# syntax=docker/dockerfile:1
FROM python:3.12-slim

# uv (binario oficial) para instalar dependencias de forma reproducible.
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /uvx /bin/

# Build reproducible y rápido.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# 1) Capa de dependencias (cacheable): solo se reconstruye si cambian pyproject/uv.lock.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# 2) Código de la app (capa que cambia más a menudo).
COPY app ./app

# Usuario no-root.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# El venv creado por uv vive en /app/.venv.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Producción: sin --reload (el compose lo añade solo para desarrollo).
# Render inyecta el puerto vía $PORT; en local (sin PORT) cae a 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
