# apps/backend — Backend de Rover (Python + FastAPI)

Backend en **Python** del monorepo. A diferencia del resto de apps, **NO** forma
parte del workspace de pnpm/Turborepo: se gestiona aparte con
[**uv**](https://docs.astral.sh/uv/). Python 3.12.

Esta es la primera versión real: un esqueleto desplegable con un healthcheck.
Las features (DB, auth, agente) llegan en HUs posteriores.

## Estructura

```
app/
├── main.py            # crea la app FastAPI (metadatos OpenAPI, lifespan)
├── core/config.py     # Settings por ambiente (pydantic-settings) + fail-fast
├── core/database.py   # SQLAlchemy 2.0 async + asyncpg: engine, get_db, Base
├── core/security.py   # validación local del JWT de Supabase (JWKS cacheado)
├── core/errors.py     # formato ÚNICO de error + handlers centralizados
├── core/rate_limit.py # rate limiting: almacén, política y IP tras el proxy
├── api/middleware.py  # middleware ASGI que aplica el límite por IP
├── api/deps.py        # get_current_user + cuota por usuario + esquema Bearer
└── api/v1/
    ├── router.py      # AGREGADOR: monta /v1 y describe los tags de OpenAPI
    ├── health.py      # GET /v1/health y /v1/health/db
    ├── auth.py        # POST /v1/auth/register y /v1/auth/login
    └── users.py       # GET y PATCH /v1/users/me
tests/
├── test_health.py     # test del healthcheck
├── test_openapi.py    # estructura de la API y docs (tags, seguridad, /docs)
├── test_errors.py     # formato único de error y blindaje de los 500
├── test_config.py     # tests de config por ambiente y fail-fast
├── test_rate_limit.py # almacén, IP tras el proxy y límites aplicados
├── conftest.py        # aísla el contador de rate limiting entre tests
└── test_database.py   # tests de la capa DB SIN base real (SQLite en memoria)
.env.example           # plantilla de variables (el .env real NUNCA se commitea)
Dockerfile             # imagen de producción (Python 3.12 slim + uv, no-root)
docker-compose.yml     # servicio de desarrollo (hot-reload + puerto 8000)
```

**Organización de la API.** Cada dominio tiene su router (`health`, `auth`,
`users`) declarado **sin** prefijo de versión; `api/v1/router.py` los agrega y
pone `/v1` en un único sitio, y `main.py` monta solo ese agregador. Publicar una
`/v2` es añadir otro agregador, no editar cada `include_router`.

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
| `ROVER_ENABLE_DOCS` | según ambiente | Fuerza el encendido/apagado de `/docs`, `/redoc` y `/openapi.json`. |
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
# ok:    {"status":"ok"}
# fallo: 503 {"error":{"code":"service_unavailable","message":"No se pudo conectar a la base de datos.","details":null,"error_id":null}}
```

El error nunca incluye la causa real (la URL o el mensaje del driver podrían
contener credenciales); el detalle queda en los logs del servidor. Los tests
NO tocan Supabase: sustituyen la fábrica de sesiones por SQLite async en
memoria (ver `tests/test_database.py`), así el CI pasa sin secretos.

## Autenticación (Supabase Auth)

La identidad se delega en **Supabase Auth**: el backend no firma JWT propios,
sino que valida los de Supabase. Toda la interacción con el proveedor vive en
`app/services/auth.py` (HTTP directo contra GoTrue); ningún otro módulo habla
con Supabase.

> **Renovación de sesión:** el backend **no** la implementa —valida el access
> token y responde `401` cuando ya no vale— y **no** expone un endpoint de
> refresh. Quien renueva es el SDK de Supabase en el cliente. El flujo completo
> (rotación, fallo → re-login, almacenamiento de tokens, y qué debe hacer cada
> cliente) está en [`docs/auth.md`](../../docs/auth.md).

### `POST /v1/auth/register`

Registra un usuario (email + contraseña) y crea su fila de **perfil** local de
forma idempotente. Responde **201** en dos casos, que el cliente distingue por
el campo `status` (nunca inspeccionando si `session` es nula):

- **`status: "active"`** — la confirmación de email está desactivada; la
  respuesta incluye `session` (access + refresh token de Supabase). El cliente
  guarda la sesión y **entra directo**.

  ```json
  {
    "status": "active",
    "user": { "id": "…uuid…", "email": "ana@example.com" },
    "session": { "access_token": "…", "refresh_token": "…", "token_type": "bearer" }
  }
  ```

- **`status: "pending_email_confirmation"`** — con "Confirm email" activado en
  Supabase (lo deseable en producción), el usuario se crea pero **aún no hay
  sesión**. `session` es `null`. El cliente muestra **"revisa tu correo"** y no
  intenta iniciar sesión hasta que el usuario confirme.

  ```json
  {
    "status": "pending_email_confirmation",
    "user": { "id": "…uuid…", "email": "ana@example.com" },
    "session": null
  }
  ```

En web y móvil, usa el cliente tipado de `@rover/shared`: `RegisterResponse` es
una unión discriminada por `status`, así que `if (res.status === "active")`
estrecha el tipo y da acceso a `res.session` sin castings.

Errores (respuesta genérica; la causa real queda en los logs del servidor):
`409` email ya registrado · `422` email/contraseña inválidos · `429` demasiados
intentos (rate limit de Supabase) · `503` fallo del proveedor. La contraseña
nunca viaja en las respuestas de error (ni siquiera en las de validación).

### `POST /v1/auth/login`

Valida credenciales contra Supabase y devuelve **200** con el usuario y la
sesión (el login **siempre** abre sesión). El login **no** crea el perfil
local: si un usuario autenticado aún no tiene perfil, lo materializa el
middleware de la HU-1.6, por donde pasa toda petición autenticada (así la
lógica vive en un solo sitio).

```json
{
  "user": { "id": "…uuid…", "email": "ana@example.com" },
  "session": { "access_token": "…", "refresh_token": "…", "token_type": "bearer" }
}
```

Errores:

- **`401`** — credenciales inválidas. **Mismo** mensaje (`"Email o contraseña
  incorrectos."`) tanto si el email no existe como si la contraseña es
  incorrecta: no se revela si la cuenta existe.
- **`403`** — el email **no está confirmado** (las credenciales son correctas,
  pero falta confirmar el correo). Es un estado distinto de "credenciales
  malas", así que usa otro status **y** un código explícito para que el cliente
  muestre "confirma tu correo" sin inferir:

  ```json
  {
    "error": {
      "code": "email_not_confirmed",
      "message": "Debes confirmar tu correo antes de iniciar sesión.",
      "details": null,
      "error_id": null
    }
  }
  ```

- **`429`** rate limit (`rate_limited`) · **`503`** fallo del proveedor
  (`service_unavailable`).

En `@rover/shared`, `ApiClient.login()` devuelve `LoginResponse` (usuario +
sesión) y lanza `ApiError` en los casos de error, con `status` **y** `code`
(por el `code` es por donde se ramifica, ver [Formato de errores](#formato-de-errores)).

### Middleware de auth (rutas protegidas)

Las rutas protegidas validan el **access token de Supabase** (un JWT) con la
dependencia `get_current_user`. La validación es **local**, no remota: no se
pregunta a Supabase por cada petición. Supabase firma con **ES256** y publica
las claves en un **JWKS**; el backend descarga ese JWKS (derivado de
`ROVER_SUPABASE_URL`), lo **cachea** en memoria (TTL de 10 min, con refresco al
ver un `kid` desconocido y un cooldown para no martillar el endpoint), y
verifica firma, **expiración**, **issuer** y **audiencia**. `get_current_user`
resuelve el **perfil local** del usuario y, si no existe, lo **crea de forma
perezosa e idempotente** — este es el único punto donde el perfil se
materializa (lo que el registro y el login posponen).

El token va en el header:

```
Authorization: Bearer <access_token>
```

Cualquier fallo de autenticación (sin token, esquema incorrecto, malformado,
firma inválida, expirado, issuer/audiencia incorrectos, `kid` desconocido)
responde un **`401` uniforme** — mismo cuerpo para todos los motivos, para no
revelar cuál falló; el motivo real solo va al **log** del servidor. Un problema
de infraestructura (JWKS o base de datos no disponibles) responde **`503`**.

El esquema **Bearer** está declarado en OpenAPI (`bearer_scheme` en
`api/deps.py`), así que `/docs` marca las rutas protegidas y su botón
**Authorize** manda el token. Es **solo documentación**: la validación sigue
siendo la de `get_current_user` — la librería no se usa para extraer el token
porque colapsaría "sin header" e "esquema inválido" en el mismo caso y
perderíamos el motivo preciso en el log.

## Perfil de usuario (`/v1/users/me`)

Router por dominio (`users`, aparte de `auth`), protegido por el mismo
middleware. El id del usuario **siempre** sale del token, nunca del cuerpo ni
de la URL (por eso es `/me`, no `/users/{id}`): un usuario no puede leer ni
tocar el perfil de otro.

- **`GET /v1/users/me`** → perfil completo: `id`, `email`, `plan`,
  `preferences` y timestamps. Es también el endpoint de **identidad** ("¿quién
  soy?", "¿sigue válida mi sesión?"): ver la nota de consolidación al final.
- **`PATCH /v1/users/me`** → actualiza **solo `preferences`**.
  - **Merge superficial** (no reemplazo): las claves de primer nivel enviadas
    se fijan, las no mencionadas se conservan. Elegido porque web y móvil
    envían actualizaciones parciales; con reemplazo tendrían que
    leer-modificar-escribir el objeto entero (y dos clientes se pisarían).
  - `preferences` debe ser un **objeto** JSON (un array/número/string → `422`)
    y su tamaño se acota (**8 KB** del JSON resultante → `422`), para no
    guardar payloads enormes.
  - **Solo `preferences` es editable.** Un intento de cambiar `plan`, `id` o
    `email` responde **`422`** (campos desconocidos rechazados, no ignorados):
    exponer campos de más en un PATCH es una vía clásica de escalada de
    privilegios (ascenderse a un plan de pago). `plan`/`id`/`email` los
    gobiernan Supabase y la monetización.

En `@rover/shared`: `getProfile(accessToken)` y `updateProfile(accessToken,
{ preferences })`; el tipo `ProfileUpdate` impide, a nivel de tipos, enviar
campos no editables.

> **Consolidación (HU-1.9): `/v1/auth/me` se retiró.** Existía como
> verificación del middleware antes de que hubiera endpoints de perfil, y
> devolvía `(id, email, plan)`: un **subconjunto estricto** de `/v1/users/me`
> obtenido con **exactamente el mismo trabajo** (validar el token y leer la
> fila del perfil, que el middleware carga igual para materializarla). No era
> un "check ligero": solo era la misma respuesta con menos campos. Mantener dos
> rutas para la misma pregunta costaba dos contratos, dos métodos en
> `@rover/shared` y una duda para el cliente ("¿cuál llamo?"), sin ganar nada.
> Quien solo quiera la identidad usa `getProfile()` y lee `id`/`email`/`plan`.

## Documentación de la API (OpenAPI)

`/docs` (Swagger UI), `/redoc` y `/openapi.json`. El esquema lleva título,
versión (de `app.__version__`, una sola fuente de verdad), descripción,
**tags por dominio** con su explicación, `summary`/`description` por operación,
ejemplos de cuerpo y los **códigos de error** documentados (`401`, `403`,
`409`, `422`, `429`, `503`) con el *cuándo* de cada uno — nunca el motivo
concreto de un rechazo de auth, que sigue siendo uniforme.

**En producción están apagadas por defecto.** El esquema es el mapa completo de
la API (rutas, cuerpos, errores): publicarlo regala trabajo de reconocimiento a
quien busque superficie de ataque, y los clientes propios consumen
`@rover/shared`, no la UI. La regla vive en `Settings.docs_enabled`:

| `ROVER_ENV`  | `ROVER_ENABLE_DOCS` | `/docs`, `/redoc`, `/openapi.json` |
| ------------ | ------------------- | ---------------------------------- |
| `local`/`test` | sin definir       | **activas**                        |
| `production` | sin definir         | **404** (apagadas)                 |
| cualquiera   | `true` / `false`    | manda la variable                  |

Apagarlas desmonta también `/openapi.json` (sin esquema no hay nada que
renderizar). El default es por ambiente para que no se pueda *olvidar*
apagarlas: exponerlas en producción exige pedirlo explícitamente.

## Formato de errores

**Toda** respuesta no-2xx de la API —de un endpoint, de la validación o de un
fallo inesperado— tiene la misma forma (`app/core/errors.py`):

```json
{
  "error": {
    "code": "email_already_exists",
    "message": "Ya existe una cuenta con ese email.",
    "details": null,
    "error_id": null
  }
}
```

- **`code`** — estable y legible por máquina. **Por aquí se ramifica**, no por
  el status: un `422` puede ser `validation_error`, `weak_password`,
  `invalid_email` o `preferences_too_large`, y el cliente necesita
  distinguirlos sin leer mensajes (que cambian y se traducen). Los `error_code`
  **crudos de Supabase nunca se exponen**: se traducen a códigos de dominio,
  igual que las excepciones — atar los clientes al proveedor sería revivir el
  acoplamiento que `services/auth.py` existe para contener.
- **`message`** — seguro de mostrar al usuario; nunca lleva diagnóstico del
  proveedor, de la base ni de la excepción.
- **`details`** — objeto opcional. En un `422` de validación trae `errors` con
  los fallos campo a campo (**sin** el valor de campos sensibles: la contraseña
  jamás viaja de vuelta).
- **`error_id`** — solo en los `500`. Ver más abajo.

Los discriminantes que antes eran casos especiales viven ahora **dentro** del
formato: el "email sin confirmar" del `403` ya no es un `detail.reason`, es
`code: "email_not_confirmed"`. Y el **`401` uniforme se mantiene**: todos los
fallos de token dan exactamente el mismo cuerpo (`unauthenticated`), sin pistas
sobre cuál falló.

Los endpoints **lanzan `ApiError(status, code, mensaje)`** —semántica—; la forma
la deciden los handlers, registrados en `create_app()`:

| Excepción | Handler | Resultado |
| --------- | ------- | --------- |
| `ApiError` | `api_error_handler` | su status, código y mensaje |
| `RequestValidationError` | `validation_exception_handler` | `422` `validation_error` + `details.errors` saneados |
| `HTTPException` (framework) | `http_exception_handler` | código por status (404, 405…) |
| `Exception` | `unhandled_exception_handler` | `500` blindado |

**Los 500 no filtran nada.** El cliente recibe siempre el mismo mensaje
genérico más un `error_id` opaco de 12 caracteres; **nunca** el tipo de la
excepción, su mensaje ni la traza (ahí es donde aparecerían la URL de la base
con su contraseña, una llave o un token). Ese mismo `error_id` se registra a
nivel `error` junto a la causa real y el método y ruta de la petición —no la
query string ni las cabeceras, para que un token en `Authorization` no acabe en
los logs—. Es el único puente entre lo que ve el usuario y lo que ve quien
depura:

```
ERROR app.core.errors: Error no controlado [error_id=9f2c1ab4e77d] en GET /v1/users/me
Traceback (most recent call last): …
```

En `@rover/shared`: `isApiErrorResponse` parsea **cualquier** error de la API, y
`ApiClient` lo convierte en un `ApiError` con `status`, `code`, `details` y
`errorId`. El tipo de `code` admite strings desconocidos a propósito: un cliente
ya publicado debe poder parsear un error cuyo código aún no conocía.

## Rate limiting (HU-1.7)

Tres controles, con contadores **independientes** (agotar uno no gasta otro):

| Ámbito | Clave | Dónde se aplica | Defecto |
| --- | --- | --- | --- |
| **Global** | IP | toda la API (`api/middleware.py`) | 120 / min |
| **Auth** | IP | `POST /v1/auth/login` y `/register` | 10 / min |
| **Usuario** | id del token | rutas protegidas (`api/deps.py`) | 60 / min |

**Por qué esos valores.** El global (2 req/s sostenidas) es holgado para un
cliente real y acota a una sola fuente abusiva. El de auth es el estricto porque
es donde se adivinan contraseñas: con 10/min, probar un diccionario de 10.000
contraseñas pasa de minutos a casi 17 horas **por IP**. El de usuario es más
estricto que el global a propósito: el global protege la máquina, este acota lo
que consume una cuenta.

**Por qué por IP y por usuario.** Antes de autenticarse la IP es lo único que
hay —y es justo el caso de login/registro—. Después, la cuenta es mejor clave:
detrás de un NAT o de una operadora móvil mucha gente legítima comparte
dirección, y limitar solo por IP dejaría que uno se comiera el cupo de todos.
Además el token está firmado (no se falsifica), y la cuota por plan es por
definición del usuario. Una ruta protegida pasa por los dos controles: son
cosas distintas y manda el más estricto.

**Algoritmo: ventana deslizante** por marcas de tiempo. Frente a la ventana
fija, no permite la ráfaga del doble del límite a caballo del corte (con 10/min:
diez peticiones a las 11:59:59 y diez a las 12:00:00) — justo el agujero que
importa en el login. Cuesta O(N) marcas por clave, pero N es el propio límite
(10–120): unos cientos de bytes. A cambio el `Retry-After` es exacto, no una
estimación. Detalle y comparación con token bucket en `app/core/rate_limit.py`.

**IP real detrás del proxy.** `X-Forwarded-For` es una lista donde cada proxy
**añade al final** la dirección de quien le habló; la primera entrada la escribe
el cliente y es falsificable. Se lee la entrada `ROVER_RATE_LIMIT_TRUSTED_PROXIES`-ésima
**empezando por el final** (1 por defecto = el edge de Render):

```
X-Forwarded-For: 1.2.3.4, 203.0.113.7
                 ────┬───  ─────┬─────
        lo pone el cliente      lo pone Render → esta es la que se usa
```

Con `0` la cabecera se ignora del todo y se usa el peer TCP: sin un proxy de
confianza delante, cualquier `X-Forwarded-For` lo escribió el cliente. Las
entradas que no son una IP válida se descartan (si no, mandar basura distinta en
cada petición crearía una clave nueva cada vez y haría crecer el almacén sin
límite).

**Respuesta al exceder el límite:** `429` con el [formato único de
error](#formato-de-errores), `code: "rate_limited"` y las cabeceras
`Retry-After` (segundos, nunca 0), `X-RateLimit-Limit`, `X-RateLimit-Remaining`
y `X-RateLimit-Reset`. Es el **mismo `code`** que el 429 nacido de un rechazo
del proveedor de identidad: la acción del cliente es idéntica y el catálogo es
de dominio, no de origen. En `@rover/shared`, `isRateLimitedError` lo distingue
y `ApiError.retryAfterSeconds` trae la espera ya parseada.

### Limitación del almacén en memoria — LEER ANTES DE ESCALAR

El conteo vive en la **memoria del proceso**:

> Con **varias instancias** del backend el conteo **NO es global**: cada
> proceso cuenta lo suyo, así que el límite efectivo se multiplica por el número
> de instancias.

Es aceptable **hoy** porque el despliegue es de una sola instancia. El punto de
cambio está aislado a propósito: el almacén está detrás de la interfaz
`RateLimitStore`, y `hit()` registra y consulta en **una sola operación
atómica** (partirlo reabriría la carrera entre consultar y registrar).

Migrar a Redis es implementar esa interfaz y llamar a
`reset_rate_limit_store(RedisRateLimitStore(...))` al arrancar. **Nada más**: ni
la política, ni el middleware, ni la dependencia, ni los endpoints cambian. Con
un `ZSET` por clave y un script Lua para que sea atómico:

```
ZREMRANGEBYSCORE key -inf (now - window)   # tira lo viejo
ZADD             key now <miembro único>   # registra
ZCARD            key                       # cuenta
EXPIRE           key window                # que se limpie solo
```

Se pospone porque una segunda instancia todavía no existe y Redis añadiría,
desde ya, un salto de red en **cada** petición y una decisión nueva que hoy no
hace falta tomar (si Redis cae, ¿se deja pasar el tráfico o se corta?).

### Extensión: límites por plan

`rule_for_user(multiplier=…)` escala la cuota del usuario, y
`_multiplicador_del_plan` en `api/deps.py` traduce el plan a ese multiplicador.
Hoy free y pro pesan igual (`ROVER_RATE_LIMIT_PRO_MULTIPLIER=1.0`): la HU deja
el enganche, no la política comercial. Un plan nuevo (Épica 5) es una entrada
más en ese mapa. Las cuotas de **consumo** del agente (tokens de LLM, minutos de
voz — Épica 2) son ámbitos **nuevos** con su propia regla, no un cambio aquí:
esto acota peticiones, aquello acotará consumo.

### Verificarlo en local

```bash
uv run uvicorn app.main:app                      # terminal 1
# terminal 2: 12 peticiones seguidas al login (límite de auth: 10/min)
for i in $(seq 12); do
  curl -s -o /dev/null -w "%{http_code} " \
    -X POST http://127.0.0.1:8000/v1/auth/login \
    -H 'Content-Type: application/json' -d '{}'
done
# → 422 422 422 422 422 422 422 422 422 422 429 429

# El cuerpo y las cabeceras del rechazo:
curl -si -X POST http://127.0.0.1:8000/v1/auth/login \
  -H 'Content-Type: application/json' -d '{}' | head -12
# HTTP/1.1 429 Too Many Requests
# retry-after: 60
# x-ratelimit-limit: 10
# {"error":{"code":"rate_limited","message":"Demasiadas peticiones; …"}}
```

En local no hay proxy delante, así que todas las peticiones caen en el mismo
cubo (el peer TCP). Para simular varias IPs, manda la cabecera a mano:
`-H 'X-Forwarded-For: 203.0.113.7'`.

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
