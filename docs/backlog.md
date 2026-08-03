# Rover — Backlog activo

> **Documento de trabajo vivo.** Crece **épica por épica**: aquí solo se detalla la épica en curso. Cuando cerremos todas sus HU (cumpliendo la Definition of Done), añadimos la siguiente. El panorama completo de las 7 épicas vive en `backlog-full.md` como referencia.
>
> **Épica en curso: 1 — Backend core.** (Épica 0 — Fundación: **completada**; queda abajo como registro histórico.)

---

## Cómo usar este documento

- **Jerarquía:** Épica → Historia de Usuario (HU = un Issue) → Tareas técnicas (checklist dentro del Issue).
- **Tablero (GitHub Projects):** `Backlog → En progreso → En revisión → Done`.
- **Flujo de trabajo:** un solo desarrollador; todo el trabajo se commitea directo en `develop` (no hay rama `main` ni PRs por ahora). La calidad la garantizan los hooks locales (lefthook) y el CI que corre en cada push a `develop`.
- **Labels sugeridas:** `epica:0-fundacion` · `epica:1-backend` · `tipo:hu | bug | tech-debt` · `prioridad:alta | media | baja` · `bloqueante`.
- **Sprints:** solo como *timeboxes* de foco (elige unas pocas HU, no toques nada fuera de ese alcance). Sin story points ni dailies.

---

## Definition of Done (global — aplica a TODA historia, sin excepción)

Una HU está **Done** solo cuando:

- [ ] El código pasa el **linter** y el **type-check** sin errores.
- [ ] Todas las **pruebas** (unitarias e integración relevantes) están en verde.
- [ ] Se cumplen **todos los criterios de aceptación** de la HU.
- [ ] Si tocó el esquema de base de datos: la **migración Alembic** está escrita y aplicada.
- [ ] Si cambió un endpoint o un tipo: el **paquete compartido** (cliente API tipado) está actualizado.
- [ ] El trabajo está commiteado en **`develop`**; la calidad la garantizan los **hooks locales (lefthook)** y el **CI** que corre en cada push a `develop`.
- [ ] El **CI está verde** en `develop` tras el push.
- [ ] No se introdujeron **secretos** en el repo ni valores hardcodeados que deban ir en config.

---

## Roadmap (panorama — detalle se añade épica por épica)

| Épica | Nombre | Objetivo | Estado |
|-------|--------|----------|--------|
| 0 | Fundación | Monorepo, tooling, CI/CD desplegando desde el día uno | Completada ✅ |
| **1** | Backend core | API `/v1`, async Supabase, Alembic, auth vía Supabase Auth, rate limiting, errores | **En curso** |
| 2 | El agente | RAG + tool-calling, streaming, sesiones, caché semántico, voz opcional (pipeline) | Pendiente |
| 3 | Web | Next.js con auth, chat con streaming, pricing | Pendiente |
| 4 | Mobile | Expo reusando la capa compartida | Pendiente |
| 5 | Monetización | Stripe / Play Billing / Apple IAP, freemium | Diferida |
| 6 | Operaciones | n8n / cron para tareas internas (nunca en el camino de la petición) | Pendiente |

---

# ÉPICA 0 — Fundación ✅ COMPLETADA

**Objetivo:** que todo el proyecto nazca con calidad: monorepo estructurado, linting, type-checking y un pipeline de CI/CD que despliega a un PaaS *desde el primer día*. Esta épica va primero porque desbloquea la disciplina de todo lo demás.

> **Estado: las 8 HU (0.1–0.8) están hechas.** Esta sección queda como registro histórico de lo construido.

### ✅ HU-0.1 — Inicializar el monorepo
*Como* desarrollador, *quiero* un monorepo con espacios para backend, web, mobile y paquetes compartidos, *para* compartir lógica entre plataformas sin duplicar código.

**Criterios de aceptación:**
- Existe la estructura `apps/` (backend, web, mobile) y `packages/` (shared).
- El gestor de workspaces está configurado y `install` desde la raíz instala todo.
- Un `README` raíz documenta la estructura y los comandos básicos.
- Cada workspace puede ejecutarse de forma independiente.

**Tareas técnicas:** elegir pnpm workspaces (o Turborepo) · estructura de carpetas · `package.json` raíz con scripts · README inicial · `.gitignore` completo.

---

### ✅ HU-0.2 — Linting y formateo
*Como* desarrollador, *quiero* linting y formateo automáticos, *para* mantener consistencia y atrapar errores antes de ejecutar.

**Criterios de aceptación:**
- Ruff (backend Python) y ESLint + Prettier (TS) configurados.
- `lint` corre desde la raíz sobre todos los workspaces.
- Existe configuración de pre-commit que bloquea commits con errores de lint.
- Las reglas están documentadas y son las mismas en local y en CI.

**Tareas técnicas:** configurar Ruff · configurar ESLint + Prettier · pre-commit hooks (husky/lefthook o pre-commit de Python) · script `lint` en la raíz.

---

### ✅ HU-0.3 — Type-checking estricto
*Como* desarrollador, *quiero* chequeo de tipos estricto, *para* que los errores de tipos no lleguen a runtime.

**Criterios de aceptación:**
- `mypy` (o pyright) en backend en modo estricto, `tsc --noEmit` en TS.
- `type-check` corre desde la raíz.
- Cero errores de tipos en el estado base del repo.

**Tareas técnicas:** configurar mypy/pyright · `tsconfig` estricto · script `type-check`.

---

### ✅ HU-0.4 — Esqueleto del backend desplegable (healthcheck)
*Como* desarrollador, *quiero* un FastAPI mínimo con un endpoint de salud, *para* tener algo real que desplegar desde el día uno.

**Criterios de aceptación:**
- `GET /v1/health` responde `200` con `{"status": "ok"}` y versión (versionado bajo `/v1` desde el día uno).
- La app arranca con un comando documentado y corre en contenedor.
- Existe `Dockerfile` y `docker-compose.yml` para desarrollo local.
- Hay al menos un test que verifica el healthcheck.

**Tareas técnicas:** scaffold FastAPI · endpoint `/v1/health` · Dockerfile · docker-compose · primer test.

---

### ✅ HU-0.5 — Pipeline de CI (calidad en cada push)
*Como* desarrollador, *quiero* que cada push a `develop` corra lint, type-check y tests, *para* que nada roto se quede en la rama sin avisar.

**Criterios de aceptación (como se construyó):**
- GitHub Actions con un workflow (`.github/workflows/ci.yml`) que corre en cada push a `develop` y permite disparo manual (`workflow_dispatch`).
- Dos jobs en **paralelo**: **TS** (ESLint, Prettier check, tsc estricto y, desde la HU-0.7, tests con `node --test`) y **Python** (ruff check, ruff format check, mypy estricto, pytest).
- Cachés atadas a cada lockfile (`pnpm-lock.yaml` y `apps/backend/uv.lock`); instalaciones frozen/locked; `concurrency` con cancel-in-progress (si llegan varios pushes seguidos, gana el último); badge de estado en el README.
- El CI **no** bloquea merges ni exige PRs (no aplica al flujo de un solo desarrollador en `develop`): su función es avisar con el check verde/rojo y validar todo en un entorno limpio.

