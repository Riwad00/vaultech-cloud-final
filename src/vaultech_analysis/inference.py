"""
Inference service for predicting total piece travel time.

Loads the trained XGBoost model and provides predictions.

Usage as CLI:
    uv run python -m vaultech_analysis.inference --die-matrix 5052 --strike2 18.3 --oee 13.5

Usage as module (for Streamlit):
    from vaultech_analysis.inference import Predictor
    predictor = Predictor()
    result = predictor.predict(die_matrix=5052, lifetime_2nd_strike_s=18.3, oee_cycle_time_s=13.5)
"""

import argparse
import json
from pathlib import Path

import pandas as pd
from xgboost import XGBRegressor


MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "models"
GOLD_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "gold" / "pieces.parquet"


class Predictor:
    """Loads the trained model and provides predictions."""

    def __init__(self, model_dir: Path = MODEL_DIR, gold_file: Path = GOLD_FILE):
        # Load model metadata
        metadata_path = model_dir / "model_metadata.json"
        with open(metadata_path) as f:
            self.metadata = json.load(f)

        # Load XGBoost model
        self.model = XGBRegressor()
        self.model.load_model(str(model_dir / self.metadata["model_file"]))

        self.features = self.metadata["features"]
        self.metrics = self.metadata["metrics"]
        self.valid_matrices = self.metadata["die_matrices"]
        self.oee_median = self.metadata["oee_median"]

        # Load reference medians per die matrix from gold file
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
        """Predict total bath time from early-stage features.

        Returns a dict with predicted_bath_time_s, input values, and model_metrics.
        Returns {"error": "..."} for unknown die_matrix values.
        Missing oee_cycle_time_s defaults to the median (~13.8s).
        """
        if die_matrix not in self.valid_matrices:
            return {"error": f"Unknown die_matrix: {die_matrix}. Valid: {self.valid_matrices}"}

        # Default OEE to median if not provided
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
        """Predict bath time for a DataFrame of pieces.

        Handle missing oee_cycle_time_s by filling with the median.
        """
        input_df = df[self.features].copy()
        input_df["oee_cycle_time_s"] = input_df["oee_cycle_time_s"].fillna(self.oee_median)
        predictions = self.model.predict(input_df)
        return pd.Series(predictions, index=df.index)


def main():
    parser = argparse.ArgumentParser(description="Predict bath time from early-stage features")
    parser.add_argument("--die-matrix", type=int, required=True, help="Die matrix ID")
    parser.add_argument("--strike2", type=float, required=True, help="Lifetime at 2nd strike (seconds)")
    parser.add_argument("--oee", type=float, default=None, help="OEE cycle time (seconds, optional)")
    args = parser.parse_args()

    predictor = Predictor()
    result = predictor.predict(
        die_matrix=args.die_matrix,
        lifetime_2nd_strike_s=args.strike2,
        oee_cycle_time_s=args.oee,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
