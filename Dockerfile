# syntax=docker/dockerfile:1

# ---- Builder: resolve and install dependencies with uv -----------------------
FROM python:3.14-slim AS builder

# uv: fast, reproducible installs. Copy the static binary from the official image.
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install dependencies first (better layer caching), without the project itself.
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev || \
    uv sync --no-install-project --no-dev

# Now copy the source and install the project.
COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev || uv sync --no-dev

# ---- Runtime: minimal image, non-root user -----------------------------------
FROM python:3.14-slim AS runtime

# Create an unprivileged user.
RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

# Copy the resolved virtualenv and application code from the builder.
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src

# Alembic config + migrations so `alembic upgrade head` can run inside the container
# (e.g. a Render pre-deploy step). Small and dependency-free.
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app migrations ./migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production

USER app
EXPOSE 8000

# Liveness probe hitting the FastAPI health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

# Shell-form CMD: Docker runs it via `sh -c`, so migrations apply and then the app
# execs (replacing the shell, so it receives signals) on every container start.
CMD alembic upgrade head && exec python -m cinch.api
