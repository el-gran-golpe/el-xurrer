FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

LABEL authors="moises"

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/apps/ai-content-pipeline:/app/apps/fanvue-fastapi:/app/shared/fanvue-api-client"

COPY pyproject.toml uv.lock ./

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc python3-dev libc-dev \
    && uv sync --no-dev --no-install-project \
    && apt-get remove -y gcc python3-dev libc-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Runtime resources should be mounted or synced, not baked into the image.
COPY apps/ ./apps/
COPY shared/ ./shared/

ENTRYPOINT ["python", "apps/ai-content-pipeline/main.py"]