**Tareas técnicas (como se hizo):** workflow en `.github/workflows/ci.yml` con jobs frontend + backend · cache de pnpm (`setup-node`) y de uv (`setup-uv` con `cache-dependency-glob` al `uv.lock`) · `pnpm install --frozen-lockfile` / `uv sync --frozen` · `concurrency` por ref con cancel-in-progress · badge de estado en el README.

---

### ✅ HU-0.6 — Pipeline de CD (deploy automático a Render)
*Como* desarrollador, *quiero* que un push a `develop` despliegue solo al PaaS, *para* no integrar la infraestructura al final del proyecto.

**Criterios de aceptación (como se construyó):**
- El deploy está definido como **Infraestructura como Código** en `render.yaml` (Blueprint de Render): servicio web Docker en plan free, **sin** workflow de CD propio ni secretos del deploy en GitHub.
- Push a `develop` dispara un deploy automático del backend en Render (`autoDeploy`).
- El deploy usa la imagen contenedorizada de la HU-0.4; el contenedor respeta el `$PORT` que inyecta Render (con fallback a 8000 en local).
- Render solo marca el deploy como sano si `GET /v1/health` responde `200` (healthcheck del servicio); un deploy fallido queda visible en el panel.

**Tareas técnicas (como se hizo):** elegir PaaS (Render) · `render.yaml` en la raíz (`dockerfilePath`/`dockerContext` → `apps/backend`, `healthCheckPath: /v1/health`, `ROVER_ENV=production`) · CMD del Dockerfile con `${PORT:-8000}` · conexión del Blueprint en el panel de Render (paso manual, una vez) · documentar en `docs/deploy.md` (incluida la nota del arranque en frío del plan free).

---

### ✅ HU-0.7 — Paquete compartido de tipos y cliente API
*Como* desarrollador, *quiero* un paquete compartido con los tipos de datos y el cliente HTTP tipado, *para* que web y mobile consuman la misma API sin duplicar lógica.

**Criterios de aceptación:**
- Existe `packages/shared` con tipos y un cliente API tipado importable desde web y mobile.
- Un cambio en un tipo se refleja en ambos consumidores sin copiar y pegar.
- El paquete está cubierto por type-check en el CI.

**Tareas técnicas:** scaffold `packages/shared` · definir tipos base · cliente HTTP tipado · wiring en los workspaces consumidores.

---

### ✅ HU-0.8 — Configuración por ambiente y manejo de secretos
*Como* desarrollador, *quiero* configuración separada por ambiente y secretos fuera del repo, *para* no filtrar credenciales y poder mover entre local/staging/prod.

**Criterios de aceptación:**
- Settings con `pydantic-settings`, leídas de variables de entorno.
- Existe `.env.example` documentado; el `.env` real está en `.gitignore`.
- Ningún secreto está hardcodeado ni commiteado.
- La app falla con un error claro si falta una variable obligatoria.

**Tareas técnicas:** `core/config.py` con pydantic-settings · `.env.example` · validación de variables obligatorias al arranque · documentar en README.

---

# ÉPICA 1 — Backend core

**Objetivo:** el backend permanente y bien construido. API versionada, conexión async a Supabase, migraciones, autenticación delegada en Supabase Auth, rate limiting por plan, manejo de errores centralizado y observabilidad básica. Esto no se bota cuando crezcas; solo le pones más máquinas detrás.

> **Decisión de arquitectura: Supabase Auth como proveedor de identidad.** El backend **no emite JWT propios**: delega registro y login en Supabase Auth y **valida** los tokens que este emite. Motivos: el login social con Google/Apple que exigen las stores viene resuelto de serie, la seguridad de credenciales (hashing, rotación de refresh tokens, recuperación de contraseña) queda en un servicio probado en vez de código propio, y es coherente con el Postgres de Supabase que ya usamos (HU-1.1). Trade-off asumido: **acoplamiento al proveedor** — migrar de Supabase Auth tendría costo; se mitiga concentrando la integración en el servicio de auth del backend. Consecuencia en el modelo de datos: la tabla local de usuarios pasa a ser un **perfil** que referencia el id de Supabase (`auth.users`), no una fuente de identidad (ver HU-1.10a).

### ✅ HU-1.1 — Conexión async a base de datos
*Como* sistema, *quiero* conectarme a Supabase Postgres de forma asíncrona, *para* no bloquear el event loop bajo carga.

**Criterios de aceptación:**
- SQLAlchemy 2.0 async + asyncpg conectando a Supabase Postgres.
- Pool de conexiones configurado y cerrado limpiamente al apagar la app.
- Existe una dependencia de FastAPI que entrega sesiones de DB por request.
- Un test de integración verifica que se puede leer/escribir contra una DB de prueba.

**Tareas técnicas:** `core/database.py` (engine async + sessionmaker) · dependency `get_db` · configuración del pool · test de conexión.

---

### ✅ HU-1.2 — Alembic y primera migración
*Como* desarrollador, *quiero* migraciones versionadas, *para* controlar el esquema en producción sin sorpresas.

**Criterios de aceptación (como se construyó):**
- Alembic configurado sobre el **mismo engine async** del proyecto: `migrations/env.py` reutiliza la construcción del engine de `app.core.database` (`build_async_url` + `engine_kwargs`, detección del Transaction Pooler de Supabase incluida) y resuelve la URL desde `ROVER_DATABASE_URL`; la URL **nunca** se escribe en `alembic.ini` (ese archivo se versiona y la URL es un secreto — un test lo garantiza).
- `alembic upgrade head` y `downgrade` verificados desde local contra Supabase.
- La primera migración es una **baseline que ancla el versionado sin crear tablas** (solo aparece la tabla de control `alembic_version`): los modelos de dominio —incluida la tabla de usuarios— corresponden a la HU-1.10a, y crearlos aquí habría adelantado ese diseño.
- La estrategia de migración en producción (manual desde local; por qué no está automatizada en el plan free de Render) está documentada en `docs/deploy.md`, y los comandos del día a día en el README del backend.

> **Nota:** la tabla de usuarios y su migración llegan con la HU-1.10a (modelos de dominio).

**Tareas técnicas (como se hizo):** init de Alembic · `env.py` async reutilizando la config real del backend · migración baseline · hooks de ruff (fix + format) para las migraciones autogeneradas · tests de configuración sin base real · documentar en README y `docs/deploy.md`.

---

### ✅ HU-1.3 — Registro de usuario (vía Supabase Auth)
*Como* viajero nuevo, *quiero* crear una cuenta con email y contraseña, *para* guardar mis conversaciones y preferencias.

