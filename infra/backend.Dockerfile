# API and worker image. Build context: backend/
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Optional: LibreOffice renders PowerPoint slides containing Office equation
# objects so Claude can read them (~500 MB). Enable with WITH_LIBREOFFICE=true.
ARG WITH_LIBREOFFICE=false
RUN if [ "$WITH_LIBREOFFICE" = "true" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends libreoffice-impress \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Dependencies first so code edits don't invalidate the layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/storage && chown -R app /data
USER app

EXPOSE 8000
CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
