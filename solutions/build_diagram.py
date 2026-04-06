"""
Build the architecture diagram for the VaultTech final project.

Run:
    uv run python solutions/build_diagram.py

Outputs:
    solutions/architecture_diagram.png
"""

from pathlib import Path
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECR, ElasticContainerServiceService, Fargate
from diagrams.aws.ml import Sagemaker, SagemakerModel
from diagrams.aws.storage import S3
from diagrams.aws.network import VPC, PublicSubnet, InternetGateway
from diagrams.aws.management import Cloudwatch
from diagrams.aws.security import IAMRole
from diagrams.onprem.client import User

OUTPUT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = OUTPUT_DIR / "architecture_diagram"

graph_attr = {
    "fontsize": "16",
    "bgcolor": "white",
    "pad": "0.6",
    "splines": "spline",
}

with Diagram(
    "VaultTech — Forging Line Cycle Time Predictor (eu-west-1)",
    filename=str(OUTPUT_FILE),
    show=False,
    direction="LR",
    graph_attr=graph_attr,
    outformat="png",
):
    user = User("Operator\nbrowser")

    with Cluster("AWS Account · eu-west-1"):

        with Cluster("VPC 10.0.0.0/16"):
            igw = InternetGateway("Internet\nGateway")
            with Cluster("Public subnet 10.0.1.0/24"):
                with Cluster("ECS Fargate · vaultech-cluster"):
                    fargate = Fargate("Streamlit task\n(1 vCPU · 2 GB)\nport 8501")
                    task_role = IAMRole("vaultech-ecs-\ntask-role")

        ecr = ECR("ECR\nvaultech-app:latest")

        with Cluster("SageMaker"):
            endpoint = Sagemaker("Real-time endpoint\nvaultech-bath-predictor\n(ml.t2.medium)")
            registry = SagemakerModel("Model Registry\nvaultech-bath-\npredictor-group")

        s3 = S3("S3\nvaultech-models-riwad\nmodel.tar.gz")
        cw = Cloudwatch("CloudWatch logs\n/ecs/vaultech-app")

        # 1. User → Fargate via Internet Gateway
        user >> Edge(label="HTTPS\n:8501", color="darkblue", style="bold") >> igw
        igw >> Edge(color="darkblue", style="bold") >> fargate

        # 2. Fargate pulls image from ECR (one-time on task start)
        ecr >> Edge(label="docker pull", color="gray", style="dashed") >> fargate

        # 3. Fargate → SageMaker endpoint (boto3 invoke_endpoint)
        fargate >> Edge(label="boto3.invoke_\nendpoint(CSV)", color="darkgreen", style="bold") >> endpoint
        task_role >> Edge(label="sagemaker:\nInvokeEndpoint", color="darkgreen", style="dotted") >> endpoint

        # 4. Endpoint loads model artifact from S3 (at startup)
        s3 >> Edge(label="loads model.tar.gz\nat startup", color="orange", style="dashed") >> endpoint

        # 5. Model registry references S3 artifact
        registry >> Edge(label="references", color="purple", style="dotted") >> s3
        registry >> Edge(label="deploys", color="purple", style="dotted") >> endpoint

        # 6. Fargate writes logs to CloudWatch
        fargate >> Edge(label="stdout", color="gray", style="dotted") >> cw

        # 7. Endpoint returns prediction back to Fargate
        endpoint >> Edge(label="prediction\n(float CSV)", color="darkred", style="bold") >> fargate

        # 8. Fargate renders dashboard back to user
        fargate >> Edge(color="darkblue", style="bold") >> igw
        igw >> Edge(label="HTML\n+ JSON", color="darkblue", style="bold") >> user

print(f"Diagram written to: {OUTPUT_FILE}.png")