**Criterios de aceptación (como se construyó):**
- `POST /v1/auth/register` delega el alta en Supabase Auth usando la **anon key** (no la service role: registrar no requiere privilegios elevados) y responde `201` con el usuario (`id`, `email`) y la sesión de Supabase (access + refresh token). El backend **no firma JWT propios**.
- Toda la interacción con Supabase Auth está **encapsulada en `app/services/auth.py`**: se integró con `httpx` directo contra la API de GoTrue (menos peso que el SDK oficial y control propio del parseo de errores). Ningún otro módulo del backend habla con Supabase.
- Los errores del proveedor se traducen a excepciones de dominio (`EmailAlreadyExists`, `WeakPassword`, `InvalidEmail`, `RateLimited`, `AuthProviderError`) por el campo **`error_code` estable** de Supabase + el status HTTP, **nunca** buscando palabras en el texto del mensaje. Mapeo a HTTP: `409` / `422` / `429` / `503`. Un `error_code` desconocido cae en `AuthProviderError`, conservando el código original solo para logs.
- El **perfil local** se crea de forma **idempotente** tras el alta y su fallo **no rompe el registro** (se materializa después, HU-1.6). La sesión de base se gestiona a mano en vez de con `Depends(get_db)`, para que un fallo de la dependencia no aborte el request antes de poder contenerlo; un `IntegrityError` por id repetido se trata como idempotencia esperada, no como error.
- Los fallos quedan **logueados** en servidor con status + `error_code` + mensaje del proveedor (warning para esperables, error para inesperados), **sin contraseñas ni llaves**; la respuesta al cliente sigue siendo genérica.
- La contraseña **no aparece** en las respuestas de error de validación (handler propio en `app/core/errors.py` que elimina el campo `input` de errores sobre campos sensibles; se verificó que `SecretStr` por sí solo no lo evitaba). *(El saneo sigue igual desde la HU-1.8; lo que cambió es dónde viaja: bajo `details.errors` del formato único.)*
- Cliente compartido (`@rover/shared`) actualizado con los tipos y el método del registro. Tests que **no** dependen de Supabase real (cliente mockeado): caso feliz, `409`, `422`, `429`, `503`, fallo del perfil sin romper el registro e idempotencia.
- **Verificado end-to-end** contra Supabase real: `201` con sesión, usuario en `auth.users` y fila en `user_profiles` con el mismo id y `plan='free'`.

**Tareas técnicas (como se hizo):** schemas Pydantic request/response · `app/services/auth.py` (httpx contra GoTrue + traducción de errores por `error_code`) · perfil local idempotente con sesión gestionada a mano · handler de validación que oculta campos sensibles · endpoint · cliente compartido · tests con mock.

> **Nota:** el caso de **confirmación de email pendiente** (Supabase crea el usuario pero no devuelve sesión) quedó fuera de alcance y se aborda en la **HU-1.3b**.

---

### ✅ HU-1.3b — Registro con confirmación de email pendiente
*Como* usuario que se registra, *quiero* saber que debo confirmar mi correo, *para* entender por qué aún no tengo sesión iniciada.

Contexto: con **"Confirm email" activado** en Supabase (lo deseable en producción), el alta crea el usuario pero **no** devuelve sesión. Antes el endpoint traducía esa ausencia a un `503` de "fallo del proveedor", que es incorrecto: es un estado legítimo del negocio, no un error de infraestructura.

**Criterios de aceptación (como se construyó):**
- `POST /v1/auth/register` responde `201` en **ambos modos** de Supabase, con un contrato de **unión discriminada** por un campo **`status` tipado** (no un booleano): `active` (con sesión) y `pending_email_confirmation` (`session` es `null`). El literal habilita **narrowing en TypeScript sin castings** y es extensible a futuros estados.
- El `RegisterResponse` valida **en el borde** con un `model_validator` que rechaza combinaciones incoherentes (`active` sin sesión, o pendiente con sesión): el cliente **nunca** recibe algo ambiguo.
- El servicio distingue las **dos formas** de respuesta de GoTrue, verificadas contra el proveedor real: con sesión, el usuario viene **anidado** bajo la clave `"user"`; sin sesión (confirmación activada), el usuario viene **directamente en la raíz** (`id`, `email`, `confirmation_sent_at`, …). La **presencia de `"user"` es el discriminante primario**; la raíz es el respaldo. Si `"user"` existe pero es inválido **no** se cae al respaldo (es incoherente, no otro caso).
- Reglas de sesión: ambos tokens → `active`; ningún token con usuario válido → `pending`; un solo token → `AuthProviderError` (`503`). Sin usuario identificable → `AuthProviderError`.
- El **perfil local** se crea de forma **idempotente** en ambos caminos, con el mismo tratamiento de fallos (no rompe el registro, se loguea).
- `over_email_send_rate_limit` sigue devolviendo `429`.
- `@rover/shared` expone `RegisterResponse` como **unión discriminada**, con **type guard de runtime** que valida ambas formas y rechaza incoherencias.
- Flujo **documentado** para web/móvil en el README del backend (qué mostrar en cada `status`).
- **Verificado end-to-end** contra Supabase real en ambos modos.

**Tareas técnicas (como se hizo):** `_parse_signup` soporta las dos formas de GoTrue · `SignUpResult` (usuario siempre, sesión opcional) · `RegisterResponse` como unión discriminada con validador de coherencia · cliente compartido con unión + type guard · `configure_logging` para ver los diagnósticos (ver nota 2) · tests de ambos caminos con httpx mockeado · flujo documentado en el README.

> **Aprendizaje 1 — los mocks valen lo que vale el conocimiento del sistema que imitan.** La forma de la respuesta de GoTrue **cambia según el modo de confirmación**. Los tests iniciales pasaban porque estaban escritos contra una respuesta *imaginada* (usuario siempre bajo `"user"`); solo la verificación manual contra el proveedor real reveló la forma con el **usuario en la raíz**. El mock daba una falsa sensación de cobertura.
>
> **Aprendizaje 2 — el logging de la app no era visible.** uvicorn configura solo sus propios loggers y deja el root sin handler, así que los loggers `app.*` dependían del `lastResort` de `logging` (frágil: solo `WARNING`+, sin formato, y desaparece si cualquier librería añade un handler en la cadena). Se resolvió con `app/core/logging.py` (`configure_logging`, llamado desde `create_app`), que engancha un `StreamHandler` a **stdout** en el logger raíz `app`. Esto **adelanta parte de la HU-1.12** (ver esa HU).

---

### ✅ HU-1.4 — Login (delegado en Supabase Auth)
*Como* usuario registrado, *quiero* iniciar sesión, *para* acceder a mi cuenta de forma segura.

