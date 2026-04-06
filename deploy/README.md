# Deployment

## SageMaker deployment

Run the deployment script:

```bash
uv run python deploy/deploy_sagemaker.py \
  --bucket vaultech-models-riwad \
  --region eu-west-1 \
  --endpoint-name vaultech-bath-predictor \
  --model-package-group vaultech-bath-predictor-group
```

The script will:
1. Package the trained XGBoost model as `model.tar.gz` (with file renamed to `xgboost-model` at archive root)
2. Upload to S3
3. Register a Model Package in the Model Registry (auto-creating the group if needed)
4. Deploy the endpoint on `ml.t2.medium` and wait until `InService`
5. Run sample predictions to verify

## Resource names

| Resource | Name |
|---|---|
| S3 bucket | `vaultech-models-riwad` |
| Model Package Group | `vaultech-bath-predictor-group` |
| Endpoint name | `vaultech-bath-predictor` |
| Endpoint Config | `vaultech-bath-predictor-config` |
| Model | `vaultech-bath-predictor-model` |
| IAM execution role | `SageMakerExecutionRole` |
| AWS region | `eu-west-1` |
| Container | `sagemaker-xgboost:1.7-1` (account 141502667606 in eu-west-1) |

## Validate

```bash
export SAGEMAKER_MODEL_PACKAGE_GROUP="vaultech-bath-predictor-group"
export SAGEMAKER_ENDPOINT_NAME="vaultech-bath-predictor"
export AWS_DEFAULT_REGION="eu-west-1"
uv run pytest tests/test_sagemaker.py -v
```

All 7 tests must pass.

## Important: XGBoost version compatibility

The SageMaker built-in XGBoost 1.7-1 container uses XGBoost 1.7.x. The training notebook (`notebooks/05_feature_selection_and_model.ipynb`) and the project's `pyproject.toml` pin `xgboost==1.7.6` so the model file is compatible with the container.

The deployment script also strips feature names from the saved model (`booster.feature_names = None`) before packaging, because the SageMaker container receives unnamed CSV columns at inference time and cannot match named features to positional CSV input.

## Re-run

To re-deploy with a fresh model:
1. Re-run notebook 05 to retrain
2. Re-run the deploy script — it will automatically delete the existing endpoint, config, and model and recreate them

## Cleanup (cost management)

After grading, delete all AWS resources to avoid charges:

```bash
aws sagemaker delete-endpoint --endpoint-name vaultech-bath-predictor --region eu-west-1
aws sagemaker delete-endpoint-config --endpoint-config-name vaultech-bath-predictor-config --region eu-west-1
aws sagemaker delete-model --model-name vaultech-bath-predictor-model --region eu-west-1
aws s3 rb s3://vaultech-models-riwad --force
```
