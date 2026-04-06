"""
Inference service for predicting total piece travel time.

Two backends:
- LocalPredictor: loads the XGBoost model from disk and predicts in-process.
- SageMakerPredictor: invokes a deployed SageMaker endpoint via boto3.

Use get_predictor() to auto-select based on the SAGEMAKER_ENDPOINT_NAME env var.

Usage as CLI:
    uv run python -m vaultech_analysis.inference --die-matrix 5052 --strike2 18.3 --oee 13.5

Usage as module (for Streamlit):
    from vaultech_analysis.inference import get_predictor
    predictor = get_predictor()
    result = predictor.predict(die_matrix=5052, lifetime_2nd_strike_s=18.3, oee_cycle_time_s=13.5)
"""

import argparse
import json
import os
import time
from pathlib import Path

import pandas as pd
from xgboost import XGBRegressor


MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "models"
GOLD_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "gold" / "pieces.parquet"


class Predictor:
    """Local predictor — loads the XGBoost model from disk."""

    def __init__(self, model_dir: Path = MODEL_DIR, gold_file: Path = GOLD_FILE):
        metadata_path = model_dir / "model_metadata.json"
        with open(metadata_path) as f:
            self.metadata = json.load(f)

        self.model = XGBRegressor()
        self.model.load_model(str(model_dir / self.metadata["model_file"]))

        self.features = self.metadata["features"]
        self.metrics = self.metadata["metrics"]
        self.valid_matrices = self.metadata["die_matrices"]
        self.oee_median = self.metadata["oee_median"]

        if gold_file.exists():
            gold = pd.read_parquet(gold_file)
            self.reference = gold.groupby("die_matrix").median(numeric_only=True).to_dict("index")
        else:
            self.reference = {}

    def predict(
        self,
        die_matrix: int,
        lifetime_2nd_strike_s: float,
        oee_cycle_time_s: float | None = None,
    ) -> dict:
        if die_matrix not in self.valid_matrices:
            return {"error": f"Unknown die_matrix: {die_matrix}. Valid: {self.valid_matrices}"}

        oee_value = oee_cycle_time_s if oee_cycle_time_s is not None else self.oee_median

        input_df = pd.DataFrame([{
            "die_matrix": die_matrix,
            "lifetime_2nd_strike_s": lifetime_2nd_strike_s,
            "oee_cycle_time_s": oee_value,
        }])

        prediction = float(self.model.predict(input_df)[0])

        return {
            "predicted_bath_time_s": round(prediction, 2),
            "die_matrix": die_matrix,
            "lifetime_2nd_strike_s": lifetime_2nd_strike_s,
            "oee_cycle_time_s": oee_cycle_time_s,
            "model_metrics": self.metrics,
        }

    def predict_batch(self, df: pd.DataFrame) -> pd.Series:
        input_df = df[self.features].copy()
        input_df["oee_cycle_time_s"] = input_df["oee_cycle_time_s"].fillna(self.oee_median)
        predictions = self.model.predict(input_df)
        return pd.Series(predictions, index=df.index)


