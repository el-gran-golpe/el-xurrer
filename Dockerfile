# AI content pipeline image. Runtime state (resources/, .cache/, logs/, the
# Google Drive OAuth token) and secrets (.env) are never baked in: they are
# mounted/injected at run time, see docker-compose.yml.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

LABEL authors="moises"

# Match the host user so files written to bind-mounted volumes (resources/,
# .cache/, logs/, the Drive token) stay owned by that user.
ARG APP_UID=1000
ARG APP_GID=1000

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/apps/ai-content-pipeline:/app/apps/fanvue-fastapi:/app/shared/fanvue-api-client"

WORKDIR /app

# tzdata so TZ (set in docker-compose.yml) applies: planning_week_start uses
# date.today() and naive upload_time values are read in local time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first, in their own layer, so code changes do not reinstall them.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY apps/ ./apps/
COPY shared/ ./shared/

# The GID may already exist in the base image (e.g. 100 = users); reuse it.
RUN (getent group "$APP_GID" >/dev/null || groupadd --gid "$APP_GID" app) \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --create-home app \
    && mkdir -p /app/resources /app/.cache /app/logs /home/app/.config/myapp \
    && chown -R "app:$APP_GID" /app/resources /app/.cache /app/logs /home/app/.config

USER app

# The CLI resolves .env, .cache/ and logs/ relative to the working directory,
# and resources/ relative to the repo root; both are /app here.
ENTRYPOINT ["python", "apps/ai-content-pipeline/main.py"]
CMD ["--help"]
