
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim
LABEL authors="moises"

# TODO: Run this as non-root user

WORKDIR /app
COPY requirements.txt .
# TODO: reduce size of the image
# The next run layer is about 7.x GB in size
RUN apt update  \
    && apt install -y --no-install-recommends gcc python3-dev libc-dev \
    && uv venv .venv \
    && . .venv/bin/activate  \
    && uv pip install --no-cache-dir -r requirements.txt \
    && apt remove -y gcc python3-dev libc-dev && apt autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Use virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Copy only necesary files
COPY bot_services/ ./bot_services/
COPY generation_tools/ ./generation_tools/
COPY llm/ ./llm/
COPY main_components/ ./main_components/
COPY mains/ ./mains/
# TODO: this should be a volume
COPY resources/ ./resources/
COPY utils/ ./utils/

ENTRYPOINT ["python", "mains/main_meta.py"]
