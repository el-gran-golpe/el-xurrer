# TODO: use alpine to reduce the image size
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim
LABEL authors="moises"

WORKDIR /app
COPY requirements.txt .
RUN apt update && apt install -y gcc
RUN uv pip install --system --no-cache-dir -r requirements.txt

# Copy only necesary files
COPY bot_services/ ./bot_services/
COPY generation_tools/ ./generation_tools/
COPY llm/ ./llm/
COPY main_components/ ./main_components/
COPY mains/ ./mains/
COPY resources/ ./resources/
COPY utils/ ./utils/



ENTRYPOINT ["python", "mains/main_meta.py"]
