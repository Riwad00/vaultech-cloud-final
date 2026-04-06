# Demo Video Script — VaultTech Final Project

**Target length:** ≤ 5 minutes
**Recording tool (recommended):** macOS QuickTime Player → File → New Screen Recording, OR Cmd+Shift+5 → "Record Selected Portion"

---

## Setup before recording

1. Have these tabs open:
   - The architecture diagram (`solutions/architecture_diagram.png`) in Preview
   - The live app: **http://3.249.32.187:8501**
2. Make sure your AWS credentials are still valid and the Fargate task is running:
   ```bash
   curl -sf http://3.249.32.187:8501/_stcore/health
   ```
3. Close noisy apps, silence notifications.
4. Start recording.

---

## Script (~5 minutes)

### [0:00–0:10] Intro

> "Hi, I'm Riwad. This is my final project for the Cloud Platforms course at ESADE. I built an end-to-end pipeline that takes raw forging line sensor data, trains a model that predicts how long each piece will take to finish, and serves those predictions through a dashboard deployed on AWS."

### [0:10–1:30] Architecture diagram

*(Switch to the architecture_diagram.png in Preview, full screen)*

> "Let me walk you through the architecture. Everything runs in **eu-west-1**, in one AWS account.
>
> **Starting from the user on the left** — an operator opens the dashboard in their browser.
>
> The request goes through an **Internet Gateway** into a **VPC** I created with a public subnet. Inside that subnet, I have an **ECS Fargate task** running my Streamlit container, listening on port 8501. The container image lives in **ECR** — I push every new build there with `docker buildx`, making sure to target `linux/amd64` because Fargate runs on amd64.
>
> When the user selects a piece in the dashboard, the Fargate task calls the **SageMaker real-time endpoint** using `boto3.invoke_endpoint`. The task can do this because its IAM role — `vaultech-ecs-task-role` — has the `sagemaker:InvokeEndpoint` permission attached.
>
> The endpoint itself is named **`vaultech-bath-predictor`** and runs on `ml.t2.medium`. It was deployed from a **Model Package** I registered in the SageMaker Model Registry, which references the trained XGBoost model packaged as a `.tar.gz` archive in **S3** (bucket `vaultech-models-riwad`). When the endpoint starts up, it pulls that artifact down and loads it.
>
> Predictions go back the same way: SageMaker returns a CSV with the predicted bath time, the Fargate task adds it to the dashboard, and the dashboard renders it to the operator. Logs from the container stream to **CloudWatch** for debugging."

### [1:30–2:00] Open the live app

*(Switch to the browser, navigate to http://3.249.32.187:8501)*

> "And here is the actual app, running live on Fargate. The URL is the public IP of the task. The dashboard is loading the gold dataset — about 169,000 forged pieces — and is calling SageMaker to get predictions for all of them. Because I batch the predictions in multi-row CSV chunks, this completes in about 5 seconds instead of taking 10 minutes one row at a time."

*(Wait for the dashboard to fully load.)*

> "Once it's loaded, you can see the summary metrics at the top: total pieces, the median actual bath time, the median predicted time, and the mean absolute error of the predictions. Below that is the table of all pieces."

### [2:00–3:00] Use the filters

*(In the sidebar, set die matrix to just `5052`, leave date range full)*

> "I can filter by die matrix — let's pick **5052**. The table updates immediately. Each die matrix has different tooling, so they have slightly different median bath times. Matrix 5052 sits around 57.5 seconds.
>
> I can also toggle 'show only slow pieces' to see only the pieces in the 90th percentile of bath time for their matrix."

*(Toggle the slow-pieces filter on, then off.)*

### [3:00–4:00] Click a piece — show the inference debug panel

*(Click any row in the table.)*

> "This is the key part. When I click a piece, the dashboard shows the detail panel — the actual cumulative travel times at each stage compared to the matrix reference, the partial times between stages, and a bar chart of actual versus reference for each segment.
>
> But the part I want to highlight is **this expander right here — 'Inference Debug — SageMaker endpoint call'**.
>
> This is the proof that the prediction is coming from SageMaker, not from a local copy of the model:
>
> - **Endpoint:** `vaultech-bath-predictor` — that's the live endpoint
> - **Region:** `eu-west-1`
> - **Input payload:** the exact CSV string sent to SageMaker — die matrix, lifetime at 2nd strike, OEE cycle time
> - **Raw response:** the floating-point number SageMaker returned
> - **Latency:** the round-trip time in milliseconds
>
> If I click another piece..."

*(Click another row.)*

> "... you can see a different payload, a different response, and a different latency. The model file is not in the Docker image — I removed `models/xgboost_bath_predictor.json` from the Dockerfile in task 11. The container only has `model_metadata.json` so it knows the valid die matrices and the OEE median for filling missing values."

### [4:00–4:45] Recap the data flow

*(Switch back to the architecture diagram, point at the arrows as you describe them.)*

> "So end to end: **browser** sends an HTTPS request to port 8501 → it goes through the **Internet Gateway** into the **public subnet** → reaches the **Fargate task** running Streamlit → Streamlit calls **`boto3.invoke_endpoint`** with the piece's features as CSV → the **SageMaker endpoint** runs the **XGBoost model** that was loaded from **S3** at startup → returns a single float → Streamlit renders it in the dashboard, including the inference debug panel I just showed.
>
> The model was originally trained in a Jupyter notebook, packaged with `tarfile` so it's a `model.tar.gz` with the file named `xgboost-model` at the root, uploaded to S3, and registered in the **Model Registry** so I can roll back to previous versions if needed."

### [4:45–5:00] Wrap up

> "All twelve tasks of the project are complete. The model gets an R-squared of 0.69 and a mean absolute error of 0.92 seconds on a roughly 58-second journey, which is enough to flag slow pieces in real time. Thanks for watching."

*(Stop recording.)*

---

## Things to verify after recording

- [ ] Video is under 5 minutes
- [ ] Architecture diagram is shown clearly
- [ ] Public Fargate URL is visible in the browser address bar
- [ ] At least one click on a piece shows the SageMaker debug panel with payload + response + latency
- [ ] No sensitive AWS credentials are visible on screen (terminal closed, no `.aws_env` open)
- [ ] Save as `solutions/demo_video.mp4`

## Tips

- If your video is too long, the easiest cut is the architecture diagram explanation — you can shorten the component descriptions or skip the IAM role detail.
- If your video is too short, talk a bit more about the prediction comparison: "MAE of 0.92 seconds means predictions are usually within one second of the actual bath time."
- Speak slowly and clearly — graders watching at 1.5x can speed it up; they can't slow it down without losing audio quality.
