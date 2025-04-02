# TODO: use alpine to reduce the image size
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim
LABEL authors="moises"

# TODO: Improve this copy to exclude the resources/outputs
COPY . /app
WORKDIR /app



RUN apt update && apt install -y \
    gcc
RUN uv pip install --system --no-cache-dir -r requirements.txt


ENTRYPOINT [".venv/bin/python", "mains/main_meta.py"]