**Criterios de aceptación (como se construyó):**
- `POST /v1/auth/login` delega en Supabase Auth (endpoint de **token** de GoTrue con `grant_type=password`) usando la **anon key**. Responde `200` con `user` (`id`, `email`) y la sesión (access + refresh token). El backend **no firma JWT propios**.
- El transporte y el parseo se extrajeron a **helpers compartidos** con el registro (`_gotrue_post`, `_parse_user_and_session`), evitando duplicación. `_parse_signin` **exige sesión**: en login, un `2xx` sin tokens es incoherente (`AuthProviderError`), a diferencia del registro donde es un estado válido (`pending_email_confirmation`).
- Nuevas excepciones de dominio `InvalidCredentials` y `EmailNotConfirmed`, traducidas por los `error_code` estables `invalid_credentials` y `email_not_confirmed`.
- Mapeo HTTP: `401` credenciales inválidas · `403` email sin confirmar · `429` rate limit · `503` fallo del proveedor.
- Credenciales inválidas devuelven un cuerpo **idéntico** tanto si el email no existe como si la contraseña es incorrecta, para no revelar qué cuentas están registradas (verificado con un test que compara ambos cuerpos, y contra Supabase real).
- El caso **"email sin confirmar" se resolvió como `403`** (no `401` con discriminante): las credenciales son correctas, lo que falta es activar la cuenta; meterlo en `401` conflaciona dos situaciones que interesa separar. Coherente con el estilo de la HU-1.3b, el cuerpo incluye un discriminante explícito (`reason: "email_not_confirmed"`) para que el cliente **no infiera**.
- El login **no** crea ni materializa el perfil local: esa responsabilidad es del middleware de la **HU-1.6**, único punto por el que pasa toda petición autenticada. Criterio documentado en el endpoint.
- Fallos **logueados** con status + `error_code` + mensaje del proveedor, **sin contraseñas ni llaves**.
- `@rover/shared` actualizado con tipos, método (`ApiClient.login()`) y **type guard** de runtime.
- **Verificado end-to-end** contra Supabase real: login correcto (`200`), contraseña incorrecta (`401`), email inexistente (`401` con cuerpo idéntico) y usuario sin confirmar (`403` con `reason`).

**Tareas técnicas (como se hizo):** `_gotrue_post` + `_parse_user_and_session` compartidos con el alta · `sign_in` + `_parse_signin` (sesión obligatoria) · excepciones `InvalidCredentials` / `EmailNotConfirmed` mapeadas por `error_code` · endpoint con mapeo `401/403/429/503` · cliente compartido con tipos + método + type guard · tests con httpx/servicio mockeados · flujo documentado en el README.

> **Deuda técnica (infra de tests) — SIGUE ABIERTA y se acumula (revisada en la HU-1.7):** al correr el **conjunto completo** aparecen warnings intermitentes de aiosqlite (`RuntimeError: Event loop is closed`) durante el *teardown*. **No son fallos**: los **151 tests pasan de forma determinista** y el CI no los trata como error. Son ruido, pero ruido que ensucia la señal de la suite.
>
> **Causa, ya identificada:** los fixtures crean el engine SQLite con `asyncio.run(...)`, lo usan desde el loop del `TestClient` y lo cierran con otro `asyncio.run(engine.dispose())` en el teardown — **tres event loops distintos para el mismo engine**. El hilo trabajador de aiosqlite guarda el loop con el que nació y falla al entregar su resultado cuando ese loop ya no existe; el warning aflora en el test que estuviera corriendo en ese momento, no en el que lo causó. Afecta a `test_auth_middleware.py` y `test_users_me.py` (cierre entre loops) y a los tests de **registro/login**, que además ni siquiera cierran sus engines.
>
> **Intentos descartados en la HU-1.7:** `poolclass=NullPool` en los engines de test y cerrar el generador de `get_db` con `aclosing` (esto último sí arregló una fuga real, ver la HU-1.7). Ninguno lo elimina: el arreglo de verdad es **reestructurar los fixtures** para que el engine nazca y muera en el mismo loop.
>
> **Recomendación: abrir una HU dedicada de limpieza de fixtures de test, y pronto.** La deuda ya no está "acotada a registro/login" como decía esta nota antes de la HU-1.7: cada HU nueva que necesita base de datos copia el patrón y lo extiende. El trabajo es acotado (un fixture compartido en `tests/conftest.py`, que desde la HU-1.7 ya existe) pero crece con cada módulo que se añada.

---

### HU-1.5 — Renovación de sesión
*Como* usuario, *quiero* renovar mi sesión sin volver a loguearme, *para* una experiencia fluida sobre todo en móvil.

**Criterios de aceptación:**
- El refresh y la **rotación** de tokens son responsabilidad de Supabase (y de su SDK en los clientes web/móvil); el backend **no** implementa lógica propia de refresh ni de rotación.
- El flujo queda documentado: cómo renuevan sesión los clientes contra Supabase.
- Solo si aporta a los clientes, se expone un `POST /v1/auth/refresh` que **delega** en Supabase; en ese caso, refresh token inválido o expirado responde `401` y hay tests con el cliente mockeado.

**Tareas técnicas:** documentar el flujo de refresh de Supabase · decidir si se expone un endpoint de refresh delegado (y si sí: endpoint + tests con mock).

---

### ✅ HU-1.6 — Middleware de autenticación (validación del JWT de Supabase)
*Como* sistema, *quiero* proteger rutas que requieren sesión, *para* que solo usuarios autenticados accedan a recursos privados.

**Criterios de aceptación (como se construyó):**
- Validación **local** del JWT de Supabase (no remota): se evita una llamada de red al proveedor en el camino crítico de cada petición, y la dependencia dura que eso implicaría.
- Librería **PyJWT** (extra `crypto`): soporta ES256 y JWKS, y lanza una excepción distinta por cada motivo de fallo (lo que permite loguear la causa real). El fetch **async** del JWKS y su **caché** se controlan en el proyecto (httpx), no con el cliente síncrono de la librería.
- **Caché del JWKS** en memoria con **TTL de 10 min**; ante un `kid` desconocido (rotación de claves) se fuerza un refresco, con **cooldown** mínimo entre refrescos forzados para que una lluvia de tokens con `kid` inválido no golpee el endpoint del JWKS en cada petición.
- Se verifican **firma** (ES256, clave seleccionada por `kid`), **expiración**, **issuer** (`{SUPABASE_URL}/auth/v1`) y **audiencia** (`"authenticated"`); `require` de `exp` y `sub`.
- Los fallos del token se traducen a `TokenError` con motivo **preciso** (`expired`, `invalid_signature`, `invalid_issuer`, `invalid_audience`, `unknown_kid`, `malformed`, `invalid_scheme`…). Un fallo al obtener el JWKS es `JWKSUnavailable` → **`503`, no `401`**: es un fallo de infraestructura propio, no un problema con las credenciales del cliente.
- `get_current_user` (`app/api/deps.py`) extrae el Bearer, valida el token y resuelve el **perfil local**; si no existe, lo **crea de forma perezosa e idempotente**. Este es el **único punto de materialización** del perfil (registro y login lo delegan aquí a propósito). La carrera se maneja releyendo la fila tras un `IntegrityError`.
- Deja `id`, `email` y `plan` en el contexto del request (`CurrentUser`).
- Todos los fallos de autenticación → **`401` uniforme** (mismo cuerpo, `WWW-Authenticate: Bearer`); el motivo real solo va al log. Un `503` por fallo de base de datos **no** loguea el error crudo (podría contener la URL con credenciales).
- Ruta protegida de verificación **`GET /v1/auth/me`** (los endpoints completos de perfil siguen siendo la HU-1.10b). *(Retirada en la HU-1.9: era andamio y se consolidó en `GET /v1/users/me`; los tests del middleware se ejercen ahora contra esa ruta.)*
- `@rover/shared` actualizado con tipo (`MeResponse`), método (`getMe`) y type guard; envío **tipado** del header `Authorization`. *(También retirados en la HU-1.9; los sustituye `getProfile`/`Profile`.)*
- Tests que firman tokens ES256 propios e inyectan el JWKS (sin credenciales reales): cubren los motivos de fallo, el **cuerpo idéntico** del `401`, que el motivo **sí** aparece en el log y el token **no**, la creación perezosa y la carrera.
- **Verificado end-to-end** contra Supabase real: `200` con identidad resuelta; `401` uniforme sin header, con esquema incorrecto y con firma alterada, con el motivo real visible solo en los logs.

