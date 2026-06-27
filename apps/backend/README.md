# apps/backend — Backend de Rover (Python + FastAPI)

> ⚠️ Placeholder. El FastAPI real llega en **HU-0.4**.

Este directorio contiene el backend en **Python** del monorepo. A diferencia del
resto de apps, **NO** forma parte del workspace de pnpm/Turborepo: se gestiona
aparte con [**uv**](https://docs.astral.sh/uv/).

## Estado actual

- `pyproject.toml` mínimo (proyecto `rover-backend`, sin dependencias de app).
- Aún no hay código de aplicación; el scaffold de FastAPI llega en HU-0.4.

## Tooling

Requiere Python ≥ 3.12 y `uv` instalado.

```bash
# desde apps/backend/
uv sync          # crea el entorno virtual (.venv) y resuelve dependencias
uv run python -V # ejecuta dentro del entorno
```

El backend se ejecuta y prueba de forma independiente de los comandos `pnpm`
de la raíz del monorepo.

## Lint y formato (Ruff)

[Ruff](https://docs.astral.sh/ruff/) hace de linter **y** formateador (configurado
en `pyproject.toml`, `[tool.ruff]`). No está dentro de Turborepo.

```bash
uv run ruff check .        # lintea (--fix para autocorregir)
uv run ruff format .       # formatea
```

En cada commit, el hook de lefthook (definido en la raíz) corre `ruff format` y
`ruff check --fix` solo sobre los `.py` _staged_.

## Type-checking (mypy, estricto)

[mypy](https://mypy-lang.org/) en modo `strict` (configurado en `pyproject.toml`,
`[tool.mypy]`). No está dentro de Turborepo (mismo patrón que Ruff).

```bash
uv run mypy .
```