class SageMakerPredictor:
    """Predictor that calls a deployed SageMaker endpoint via boto3.

    Same interface as Predictor, plus an `inference_debug` field in the response
    showing the raw payload, response, and round-trip latency.
    """

    def __init__(
        self,
        endpoint_name: str,
        region: str = "eu-west-1",
        gold_file: Path = GOLD_FILE,
        valid_matrices: list[int] | None = None,
        metrics: dict | None = None,
        oee_median: float = 13.8,
    ):
        import boto3
        self.endpoint_name = endpoint_name
        self.region = region
        self.runtime = boto3.client("sagemaker-runtime", region_name=region)
        self.features = ["die_matrix", "lifetime_2nd_strike_s", "oee_cycle_time_s"]
        self.valid_matrices = valid_matrices or [4974, 5052, 5090, 5091]
        self.metrics = metrics or {"rmse": None, "mae": None, "r2": None}
        self.oee_median = oee_median

        # Load reference values from gold file (for the dashboard detail panel)
        if gold_file.exists():
            gold = pd.read_parquet(gold_file)
            self.reference = gold.groupby("die_matrix").median(numeric_only=True).to_dict("index")
        else:
            self.reference = {}

    def _invoke(self, payload: str) -> tuple[float, float]:
        """Call SageMaker and return (prediction, latency_ms)."""
        start = time.perf_counter()
        response = self.runtime.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="text/csv",
            Body=payload,
        )
        body = response["Body"].read().decode("utf-8").strip()
        latency_ms = (time.perf_counter() - start) * 1000
        return float(body), latency_ms

    def predict(
        self,
        die_matrix: int,
        lifetime_2nd_strike_s: float,
        oee_cycle_time_s: float | None = None,
    ) -> dict:
        if die_matrix not in self.valid_matrices:
            return {"error": f"Unknown die_matrix: {die_matrix}. Valid: {self.valid_matrices}"}

        oee_value = oee_cycle_time_s if oee_cycle_time_s is not None else self.oee_median
        payload = f"{die_matrix},{lifetime_2nd_strike_s},{oee_value}"

        prediction, latency_ms = self._invoke(payload)

        return {
            "predicted_bath_time_s": round(prediction, 2),
            "die_matrix": die_matrix,
            "lifetime_2nd_strike_s": lifetime_2nd_strike_s,
            "oee_cycle_time_s": oee_cycle_time_s,
            "model_metrics": self.metrics,
            "inference_debug": {
                "endpoint": self.endpoint_name,
                "region": self.region,
                "input_payload": payload,
                "raw_response": str(prediction),
                "latency_ms": round(latency_ms, 1),
            },
        }

    def predict_batch(self, df: pd.DataFrame, chunk_size: int = 5000) -> pd.Series:
        """Batch prediction via multi-row CSV.

        SageMaker XGBoost endpoints accept multiple rows in a single text/csv
        body and return one prediction per line. We chunk to stay under the
        ~5MB invocation payload limit and to keep individual calls fast.
        """
        # Build the input CSV: one row per piece, columns in training order
        input_df = df[["die_matrix", "lifetime_2nd_strike_s", "oee_cycle_time_s"]].copy()
        input_df["oee_cycle_time_s"] = input_df["oee_cycle_time_s"].fillna(self.oee_median)
        input_df["die_matrix"] = input_df["die_matrix"].astype(int)

        all_predictions = []
        for start in range(0, len(input_df), chunk_size):
            chunk = input_df.iloc[start:start + chunk_size]
            csv_payload = chunk.to_csv(index=False, header=False)
            response = self.runtime.invoke_endpoint(
                EndpointName=self.endpoint_name,
                ContentType="text/csv",
                Body=csv_payload,
            )
            body = response["Body"].read().decode("utf-8").strip()
            # Response is one prediction per line
            preds = [float(line) for line in body.split("\n") if line.strip()]
            all_predictions.extend(preds)

        return pd.Series(all_predictions, index=df.index)


def get_predictor():
    """Factory: return SageMakerPredictor if SAGEMAKER_ENDPOINT_NAME env var is set,
    otherwise return the local Predictor.
    """
    endpoint = os.environ.get("SAGEMAKER_ENDPOINT_NAME")
    if endpoint:
        region = os.environ.get("AWS_DEFAULT_REGION", "eu-west-1")
        # Try to load metadata for valid matrices and metrics if available
        metadata_path = MODEL_DIR / "model_metadata.json"
        kwargs = {}
        if metadata_path.exists():
            with open(metadata_path) as f:
                meta = json.load(f)
            kwargs = {
                "valid_matrices": meta.get("die_matrices"),
                "metrics": meta.get("metrics"),
                "oee_median": meta.get("oee_median", 13.8),
            }
        return SageMakerPredictor(endpoint_name=endpoint, region=region, **kwargs)
    return Predictor()


def main():
    parser = argparse.ArgumentParser(description="Predict bath time from early-stage features")
    parser.add_argument("--die-matrix", type=int, required=True, help="Die matrix ID")
    parser.add_argument("--strike2", type=float, required=True, help="Lifetime at 2nd strike (seconds)")
    parser.add_argument("--oee", type=float, default=None, help="OEE cycle time (seconds, optional)")
    args = parser.parse_args()

    predictor = get_predictor()
    result = predictor.predict(
        die_matrix=args.die_matrix,
        lifetime_2nd_strike_s=args.strike2,
        oee_cycle_time_s=args.oee,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