**Tareas técnicas (como se hizo):** `app/core/security.py` (PyJWT + JWKS async cacheado, verificación de firma/exp/iss/aud, `TokenError`/`JWKSUnavailable`) · `app/api/deps.py` (`get_current_user` + creación perezosa idempotente del perfil + `CurrentUser`) · endpoint `GET /v1/auth/me` · cliente compartido (tipo + `getMe` + type guard) · tests con tokens ES256 de prueba y JWKS inyectado.

---

### ✅ HU-1.7 — Rate limiting
*Como* operador del producto, *quiero* limitar las peticiones a la API, *para* protegerla de abuso y dejar los cimientos de las cuotas por plan.

**Criterios de aceptación (como se construyó):**
- **Tres controles con contadores independientes**, porque protegen cosas distintas: **global por IP** (120/min — protección base de toda la API, incluidas las rutas que no existen), **auth por IP** (10/min en `POST /v1/auth/login` y `/register`) y **usuario por id del token** (60/min en las rutas protegidas). Agotar uno no gasta los otros.
- **El de auth es el estricto porque es donde se adivinan contraseñas:** con 10/min, un diccionario de 10.000 contraseñas pasa de minutos a casi 17 horas **por IP**, y eso además del límite propio de Supabase. El de usuario es más estricto que el global a propósito — el global protege la máquina, el de usuario acota lo que consume una cuenta.
- **Clave por IP antes de autenticarse y por usuario después.** Antes del token la IP es lo único disponible (y es justo el caso de login/registro); después la cuenta es mejor clave, porque detrás de un NAT o de una operadora móvil mucha gente legítima comparte dirección y limitar solo por IP dejaría que uno se comiera el cupo de todos. Una ruta protegida pasa por los dos controles: manda el más estricto.
- **IP no falsificable detrás del proxy.** `X-Forwarded-For` es una lista donde cada proxy **añade al final**; la primera entrada la escribe el cliente. Se lee la entrada `ROVER_RATE_LIMIT_TRUSTED_PROXIES`-ésima **empezando por el final** (1 = el edge de Render), y con `0` la cabecera se ignora del todo. Las entradas que no son una IP válida se descartan: si no, mandar basura distinta en cada petición esquivaría el conteo **y** haría crecer el almacén sin límite.
- **Algoritmo: ventana deslizante** por marcas de tiempo, no ventana fija — la fija permite el doble del límite a caballo del corte (diez a las 11:59:59 y diez a las 12:00:00), que es justo el agujero que importa en el login. Con límites pequeños (10–120) la exactitud sale casi gratis y el `Retry-After` es **exacto**, no una estimación.
- **`429` en el formato único de la HU-1.8**, con `code: "rate_limited"` y las cabeceras `Retry-After` (segundos, nunca 0), `X-RateLimit-Limit`, `X-RateLimit-Remaining` y `X-RateLimit-Reset`. **Mismo `code` que el 429 que nace de un rechazo de Supabase**, a propósito: la acción del cliente es idéntica y el catálogo de códigos es de dominio, no de origen (distinguirlos revelaría que hay un proveedor detrás). Los rechazos se loguean a `warning` con IP/ruta o id de usuario, nunca con el token.
- **Almacén tras una INTERFAZ (`RateLimitStore`: `hit` / `peek` / `reset`), con implementación EN MEMORIA.** `hit()` registra y consulta en **una sola operación atómica** —partirlo en "consultar" + "registrar" reabriría la carrera entre ambos: dos peticiones simultáneas leerían "queda sitio" y las dos registrarían—; `peek()` consulta **sin** consumir cupo. Por dentro: un `deque` de marcas de tiempo por clave bajo un `asyncio.Lock`, **reloj monotónico inyectable** (inmune a que cambien la hora del sistema, y permite probar el paso de la ventana sin dormir) y **barrido amortizado** de las claves inactivas, para que un escaneo desde miles de IPs no deje una entrada por IP para siempre.
- **Ubicación de cada control, por diseño.** El límite por IP va en un **middleware ASGI** porque corre **antes de resolver la ruta**: así cuenta también las peticiones a rutas que no existen, que es justo lo que dispara quien escanea (como dependencia del router se irían en 404 sin gastar cupo). El de usuario va en una **dependencia** porque la identidad no existe hasta que `get_current_user` valida el token; repetir esa validación en un middleware pagaría **dos veces** el JWKS y la consulta del perfil. Como el middleware queda **fuera** de la cadena de handlers de excepciones (lanzar `ApiError` ahí acabaría en un 500), se expuso `error_response()` en `app/core/errors.py` para que construya el 429 con el mismo formato: la forma del error se sigue decidiendo en un solo sitio.
- **`GET /v1/health` y `/v1/health/db` EXENTOS.** Render los sondea constantemente para decidir si el deploy está sano; gastarles cupo arriesga marcar como caída una instancia que funciona, y son respuestas sin coste que no interesa a nadie abusar.
- **`@rover/shared`:** `isRateLimitedError` (type guard del 429), `parseRetryAfter` (acepta las dos formas de la RFC 9110: segundos o fecha HTTP, nunca negativo) y `ApiError.retryAfterSeconds`.
- **Enganche de los planes listo, sin la política comercial:** `rule_for_user(multiplier=…)` escala la cuota y `_multiplicador_del_plan` traduce el plan; hoy free y pro pesan igual (`ROVER_RATE_LIMIT_PRO_MULTIPLIER=1.0`). Las cuotas de **consumo** del agente (tokens, voz — Épica 2) serán ámbitos **nuevos** con su propia regla: esto acota peticiones, aquello acotará consumo.
- **Tests (33 nuevos, 151 en total):** almacén (límite exacto, reseteo por ventana, deslizante vs fija, claves independientes, `peek` sin consumir, ráfagas concurrentes) · IP tras el proxy (falsificación ignorada, cabecera repetida, IPv6, puerto, basura, caída al peer) · límites aplicados por HTTP (429 con formato y cabeceras, auth más estricto que global, rutas inexistentes cuentan, health exento, interruptor) · cuota de usuario y multiplicador de plan · el 429 es **idéntico** venga del middleware o de la dependencia.
- **Verificado contra un servidor real**, no solo en tests: 12 peticiones seguidas a `POST /v1/auth/login` → **10×`422`** (el cuerpo va vacío; el middleware corta antes de validar) **+ 2×`429`** con `retry-after: 60`, `x-ratelimit-limit: 10` y `x-ratelimit-remaining: 0`. Comprobado también que `/v1/health` aguanta 15 sondeos seguidos sin un solo `429`.

**Divergencia consciente del criterio original** — el criterio decía *"el contador es consistente aunque haya varios workers (estado compartido, no en memoria local)"* y **no** se implementó así:

