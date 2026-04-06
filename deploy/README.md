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

## ECS/Fargate deployment (Task 11)

Resource names:

| Resource | Name / ID |
|---|---|
| ECR repository | `126279419868.dkr.ecr.eu-west-1.amazonaws.com/vaultech-app` |
| ECS cluster | `vaultech-cluster` |
| ECS service | `vaultech-service` |
| Task definition | `vaultech-app:1` (1 vCPU, 2 GB memory, Fargate) |
| Task role | `vaultech-ecs-task-role` (with `sagemaker:InvokeEndpoint`) |
| Execution role | `ecsTaskExecutionRole` |
| VPC | `vpc-087b79541090265bd` (10.0.0.0/16) |
| Public subnet | `subnet-025c2b91b0c8ea4d2` (10.0.1.0/24, eu-west-1a) |
| Internet gateway | `igw-05e3c875c68ca088e` |
| Security group | `sg-0f162bc25ad53b229` (allows TCP 8501) |
| CloudWatch log group | `/ecs/vaultech-app` |

The task definition (`deploy/ecs-task-definition.json`) sets `SAGEMAKER_ENDPOINT_NAME=vaultech-bath-predictor` so the app's `get_predictor()` factory uses `SageMakerPredictor` instead of the local model.

### Re-deploy after code changes

```bash
# 1. Build for linux/amd64 (NOT arm64 — Fargate runs amd64)
docker buildx build --platform linux/amd64 -t vaultech-app:sagemaker --load .

# 2. Tag and push
ECR_URI="126279419868.dkr.ecr.eu-west-1.amazonaws.com/vaultech-app"
docker tag vaultech-app:sagemaker "${ECR_URI}:latest"
docker push "${ECR_URI}:latest"

# 3. Force ECS to pull the new image
aws ecs update-service --cluster vaultech-cluster --service vaultech-service \
  --force-new-deployment --region eu-west-1
```

### Get the public URL

```bash
TASK=$(aws ecs list-tasks --cluster vaultech-cluster --service-name vaultech-service \
  --region eu-west-1 --query 'taskArns[0]' --output text)
ENI=$(aws ecs describe-tasks --cluster vaultech-cluster --tasks $TASK --region eu-west-1 \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' --output text)
aws ec2 describe-network-interfaces --network-interface-ids $ENI --region eu-west-1 \
  --query 'NetworkInterfaces[0].Association.PublicIp' --output text
```

## Cleanup (cost management)

After grading, delete all AWS resources to avoid charges:

```bash
# ECS / Fargate
aws ecs update-service --cluster vaultech-cluster --service vaultech-service \
  --desired-count 0 --region eu-west-1
aws ecs delete-service --cluster vaultech-cluster --service vaultech-service --region eu-west-1
aws ecs delete-cluster --cluster vaultech-cluster --region eu-west-1

# ECR
aws ecr delete-repository --repository-name vaultech-app --force --region eu-west-1

# SageMaker
aws sagemaker delete-endpoint --endpoint-name vaultech-bath-predictor --region eu-west-1
aws sagemaker delete-endpoint-config --endpoint-config-name vaultech-bath-predictor-config --region eu-west-1
aws sagemaker delete-model --model-name vaultech-bath-predictor-model --region eu-west-1

# S3
aws s3 rb s3://vaultech-models-riwad --force

# VPC infra
aws ec2 delete-security-group --group-id sg-0f162bc25ad53b229 --region eu-west-1
aws ec2 delete-subnet --subnet-id subnet-025c2b91b0c8ea4d2 --region eu-west-1
aws ec2 detach-internet-gateway --internet-gateway-id igw-05e3c875c68ca088e --vpc-id vpc-087b79541090265bd --region eu-west-1
aws ec2 delete-internet-gateway --internet-gateway-id igw-05e3c875c68ca088e --region eu-west-1
aws ec2 delete-vpc --vpc-id vpc-087b79541090265bd --region eu-west-1
```
