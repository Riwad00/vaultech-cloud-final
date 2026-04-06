FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock README.md ./

# Install dependencies (no dev deps, no editable install yet)
RUN uv sync --no-dev --no-install-project

# Copy only what's needed to run the app — no models/, model lives in SageMaker
COPY src/ src/
COPY app/ app/
COPY models/model_metadata.json models/model_metadata.json
COPY data/gold/ data/gold/

# Install the project itself
RUN uv sync --no-dev

EXPOSE 8501

CMD ["uv", "run", "streamlit", "run", "app/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