> El conteo vive en la **memoria del proceso**: con varias instancias el límite efectivo se multiplica por el número de instancias.

Se pospone porque el despliegue es de **una sola instancia** (Render, plan free) y Redis añadiría, desde ya, un salto de red en **cada** petición y una decisión nueva que hoy no hace falta tomar (si Redis cae, ¿se deja pasar el tráfico o se corta?). **El punto de cambio está aislado**: migrar es implementar `RateLimitStore` con un `ZSET` + script Lua y llamar a `reset_rate_limit_store(RedisRateLimitStore(...))` al arrancar — ni la política, ni el middleware, ni la dependencia, ni los endpoints cambian. Queda como **deuda técnica con disparador claro: la segunda instancia**.

**Tareas técnicas:** interfaz `RateLimitStore` + implementación en memoria (`app/core/rate_limit.py`) · middleware ASGI por IP (`app/api/middleware.py`) · dependencia de cuota por usuario (`app/api/deps.py`) · límites y multiplicador en `Settings` · `conftest.py` que aísla el contador entre tests · tipos y type guard en `@rover/shared` · documentación en el README del backend.

> **Arreglo incidental (fuga de sesión):** `_resolve_or_create_profile` salía con `return` desde **dentro** del `async for` sobre `get_db()`, lo que deja el generador suspendido en su `yield` y la sesión (con su conexión) **abiertas hasta que pasara el recolector**. Ahora usa `aclosing`, que es exactamente lo que hace `Depends` cuando la dependencia se inyecta de la forma normal. Obligó a tipar `get_db` como `AsyncGenerator` en vez de `AsyncIterator`: `aclosing` exige un `aclose()` que solo el primero promete.

---

### ✅ HU-1.8 — Manejo centralizado de errores
*Como* consumidor de la API, *quiero* errores consistentes y predecibles, *para* manejarlos bien en web y móvil.

**Criterios de aceptación (como se construyó):**
- **Formato único** para **toda** respuesta no-2xx, con envoltorio `error`: `code` (código estable legible por máquina, de un catálogo propio `ErrorCode`), `message` (texto presentable al usuario, y respaldo cuando el cliente no conoce el código), `details` (objeto extensible; en un `422` lleva `errors` campo a campo) y `error_id` (solo en los `500`). El **envoltorio** permite a web/móvil distinguir "esto es un error" de "esto es un dato" sin mirar el status ni adivinar por las claves: **un único type guard** para toda la API.
- **`code`, no solo el status.** El status agrupa demasiado: un `422` cubre contraseña débil, email inválido, campo desconocido y payload demasiado grande. El cliente ramifica por `code`, que es **estable** frente a reescribir o traducir el `message`. Los `error_code` **crudos de Supabase NO se exponen**: se traducen al catálogo propio, igual que ya se hacía con las excepciones — así el acoplamiento al proveedor sigue contenido en `services/auth.py` y no se filtra a los clientes.
- **Los contratos previos quedaron DENTRO del formato, no como excepciones a él:** el `403` de email sin confirmar es `code: "email_not_confirmed"` (deja de ser un `detail.reason` especial); el **`401` sigue siendo uniforme** como `code: "unauthenticated"` —mismo cuerpo y mismo `WWW-Authenticate` para todos los motivos, con la causa solo en el log—; y el `422` **saneado** (sin el valor de campos sensibles) va bajo `details.errors`.
- Los endpoints lanzan **`ApiError(status, code, message)`** —semántica, no respuestas—; **ya no queda ninguna `HTTPException` a mano**. La FORMA se decide en un solo sitio: handlers centralizados registrados en `create_app()` para `ApiError`, `RequestValidationError` (422 saneado), la `HTTPException` **del framework** (404 de ruta inexistente, 405 de método no permitido — con mensaje propio, porque los suyos vienen en inglés) y `Exception`.
- **Blindaje de los `500`:** el cliente recibe **siempre** el mismo mensaje genérico más un **`error_id` opaco**; **nunca** el tipo de la excepción, su mensaje ni la traza — que es justo donde aparecerían la URL de la base con su contraseña, una llave o un token. Ese **mismo** `error_id` se loguea a nivel `error` junto a la causa real y al **método y ruta** de la petición, y **no** la query string ni las cabeceras, para que el token de `Authorization` no acabe en los logs. **Verificado** con una excepción que contiene una URL con contraseña: no aparece en el cuerpo (ni el esquema, ni el host, ni la clave), sí en el log, junto al id que vio el cliente.
- **`GET /v1/health/db` se pasó al formato común:** su `503` tenía un cuerpo propio (`status: "error"` + `detail`), lo que habría dejado una excepción a la regla justo en el criterio que dice "un solo type guard para toda la API". Ahora el fallo es un error como cualquier otro y el `200` queda en `{"status": "ok"}`.
- **OpenAPI al día (HU-1.9):** todos los errores documentados referencian el esquema `ErrorResponse` —incluido el `422` que FastAPI añade solo, declarado a mano para que su `HTTPValidationError` desaparezca del esquema—, con un test que lo verifica operación por operación.
- **`@rover/shared`:** `ApiErrorResponse` + `isApiErrorResponse` (**un solo** type guard para cualquier error), y `ApiError` gana `code`, `details` y `errorId` parseados del cuerpo. El tipo de `code` admite strings desconocidos **a propósito**: un cliente ya publicado debe poder parsear un error con un código que aún no conocía.
- Tests del contrato (`tests/test_errors.py`): la forma común en cada familia (`401`, `403`, `404`, `405`, `409`, `422`, `429`, `503`), el `401` uniforme dentro del nuevo formato, la contraseña ausente del `422`, y el `500` sin traza ni credenciales con su `error_id` presente en el log.

**Tareas técnicas (como se hizo):** `app/core/errors.py` (catálogo `ErrorCode`, excepción `ApiError`, modelos `ErrorResponse`/`ErrorBody`, los cuatro handlers y `register_exception_handlers`) · migración de todos los endpoints y dependencias de `HTTPException` a `ApiError` · helper `error_doc` para documentar cada error en OpenAPI · `health/db` al formato común · `@rover/shared` (`types/error.ts` + `ApiError` enriquecido + parseo en el cliente) · tests nuevos y ajuste de los 9 que asertaban el cuerpo viejo · README (§ Formato de errores).

> **Deuda deliberada:** el catálogo `ErrorCode` y el tipo `KnownApiErrorCode` de `@rover/shared` se mantienen **a mano** en los dos lados. Es duplicación consciente y barata (una línea por código); si se generan los tipos desde el esquema OpenAPI —la idea anotada en el cliente compartido desde la HU-0.7— desaparece sola.

---

### ✅ HU-1.9 — Estructura de API versionada `/v1` y documentación OpenAPI
*Como* equipo, *quiero* versionar la API desde el inicio, *para* poder evolucionar sin romper clientes existentes (web/móvil).

> Dos criterios ya se cumplían al llegar aquí: todos los endpoints cuelgan de `/v1` desde la HU-0.4 y el cliente compartido apunta a `/v1` desde la HU-0.7. Esta HU consolidó la **organización de routers** (que la HU-1.10b había arrancado con el router `users`) y añadió la **documentación**.

