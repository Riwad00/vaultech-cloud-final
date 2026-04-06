"""
SageMaker deployment script — packages, registers, and deploys the XGBoost model.

Usage:
    uv run python deploy/deploy_sagemaker.py \
      --bucket your-bucket-name \
      --region eu-west-1 \
      --endpoint-name your-endpoint-name \
      --model-package-group your-group-name
"""

import argparse
import json
import shutil
import tarfile
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# SageMaker built-in XGBoost container account IDs per region
# https://docs.aws.amazon.com/sagemaker/latest/dg-ecr-paths/ecr-eu-west-1.html
XGBOOST_IMAGE_ACCOUNTS = {
    "eu-west-1": "141502667606",
    "us-east-1": "683313688378",
    "us-west-2": "246618743249",
}


MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_FILE = MODEL_DIR / "xgboost_bath_predictor.json"
METADATA_FILE = MODEL_DIR / "model_metadata.json"
EXECUTION_ROLE_NAME = "SageMakerExecutionRole"


def _get_execution_role_arn() -> str:
    """Get the SageMaker execution role ARN, creating it if needed."""
    iam = boto3.client("iam")
    try:
        return iam.get_role(RoleName=EXECUTION_ROLE_NAME)["Role"]["Arn"]
    except ClientError:
        trust = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "sagemaker.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }],
        }
        role = iam.create_role(
            RoleName=EXECUTION_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
        )
        for policy in [
            "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess",
            "arn:aws:iam::aws:policy/AmazonS3FullAccess",
        ]:
            iam.attach_role_policy(RoleName=EXECUTION_ROLE_NAME, PolicyArn=policy)
        time.sleep(10)  # IAM eventual consistency
        return role["Role"]["Arn"]


def package_model(model_path: Path, output_dir: Path) -> Path:
    """Package the XGBoost model as a .tar.gz archive for SageMaker."""
    # SageMaker XGBoost container expects file named 'xgboost-model' at archive root
    staging_dir = output_dir / "_sagemaker_staging"
    staging_dir.mkdir(exist_ok=True)
    staged_file = staging_dir / "xgboost-model"
    shutil.copy(model_path, staged_file)

    tar_path = output_dir / "model.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(staged_file, arcname="xgboost-model")

    shutil.rmtree(staging_dir)
    return tar_path


def upload_to_s3(local_path: Path, bucket: str, key: str) -> str:
    """Upload a local file to S3."""
    s3 = boto3.client("s3")
    s3.upload_file(str(local_path), bucket, key)
    return f"s3://{bucket}/{key}"


def register_model(
    s3_model_uri: str,
    model_package_group_name: str,
    region: str,
    metrics: dict,
) -> str:
    """Register the model in SageMaker Model Registry."""
    sm = boto3.client("sagemaker", region_name=region)

    # Create the Model Package Group if it doesn't exist
    try:
        sm.describe_model_package_group(ModelPackageGroupName=model_package_group_name)
    except ClientError:
        sm.create_model_package_group(
            ModelPackageGroupName=model_package_group_name,
            ModelPackageGroupDescription="VaultTech bath time predictor",
        )

    # Get XGBoost container image URI
    account = XGBOOST_IMAGE_ACCOUNTS.get(region)
    if not account:
        raise ValueError(f"No XGBoost image account known for region {region}")
    image_uri = f"{account}.dkr.ecr.{region}.amazonaws.com/sagemaker-xgboost:1.7-1"

    # Register the model package
    response = sm.create_model_package(
        ModelPackageGroupName=model_package_group_name,
        ModelPackageDescription="XGBoost bath time predictor",
        InferenceSpecification={
            "Containers": [{
                "Image": image_uri,
                "ModelDataUrl": s3_model_uri,
            }],
            "SupportedContentTypes": ["text/csv"],
            "SupportedResponseMIMETypes": ["text/csv"],
        },
        ModelApprovalStatus="Approved",
        CustomerMetadataProperties={
            "rmse": str(metrics["rmse"]),
            "mae": str(metrics["mae"]),
            "r2": str(metrics["r2"]),
        },
    )
    return response["ModelPackageArn"]


