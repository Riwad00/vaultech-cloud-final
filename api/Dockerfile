FROM python:3.13-slim

# Install uv from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first for layer caching
COPY pyproject.toml README.md ./

# Install dependencies without the project itself
RUN uv sync --no-dev --no-install-project

# Copy source code and runtime data
COPY src/ src/
COPY reference_times.json ./

# Install the project
RUN uv sync --no-dev

EXPOSE 80

# Long-running server — use uv run uvicorn so the project environment is active
CMD ["uv", "run", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "80"]