**Criterios de aceptación (como se construyó):**
- **Un único agregador** (`app/api/v1/router.py`) aplica el prefijo `/v1` en **un solo sitio** e incluye los routers de dominio; `main.py` lo monta con **un solo `include_router`**. Los routers de dominio (`health`, `auth`, `users`) declaran **solo su dominio, nunca la versión**. Antes el prefijo `/v1` se repetía en cada `include_router` de `main.py`: publicar una `/v2` (o mover la versión a un header) obligaba a tocar cada línea sin olvidar ninguna. Ahora es **añadir otro agregador**, sin tocar los routers.
- **Tags de OpenAPI por dominio** (`health`, `auth`, `users`) **con descripción**, declarados junto al agregador —donde ya se decide la forma de `/v1`— y en el orden en que aparecen las secciones en `/docs`.
- **Metadatos de la app:** título `"Rover API"`, **versión desde `app.__version__`** (vía `settings`: una sola fuente de verdad) y descripción de portada.
- `summary` + `description` en **cada operación**, **ejemplos** en los cuerpos de entrada y salida (`json_schema_extra` de Pydantic v2) y **códigos de respuesta documentados** (`401`, `403`, `409`, `422`, `429`, `503`) que describen **cuándo** ocurren, nunca el motivo concreto de un rechazo de auth: el `401` sigue siendo uniforme y la documentación no insinúa lo contrario. Las respuestas comunes a toda ruta protegida se comparten en `deps.AUTH_RESPONSES` en vez de repetirse.
- **`/docs`, `/redoc` y `/openapi.json` desactivables**, decididos por `Settings.docs_enabled`: **activas** en `local`/`test`, **404** en `production`, y `ROVER_ENABLE_DOCS` (`true`/`false`) **fuerza** cualquiera de los dos en cualquier ambiente. Se apagan con **`openapi_url=None`**, que desmonta también el **esquema crudo** y no solo la UI (apagar la UI dejando `/openapi.json` no oculta nada). Criterio: el esquema es el **mapa completo** de la API —rutas, cuerpos, errores— y publicarlo regala trabajo de reconocimiento a quien busque superficie de ataque, mientras los clientes propios consumen `@rover/shared`, no la UI. El default es **por ambiente** para que no se pueda *olvidar* apagarlas: exponerlas en producción exige pedirlo explícitamente.
- **Esquema Bearer reflejado en OpenAPI** (`deps.bearer_scheme`, `HTTPBearer` con `auto_error=False`): las rutas protegidas salen marcadas con candado y `/docs` ofrece **Authorize**. Es **solo representación**: el token se sigue leyendo del header crudo con código propio, porque `auto_error=True` respondería con el cuerpo de la librería (rompiendo el `401` uniforme y saltándose el log) y `auto_error=False` colapsa "sin header" e "esquema inválido" en el mismo `None`, perdiendo el **motivo preciso** en el log. Leerlo del `Request` evita además que `Authorization` aparezca duplicado en la UI como parámetro suelto.
- Tests de **contrato** (`tests/test_openapi.py`): todas las rutas bajo `/v1`, cada operación con tag de dominio + `summary`/`description`, tags descritos, **solo** las rutas protegidas declaran seguridad, ejemplos presentes, y docs **activas en local / 404 en producción** (y la variable dedicada mandando sobre el ambiente).
- **Verificado en `/docs`:** endpoints agrupados por sección, rutas protegidas marcadas y **Authorize** funcional enviando el token.

**Tareas técnicas (como se hizo):** `app/api/v1/router.py` (agregador `/v1` + `TAGS_METADATA`) · `main.py` con metadatos, `openapi_tags` y URLs de docs condicionales · `Settings.enable_docs` + propiedad `docs_enabled` · `deps.bearer_scheme` + `AUTH_RESPONSES` · `summary`/`description`/`responses`/ejemplos en `health`, `auth` y `users` · `tests/test_openapi.py` · README (organización de la API, tabla de la desactivación de docs) y `.env.example`.

> **Decisión: `GET /v1/auth/me` se ELIMINÓ, consolidado en `GET /v1/users/me`.** La premisa de "check ligero de identidad" que traía la HU-1.10b era **falsa en la implementación**: `/v1/auth/me` hacía la **misma** validación del JWT y la **misma** lectura de `user_profiles` que `/v1/users/me` (el middleware carga esa fila igual, porque ahí materializa el perfil), y solo serializaba menos campos. No ahorraba red, ni consulta, ni JWKS. Lo que sí costaba: **dos contratos** que mantener sincronizados, **dos métodos** en `@rover/shared` y una duda para el cliente ("¿cuál llamo?") justo antes de las Épicas 3 y 4. Había nacido como **andamio** para verificar el middleware cuando aún no existían los endpoints de perfil; con el edificio en pie, el andamio se retira.
>
> Consecuencias: `getProfile()` responde ahora "¿quién soy?" leyendo `id`/`email`/`plan`; se eliminaron `getMe`, `MeResponse` e `isMeResponse` de `@rover/shared` (los cubre `Profile`/`isProfile`, un superconjunto); los tests del middleware pasaron a ejercerse contra `/v1/users/me` —una ruta protegida **real**, no una que existía para ser probada— en `tests/test_auth_middleware.py`; y un test verifica que `/v1/auth/me` **no está en el esquema** y responde `404`.

---

### HU-1.10 — Modelo de usuario y perfil *(dividida en 1.10a + 1.10b)*

La HU original juntaba **modelo + migración** y **endpoints**. Se dividió para poder cerrar el modelo antes que la auth (la creación perezosa del perfil de la HU-1.6 ya lo necesitaba) y dejar los endpoints para cuando existiera el middleware que los protege:

- **HU-1.10a — Modelo de perfil y migración** ✅ completada
- **HU-1.10b — Endpoints de perfil (`/v1/users/me`)** ✅ completada

---

### ✅ HU-1.10a — Modelo de perfil de usuario y migración
*Como* sistema, *quiero* una tabla local de perfil ligada al usuario de Supabase, *para* guardar plan y preferencias sin duplicar la identidad.

**Criterios de aceptación (como se construyó):**
- Modelo `UserProfile` (`app/models/user.py`) de **perfil**, no de identidad: `id` (el **mismo** UUID de `auth.users`, **sin default propio** — olvidar pasarlo debe fallar, no inventar una identidad que Supabase no conoce), `email` (copia de conveniencia; la fuente de verdad es Supabase), `plan`, `preferences` (JSONB con default `{}`, nunca NULL) y timestamps `timestamptz` puestos por la base. **No guarda contraseñas ni credenciales.**
- **Sin ForeignKey cross-schema a `auth.users` a propósito:** acoplaría nuestras migraciones al esquema interno de Supabase (que su tooling puede recrear) y rompería en cualquier base sin ese esquema (SQLite en tests). La integridad la garantiza la aplicación: el perfil se crea de forma idempotente sobre un usuario que **ya existe** en Supabase (HU-1.3 / HU-1.6).
- `plan` como **VARCHAR + CHECK** en vez del ENUM nativo de Postgres: añadir un plan es reemplazar la constraint en una migración normal (el ENUM nativo exige `ALTER TYPE` y no deja quitar valores) y el CHECK funciona igual en SQLite. `JSONB` en Postgres con `with_variant(JSON)` para SQLite.
- Migración Alembic `8a85e1e7b420` (autogenerada y revisada): crea `user_profiles` con índice por email; el `downgrade` la elimina limpiamente. `migrations/env.py` importa `app/models` para que el `--autogenerate` vea las tablas.
- Tests sin base real: declaración de la tabla, CHECK del plan, alta/lectura sobre SQLite async y defaults del lado de la base. `test_migrations` pasó a validar **historia lineal** (una head, una raíz sin padre), ya que la head dejó de ser la baseline.