def deploy_endpoint(
    model_package_arn: str,
    endpoint_name: str,
    region: str,
    instance_type: str = "ml.t2.medium",
) -> str:
    """Deploy a real-time SageMaker endpoint from a registered Model Package."""
    sm = boto3.client("sagemaker", region_name=region)
    role_arn = _get_execution_role_arn()

    model_name = f"{endpoint_name}-model"
    config_name = f"{endpoint_name}-config"

    # Clean up any existing resources with the same names
    for delete_fn, kwargs in [
        (sm.delete_endpoint, {"EndpointName": endpoint_name}),
        (sm.delete_endpoint_config, {"EndpointConfigName": config_name}),
        (sm.delete_model, {"ModelName": model_name}),
    ]:
        try:
            delete_fn(**kwargs)
        except ClientError:
            pass

    # Create Model from the registered package
    sm.create_model(
        ModelName=model_name,
        ExecutionRoleArn=role_arn,
        Containers=[{"ModelPackageName": model_package_arn}],
    )

    # Create Endpoint Config
    sm.create_endpoint_config(
        EndpointConfigName=config_name,
        ProductionVariants=[{
            "VariantName": "AllTraffic",
            "ModelName": model_name,
            "InitialInstanceCount": 1,
            "InstanceType": instance_type,
        }],
    )

    # Create Endpoint and wait for InService
    sm.create_endpoint(EndpointName=endpoint_name, EndpointConfigName=config_name)
    print(f"  Waiting for endpoint to become InService (this can take ~5-10 min)...")
    waiter = sm.get_waiter("endpoint_in_service")
    waiter.wait(EndpointName=endpoint_name, WaiterConfig={"Delay": 30, "MaxAttempts": 40})

    return endpoint_name


def test_endpoint(endpoint_name: str, region: str) -> dict:
    """Test the deployed endpoint with sample pieces."""
    runtime = boto3.client("sagemaker-runtime", region_name=region)
    samples = [
        {"name": "matrix 5052 normal", "payload": "5052,18.3,13.5"},
        {"name": "matrix 5090 normal", "payload": "5090,17.8,14.0"},
        {"name": "matrix 5091 normal", "payload": "5091,18.6,13.8"},
        {"name": "matrix 5052 slow",   "payload": "5052,30.0,13.5"},
    ]
    results = {}
    for sample in samples:
        response = runtime.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="text/csv",
            Body=sample["payload"],
        )
        prediction = float(response["Body"].read().decode("utf-8").strip())
        results[sample["name"]] = {"input": sample["payload"], "predicted_bath_s": round(prediction, 2)}
    return results


def main():
    parser = argparse.ArgumentParser(description="Deploy XGBoost model to SageMaker")
    parser.add_argument("--bucket", required=True, help="S3 bucket for model artifact")
    parser.add_argument("--region", default="eu-west-1", help="AWS region")
    parser.add_argument("--endpoint-name", required=True, help="SageMaker endpoint name")
    parser.add_argument("--model-package-group", required=True, help="Model Package Group name")
    args = parser.parse_args()

    with open(METADATA_FILE) as f:
        metadata = json.load(f)

    print("=" * 60)
    print("SageMaker Deployment Pipeline")
    print("=" * 60)

    print("\n[1/5] Packaging model artifact...")
    tar_path = package_model(MODEL_FILE, MODEL_DIR)
    print(f"  Created: {tar_path}")

    print("\n[2/5] Uploading to S3...")
    s3_key = "models/xgboost-bath-predictor/model.tar.gz"
    s3_uri = upload_to_s3(tar_path, args.bucket, s3_key)
    print(f"  Uploaded: {s3_uri}")

    print("\n[3/5] Registering in Model Registry...")
    model_package_arn = register_model(
        s3_uri, args.model_package_group, args.region, metadata["metrics"]
    )
    print(f"  Registered: {model_package_arn}")

    print("\n[4/5] Deploying endpoint...")
    endpoint = deploy_endpoint(model_package_arn, args.endpoint_name, args.region)
    print(f"  Endpoint live: {endpoint}")

    print("\n[5/5] Testing endpoint...")
    results = test_endpoint(args.endpoint_name, args.region)
    print(f"  Results: {json.dumps(results, indent=2)}")

    print("\n" + "=" * 60)
    print("Deployment complete!")
    print(f"  Endpoint:       {args.endpoint_name}")
    print(f"  Model Package:  {model_package_arn}")
    print(f"  S3 artifact:    {s3_uri}")
    print("=" * 60)


if __name__ == "__main__":
    main()
