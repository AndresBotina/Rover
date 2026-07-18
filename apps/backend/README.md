# apps/backend — Backend de Rover (Python + FastAPI)

Backend en **Python** del monorepo. A diferencia del resto de apps, **NO** forma
parte del workspace de pnpm/Turborepo: se gestiona aparte con
[**uv**](https://docs.astral.sh/uv/). Python 3.12.

Esta es la primera versión real: un esqueleto desplegable con un healthcheck.
Las features (DB, auth, agente) llegan en HUs posteriores.

## Estructura

```
app/
├── main.py            # crea la app FastAPI (lifespan: dispose de la DB al apagar)
├── core/config.py     # Settings por ambiente (pydantic-settings) + fail-fast
├── core/database.py   # SQLAlchemy 2.0 async + asyncpg: engine, get_db, Base
└── api/v1/health.py   # GET /v1/health y GET /v1/health/db
tests/
├── test_health.py     # test del healthcheck
├── test_config.py     # tests de config por ambiente y fail-fast
└── test_database.py   # tests de la capa DB SIN base real (SQLite en memoria)
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
| `ROVER_DATABASE_URL` | — | **SECRETO.** URL directa de Supabase Postgres, tal cual la da Supabase (`postgresql://…`). Obligatoria en producción. |

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

## Base de datos (Supabase Postgres, async)

`app/core/database.py` (HU-1.1): SQLAlchemy 2.0 async + asyncpg. La URL se
guarda en config **tal cual la entrega Supabase** (`postgresql://…`); el código
le cambia el driver a `postgresql+asyncpg://` al crear el engine. El engine es
**perezoso** (se crea en el primer uso: local/test arrancan sin base
configurada) y se cierra en el lifespan. Los endpoints reciben sesión con la
dependencia `get_db` (una `AsyncSession` por request); los modelos futuros
heredan de `Base` (HU-1.10).

**Transaction Pooler de Supabase** — se usa la URL del pooler (Supavisor,
puerto 6543) en vez de la conexión directa: la directa resuelve a **IPv6** y ni
la red local ni Render tienen salida IPv6. El código **detecta el pooler por la
URL** (host `pooler.supabase.com` o puerto 6543, sin flag manual) y en ese caso
desactiva los prepared statements de asyncpg (`statement_cache_size=0` + nombres
únicos) — el pooling en modo transacción no garantiza que dos consultas caigan
en la misma conexión, y los prepared statements viven en una conexión concreta.
Además usa `NullPool`: el pooling real lo hace Supavisor. Todo esto es
**reversible**: con una URL directa (puerto 5432) se vuelve al comportamiento
por defecto (prepared statements + pool propio con `pool_pre_ping`).

**Verificar la conexión en local** (con `ROVER_DATABASE_URL` puesta en `.env`):

```bash
uv run uvicorn app.main:app          # terminal 1
curl http://127.0.0.1:8000/v1/health/db   # terminal 2
# ok:    {"status":"ok","detail":null}
# fallo: 503 {"status":"error","detail":"No se pudo conectar a la base de datos."}
```

El error nunca incluye la causa real (la URL o el mensaje del driver podrían
contener credenciales); el detalle queda en los logs del servidor. Los tests
NO tocan Supabase: sustituyen la fábrica de sesiones por SQLite async en
memoria (ver `tests/test_database.py`), así el CI pasa sin secretos.

## Migraciones (Alembic)

El esquema se versiona con Alembic (`alembic.ini` + `migrations/`), configurado
para el engine **async** del proyecto: `migrations/env.py` reutiliza la URL de
`ROVER_DATABASE_URL` (vía `app.core.config`) y la misma construcción de engine
que la app (`build_async_url` + `engine_kwargs`, detección del pooler
incluida). La URL **nunca** se escribe en `alembic.ini`: ese archivo se
versiona y la URL es un secreto.

Comandos (desde `apps/backend/`, con `ROVER_DATABASE_URL` en `.env`):

```bash
uv run alembic revision --autogenerate -m "descripción"  # nueva migración desde los modelos
uv run alembic upgrade head    # aplicar hasta la última revisión
uv run alembic downgrade -1    # revertir la última (con `base` revierte todo)
uv run alembic current         # revisión aplicada en la base
uv run alembic history         # historial de revisiones
```

`--autogenerate` compara `Base.metadata` con la base real; cuando existan
modelos (HU-1.10), basta con importar sus módulos en `migrations/env.py` para
que Alembic los vea. Las migraciones generadas pasan solas por `ruff --fix` +
`ruff format` (hooks en `alembic.ini`). La primera revisión es una **baseline
sin tablas** (los modelos llegan en HU-1.10). Cómo se aplican las migraciones
en producción: ver [`docs/deploy.md`](../../docs/deploy.md).

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