**Tareas técnicas (como se hizo):** paquete `app/models/` · `UserProfile` + enum `Plan` · `env.py` importando los modelos · migración revisada a mano · tests de modelo y de historia de migraciones.

> **Reconciliación:** la HU-1.10 original hablaba del modelo como fuente de verdad/identidad. Con Supabase Auth como proveedor de identidad (decisión al inicio de esta épica), quedó reconciliado como **perfil** que referencia el id de `auth.users`. No queda contradicción en el documento.

---

### ✅ HU-1.10b — Endpoints de perfil (`/v1/users/me`)
*Como* usuario, *quiero* leer y actualizar mis preferencias de viaje, *para* que el agente me dé respuestas personalizadas más adelante.

**Criterios de aceptación (como se construyó):**
- `GET /v1/users/me` y `PATCH /v1/users/me` en un **router por dominio** (`app/api/v1/users.py`) bajo `/v1`, protegidos por `get_current_user` (HU-1.6). El id del usuario **siempre** proviene del token: por eso la ruta es `/me` y **nunca** `/users/{id}` — no hay forma de nombrar el recurso de otro. Test explícito de que un token de A no lee ni toca el perfil de B.
- **Solo `preferences` es editable.** El schema de entrada usa `extra="forbid"`: un PATCH que incluya `plan`, `id` o `email` responde **`422`** (no se ignora en silencio) y **ni siquiera la parte válida del cuerpo se aplica**. Criterio: exponer campos de más en un PATCH es una vía de **escalada de privilegios** (auto-ascenso a un plan de pago); `plan`, `id` y `email` los gobiernan Supabase (identidad) y la monetización (Épica 5), nunca el cliente. Test parametrizado que verifica el `422` **y** que el perfil no cambió.
- **Semántica del PATCH: merge superficial** (`{**actuales, **entrantes}`), **no** reemplazo total. Razón: web y móvil envían actualizaciones **parciales**; con reemplazo tendrían que hacer read-modify-write del objeto entero y dos clientes concurrentes se pisarían. Es predecible: las claves de primer nivel enviadas se fijan y los objetos anidados se **reemplazan en su clave** (sin merge profundo, para evitar ambigüedad). Test explícito de la semántica.
- **Límite de tamaño:** se acota el **resultado del merge** (lo que se guarda), no solo el payload entrante, a **8 KB** de JSON serializado → `422` si se excede. Acotar el resultado evita el crecimiento **acumulado** entre PATCHes sucesivos. Que `preferences` sea un **objeto** (y no array, número o string) lo garantiza el tipo `dict[str, Any]` → `422` por tipo.
- `@rover/shared` actualizado: tipos del perfil y métodos `getProfile` / `updateProfile` con **type guards**; el tipo de actualización impide **a nivel de tipos** enviar campos no editables (`plan`, `email`, `id`).
- **`GET /v1/auth/me` convivió al principio** como check de identidad del middleware (`id`, `email`, `plan`), con el solape anotado para resolverlo en la HU-1.9. **Ya resuelto: se eliminó** y quedó consolidado en `/v1/users/me`, que es el único endpoint de identidad y perfil (ver HU-1.9: el supuesto "check ligero" hacía exactamente el mismo trabajo).
- **Verificado end-to-end** contra Supabase real: lectura del perfil, merge (el idioma se conserva al cambiar solo la moneda) y **escalada rechazada** (`PATCH plan=pro` → `422`, con el plan intacto en `free`).

**Tareas técnicas (como se hizo):** router `app/api/v1/users.py` por dominio · schemas `ProfileResponse` / `ProfileUpdateRequest` (`extra="forbid"`) · merge superficial + tope de 8 KB del resultado · cliente compartido (tipos + `getProfile`/`updateProfile` + type guard) · tests de lectura, persistencia, merge, campos desconocidos, tipo, tope de tamaño, `updated_at` y aislamiento entre usuarios · helpers de firma de tokens extraídos a `tests/auth_utils.py`.

---

### HU-1.11 — CORS por ambiente
*Como* operador, *quiero* CORS restringido por ambiente, *para* no exponer la API a orígenes arbitrarios.

**Criterios de aceptación:**
- Los orígenes permitidos se leen de config, distintos por ambiente.
- En producción, `*` está prohibido; solo orígenes explícitos.
- Una petición desde un origen no permitido es rechazada.

**Tareas técnicas:** middleware CORS leyendo de config · valores por ambiente · documentar en `.env.example`.

---

### HU-1.12 — Observabilidad básica (logging estructurado)
*Como* operador, *quiero* logs estructurados con id de request, *para* diagnosticar problemas en producción.

**Criterios de aceptación:**
- Logs en formato estructurado (JSON) con timestamp, nivel, id de request y user_id si aplica.
- Cada request entra y sale con una línea de log correlacionable.
- Los errores `500` incluyen el id de error de la HU-1.8.
- No se loguean secretos ni datos sensibles (contraseñas, tokens).

**Tareas técnicas:** configurar logging estructurado · middleware de request id · correlación con el manejador de errores · revisar que no se filtren secretos.

> **Ya adelantado (HU-1.3b):** el **logging básico ya está resuelto** — `app/core/logging.py` (`configure_logging`, llamado desde `create_app`) enruta los loggers `app.*` a **stdout** con formato consistente y sin filtrar secretos, así que los diagnósticos de la app son visibles junto a los de uvicorn.
>
> **Ya adelantado (HU-1.8):** el **`error_id` de los `500` ya existe** y se loguea a nivel `error` con la causa real, el método y la ruta; el cliente lo recibe en el cuerpo. **Pendiente de esta HU:** el logging **estructurado** (JSON), el **request id**, y **correlacionar** ambos — que la línea de entrada/salida de cada request y el `error_id` compartan identificador, hoy inconexos.

---

## Cómo arrancamos la Épica 1

- **Orden sugerido** (de `backlog-full.md`): empezar por **HU-1.1 → 1.2** (base de datos y migraciones) **antes de auth**; luego 1.3 → 1.4 → 1.5 → 1.6 (auth completa), y de ahí 1.7–1.12.
- **Decisiones resueltas:** el backend de estado para rate limiting (HU-1.7) es **memoria del proceso**, tras la interfaz `RateLimitStore`. Redis (Upstash o propio) queda pospuesto con un disparador explícito: **cuando haya una segunda instancia**.
- **Siguiente épica:** cuando las 12 HU estén *Done*, añadimos la Épica 2 (El agente) a este documento.
