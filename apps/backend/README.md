# apps/backend — Backend de Rover (Python + FastAPI)

Backend en **Python** del monorepo. A diferencia del resto de apps, **NO** forma
parte del workspace de pnpm/Turborepo: se gestiona aparte con
[**uv**](https://docs.astral.sh/uv/). Python 3.12.

Esta es la primera versión real: un esqueleto desplegable con un healthcheck.
Las features (DB, auth, agente) llegan en HUs posteriores.

## Estructura

```
app/
├── main.py            # crea la app FastAPI e incluye los routers
├── core/config.py     # Settings (pydantic-settings): APP_NAME, ENV, VERSION
└── api/v1/health.py   # GET /v1/health
tests/
└── test_health.py     # test del healthcheck
Dockerfile             # imagen de producción (Python 3.12 slim + uv, no-root)
docker-compose.yml     # servicio de desarrollo (hot-reload + puerto 8000)
```

## Healthcheck

`GET /v1/health` → `200` con JSON tipado:

```json
{ "status": "ok", "version": "0.1.0", "env": "local" }
```

## Configuración

`app/core/config.py` lee variables de entorno con prefijo `ROVER_` (defaults
sensatos, sin secretos):

| Variable        | Default  | Descripción                |
| --------------- | -------- | -------------------------- |
| `ROVER_APP_NAME`| `Rover`  | Nombre de la app.          |
| `ROVER_ENV`     | `local`  | Entorno (`local`, `prod`…).|
| `ROVER_VERSION` | `0.1.0`  | Versión (origen: `app.__version__`). |

## Correr en local (uv)

Requiere `uv` instalado. Desde `apps/backend/`:

```bash
uv sync                                        # crea .venv y resuelve dependencias
uv run uvicorn app.main:app --reload           # arranca en http://127.0.0.1:8000
# healthcheck:
curl http://127.0.0.1:8000/v1/health
```

## Correr con Docker

```bash
docker compose up --build        # build + arranque con hot-reload (dev)
# healthcheck (puerto 8000 mapeado):
curl http://127.0.0.1:8000/v1/health
docker compose down              # detener
```

El `Dockerfile` produce una imagen apta para producción (uvicorn sin `--reload`,
usuario no-root, capas cacheables) y es el que usará el deploy de HU-0.6.

## Tests

```bash
uv run pytest          # usa el TestClient de FastAPI (httpx)
```

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
