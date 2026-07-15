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
├── core/config.py     # Settings por ambiente (pydantic-settings) + fail-fast
└── api/v1/health.py   # GET /v1/health
tests/
├── test_health.py     # test del healthcheck
└── test_config.py     # tests de config por ambiente y fail-fast
.env.example           # plantilla de variables (el .env real NUNCA se commitea)
Dockerfile             # imagen de producción (Python 3.12 slim + uv, no-root)
docker-compose.yml     # servicio de desarrollo (hot-reload + puerto 8000)
```

## Healthcheck

`GET /v1/health` → `200` con JSON tipado:

```json
{ "status": "ok", "version": "0.1.0", "env": "local" }
```

## Configuración y secretos

`app/core/config.py` (pydantic-settings) lee variables de entorno con prefijo
`ROVER_`. Ambientes soportados: `local` | `test` | `production`.

| Variable         | Default | Descripción                          |
| ---------------- | ------- | ------------------------------------ |
| `ROVER_APP_NAME` | `Rover` | Nombre de la app.                    |
| `ROVER_ENV`      | `local` | Ambiente (`local`/`test`/`production`). |
| `ROVER_VERSION`  | `0.1.0` | Versión (origen: `app.__version__`). |

**Desarrollo local** — copia la plantilla y ajusta lo que necesites:

```bash
cp .env.example .env
```

El `.env` real está **git-ignorado y nunca se commitea** (regla de oro: ningún
secreto en el código ni en git). La plantilla versionada es `.env.example`:
documenta TODAS las variables, con placeholders, incluidas las que llegan en
Épica 1 (Supabase, LLM) marcadas como **SECRETO**.

**Producción (Render)** — no hay archivo `.env`: las variables se configuran en
el panel del servicio (**Environment**). El mismo código sirve para ambos
caminos sin cambios.

**Fail-fast** — los settings se validan al importar el módulo, así que la app
**no arranca** si la config es inválida: un `ROVER_ENV` desconocido, o una
variable obligatoria ausente en producción (lista `_REQUIRED_IN_PRODUCTION` en
`config.py`), cortan el arranque con un error que nombra la variable que falta.
El patrón para añadir secretos futuros (campo `SecretStr | None` + entrada en
esa lista + placeholder en `.env.example`) está documentado en `config.py` y
probado en `tests/test_config.py`.

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
usuario no-root, capas cacheables) y es el que usa el deploy a Render definido
en `render.yaml` (raíz del repo); ver [`docs/deploy.md`](../../docs/deploy.md).
En Render el puerto lo inyecta la plataforma vía `PORT` (el CMD usa
`${PORT:-8000}`, así que en local sigue siendo 8000).

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
