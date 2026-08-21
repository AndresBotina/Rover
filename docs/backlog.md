# Rover — Backlog activo

> **Documento de trabajo vivo.** Crece **épica por épica**: aquí solo se detalla la épica en curso. Cuando cerremos todas sus HU (cumpliendo la Definition of Done), añadimos la siguiente. El panorama completo de las 7 épicas vive en `backlog-full.md` como referencia.
>
> **Épicas 0 y 1: completadas.** Ambas quedan abajo como registro histórico de lo construido. **En curso: Épica 2 — El agente**, detallada al final de este documento. La deuda que convenía saldar antes de empezarla —la limpieza de los fixtures de test— está **resuelta** (HU-1.13); la que queda tiene disparadores propios y no bloquea (ver *Cierre de la Épica 1*).

---

## Cómo usar este documento

- **Jerarquía:** Épica → Historia de Usuario (HU = un Issue) → Tareas técnicas (checklist dentro del Issue).
- **Tablero (GitHub Projects):** `Backlog → En progreso → En revisión → Done`.
- **Flujo de trabajo:** un solo desarrollador; todo el trabajo se commitea directo en `develop` (no hay rama `main` ni PRs por ahora). La calidad la garantizan los hooks locales (lefthook) y el CI que corre en cada push a `develop`.
- **Labels sugeridas:** `epica:0-fundacion` · `epica:1-backend` · `epica:2-agente` · `tipo:hu | bug | tech-debt` · `prioridad:alta | media | baja` · `bloqueante`.
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
| 1 | Backend core | API `/v1`, async Supabase, Alembic, auth vía Supabase Auth, rate limiting, errores, CORS, observabilidad | Completada ✅ |
| **2** | El agente | Conversación con memoria, streaming SSE, sesiones y tool-calling con datos en vivo (clima primero) | **En curso** 🚧 (4/8) |
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

# ÉPICA 1 — Backend core ✅ COMPLETADA

**Objetivo:** el backend permanente y bien construido. API versionada, conexión async a Supabase, migraciones, autenticación delegada en Supabase Auth, rate limiting por plan, manejo de errores centralizado y observabilidad básica. Esto no se bota cuando crezcas; solo le pones más máquinas detrás.

> **Estado: las 15 HU están hechas** (1.1, 1.2, 1.3, 1.3b, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10a, 1.10b, 1.11, 1.12 y 1.13 — la numeración incluye la 1.3b, que nació de un caso descubierto al verificar la 1.3, el desdoble de la 1.10 en 1.10a/1.10b, y la 1.13, que salda una deuda técnica de la propia épica; el encabezado de la HU-1.10 se conserva porque explica esa división, pero no es una HU en sí). Esta sección queda como registro histórico. La deuda técnica restante está anotada al final, en *Cierre de la Épica 1*.

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

> **Deuda técnica (infra de tests) — ✅ RESUELTA en la HU-1.13.** Queda el registro de cómo se veía desde aquí, porque el recorrido explica por qué tardó tres HU en cerrarse.
>
> **El síntoma:** al correr el conjunto completo aparecían warnings intermitentes de aiosqlite (`RuntimeError: Event loop is closed`) durante el *teardown*. Nunca fueron fallos —la suite pasaba determinista— pero el warning afloraba en el test que estuviera corriendo en ese momento, no en el que lo causaba.
>
> **Lo que se creía la causa (desde esta HU y revisado en la HU-1.7):** los fixtures crean el engine SQLite con `asyncio.run(...)`, lo usan desde el loop del `TestClient` y lo cierran con otro `asyncio.run(engine.dispose())` — **tres event loops para el mismo engine**. Correcto, pero **incompleto**: era solo la mitad del problema.
>
> **Intentos descartados en la HU-1.7:** `poolclass=NullPool` en los engines de test y cerrar el generador de `get_db` con `aclosing` (esto último sí arregló una fuga real, ver la HU-1.7).
>
> **Por qué aquello no bastó, visto ya desde la HU-1.13:** el problema tenía **dos mitades** —el pool que recicla conexiones y el engine repartido entre loops— y cada intento atacó solo una. `NullPool` se probó **sin** quitar los `asyncio.run`, y reestructurar los fixtures sin tocar el pool habría dejado igual la conexión reutilizada. La causa raíz completa y el arreglo están en la **HU-1.13**.

---

### ✅ HU-1.5 — Renovación de sesión
*Como* usuario, *quiero* renovar mi sesión sin volver a loguearme, *para* una experiencia fluida sobre todo en móvil.

**HU de DOCUMENTACIÓN: no se escribió código.** El refresh y la rotación ya los resuelven Supabase y su SDK; el trabajo era dejar el flujo preciso por escrito para que las Épicas 3 y 4 no tengan que investigarlo otra vez. El resultado vive en [`docs/auth.md`](auth.md).

**Criterios de aceptación (como se construyó):**
- **El backend no renueva nada.** Valida el access token en local (HU-1.6) y responde `401` cuando ya no vale. No firma, no renueva, no revoca, y **nunca ve el refresh token** después del login.
- **El `401` de un token expirado es el `401` uniforme de siempre** y NO dice que el motivo fuera la expiración (mismo cuerpo para token ausente, malformado, con firma inválida o caducado; el motivo real solo va al log). Consecuencia documentada para los clientes: **no deben deducir del `401` si "basta con refrescar"** — esa decisión la toma el SDK, que sabe cuándo expira porque tiene la sesión.
- **La renovación la hace el SDK, directamente contra Supabase**, con `autoRefreshToken` (activo por defecto): renueva *antes* de expirar, de forma transparente. Rover no aparece en esa flecha.
- **Rotación documentada con sus dos reglas prácticas:** cada refresh puede emitir un refresh token nuevo e invalidar el anterior, así que (1) nunca copiar el refresh token a un sitio propio —la copia caduca en la siguiente renovación— y (2) no implementar reintentos propios de la llamada de refresh: reenviar uno ya consumido es lo que Supabase detecta como reuso. Hay una ventana corta de reutilización para renovaciones concurrentes, que el SDK ya coordina.
- **Fallo del refresh → re-login.** Refresh token expirado, revocado o reusado no tiene recuperación desde el cliente: el SDK emite `SIGNED_OUT`, limpia la sesión y la app manda al login. El backend no participa ni tiene nada que avisar.
- **Almacenamiento de tokens apuntado, no implementado:** web → decidir `@supabase/ssr` con cookies **antes** de la primera pantalla si hay Server Components o middleware (cambiarlo después toca layout, middleware y cada lectura); móvil → almacén seguro del sistema verificando su límite de tamaño por valor, `detectSessionInUrl: false`, y `startAutoRefresh`/`stopAutoRefresh` enganchados al `AppState` (los temporizadores no corren en segundo plano).
- **Checklists concretas para la Épica 3 y la Épica 4**, para que la sesión no se improvise cuando empiecen.

**Decisión: NO se expone `POST /v1/auth/refresh`.** Justificación completa en [`docs/auth.md`](auth.md#decisión-no-hay-un-post-v1authrefresh-propio); en corto: sería una reimplementación peor de lo que el SDK ya hace (el valor está en renovar antes de expirar, deduplicar renovaciones concurrentes y manejar la rotación, no en la llamada HTTP); añadiría un salto en el camino crítico de *seguir logueado* y convertiría a Rover en punto único de fallo para la sesión (hoy, con Rover caído, el usuario no puede usar la app pero **sigue autenticado**); ampliaría el radio de exposición del refresh token a nuestros logs y proxy en **cada** renovación en vez de una sola vez; y la rotación lo hace activamente peligroso de proxiar (un reintento ingenuo ante un timeout invalida una sesión válida). Se evaluaron y descartaron los casos a favor: un cliente sin SDK no existe hoy (y querría una credencial de servicio, no un refresh token de usuario), la revocación de sesiones es **otro** endpoint (`/v1/auth/logout`, posible HU futura) y ocultar la URL/anon key no compra nada porque son públicas por diseño. **Lo único que cambiaría la decisión** es querer que los clientes no hablen nunca con Supabase (p. ej. para poder cambiar de proveedor sin tocar web y móvil), pero eso obliga a proxiar **todo** el ciclo de sesión y renunciar al SDK: es una decisión de arquitectura de todo o nada, no un endpoint suelto.

**Punto ambiguo resuelto para las Épicas 3 y 4:** como Rover ya expone `/v1/auth/login`, había que decidir si el cliente se loguea contra Rover o contra el SDK — y importa, porque **el SDK solo renueva las sesiones que él conoce**: una sesión obtenida por `/v1/auth/login` y guardada a mano **no se renueva sola**. Recomendado: login contra Rover y entregarle la sesión al SDK con `setSession(...)` acto seguido. Conserva el catálogo de `code` de dominio y el contrato único de error (HU-1.8) sin renunciar al auto-refresh, porque el SDK acaba siendo el dueño de la sesión igual.

**Tareas técnicas:** `docs/auth.md` (flujo, rotación, fallo, almacenamiento, decisión del endpoint, checklists por épica) · enlaces desde el README del backend y el raíz · sin cambios en código (tests, lint y types siguen igual de verdes).

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

### ✅ HU-1.11 — CORS por ambiente
*Como* operador, *quiero* CORS restringido por ambiente, *para* no exponer la API a orígenes arbitrarios.

**Criterios de aceptación (como se construyó):**
- **Orígenes desde config, nunca en el código:** `ROVER_CORS_ORIGINS` (lista separada por comas). Se declara **crudo** (`str`) y se interpreta en `Settings.cors_allowed_origins`, igual que `enable_docs`/`docs_enabled`: un `list[str]` con default fijo no permitiría que el default **dependa del ambiente**, que es justo lo que aquí importa. Sin la variable: en `local`/`test`, `http://localhost:3000` y `http://127.0.0.1:3000` (van **los dos** porque para un navegador son orígenes distintos — la comparación es textual, no por resolución de nombres); en `production`, **ninguno**. Una cadena vacía significa "ningún origen", explícitamente: lo configurado manda sobre el default.
- **Producción sin orígenes → lista vacía, NO `*`.** Un despliegue al que se le olvidó la variable debe quedar **cerrado** a los navegadores, no abierto a todos. Y **no corta el arranque** (no entra en `_REQUIRED_IN_PRODUCTION`, a diferencia de los secretos): la API es perfectamente útil sin navegadores —móvil, `curl`, un servicio— y negarse a arrancar castigaría a esos clientes por una variable que solo afecta a la web, que ni siquiera existe hasta la Épica 3. El aviso se da por **log al arrancar**, porque el síntoma del olvido (la web falla con un error de CORS opaco) no apunta al backend por sí solo.
- **`*` en producción SÍ impide arrancar** (fail-fast en un `model_validator`, como el resto de la config): eso no es un olvido, es un error de configuración, y arrancar con él sería servir la API a cualquier página web con la sesión de quien la visita. Fuera de producción se admite, como escape hatch de depuración.
- **Política explícita en vez de comodines:** métodos `GET, POST, PATCH, OPTIONS` (los que la API usa hoy); cabeceras de petición `Authorization`, `Content-Type` y `X-Request-ID` — `application/json` **no** es un valor "simple" según la spec, así que sin declararlo el preflight rechazaría **todo** POST con cuerpo.
- **Cabeceras expuestas** (`Retry-After`, `X-RateLimit-*`, `X-Request-ID`): ninguna es *safelisted*, así que sin exponerlas el JavaScript del navegador **no puede leerlas** y `parseRetryAfter`/`ApiError.retryAfterSeconds` de `@rover/shared` (HU-1.7) devolverían siempre `null` en web aunque el 429 las traiga.
- **Credenciales desactivadas**: la sesión viaja en `Authorization`, no en cookies (ver [`docs/auth.md`](auth.md), HU-1.5). Activarlas no daría nada y ampliaría lo que un origen permitido puede hacer en nombre del usuario. Efecto lateral valioso: la combinación insegura **`*` + credenciales** es **imposible por construcción**, no depende de que nadie se acuerde.
- **Orden en la pila: CORS por FUERA del rate limiting.** Las cabeceras de CORS se añaden a la respuesta *al salir*, así que con CORS por dentro el **429** saldría sin ellas y el navegador se lo ocultaría a la web como un error de CORS genérico — no podría distinguir "te pasaste de peticiones" de "el servidor no responde", ni leer `Retry-After`. Contrapartida asumida y documentada: el **preflight no consume cupo** (lo responde CORS sin llegar al limitador); es barato —no toca ruta, ni base, ni JWKS— y no abre nada, porque quien quiera abusar manda peticiones reales, que sí cuentan.
- **20 tests** (`tests/test_cors.py`): origen permitido con `Vary: Origin`, origen ajeno sin permiso, `localhost` vs `127.0.0.1`, preflight por método, `Authorization` permitido, preflight de origen ajeno, credenciales ausentes, cabeceras del rate limit legibles, **el 429 con cabeceras de CORS**, el preflight sin consumir cupo, producción sin orígenes y con lista explícita, el comodín impidiendo arrancar, y la resolución de la config (defaults por ambiente, limpieza de la lista, cadena vacía).
- **Verificado contra un servidor real**, no solo en tests: cabeceras del origen permitido, ausencia de permiso para el ajeno, preflight completo, el `429` saliendo con `access-control-allow-origin`, y el arranque abortando con `ROVER_CORS_ORIGINS='*'` en producción.

**Tareas técnicas (como se hizo):** `Settings.cors_origins` + propiedad `cors_allowed_origins` + validador de `*` en producción · `configure_cors()` en `app/api/middleware.py` con la política en constantes · montaje en `create_app()` tras el rate limiter · `tests/test_cors.py` · README (§ CORS: tabla por ambiente, política, orden de la pila, verificación en local) y `.env.example`.

> **Nota para la Épica 3:** el dominio de los *preview deployments* de Vercel, si se quiere permitir, va enumerado en `ROVER_CORS_ORIGINS` como cualquier otro. Y el móvil (Expo) **no pasa por CORS**: esto solo afecta a la web.

---

### ✅ HU-1.12 — Observabilidad básica (logging estructurado)
*Como* operador, *quiero* logs estructurados con id de request, *para* diagnosticar problemas en producción.

> Dos piezas ya estaban al llegar aquí: el **logging básico** (HU-1.3b, `configure_logging` enrutando los `app.*` a stdout) y el **`error_id` de los 500** (HU-1.8). Lo que faltaba —y es lo que hizo esta HU— era el formato **estructurado**, el **request id**, y **correlacionarlos**.

**Criterios de aceptación (como se construyó):**
- **Dos formatos, uno por audiencia.** `ROVER_LOG_FORMAT` (`json`/`text`); sin definir lo decide el ambiente: **JSON en producción**, porque quien lee es una herramienta de monitoreo que necesita filtrar por campo (`level`, `request_id`, `status`, `duration_ms`) y no sabe leer prosa; **texto fuera**, porque quien lee es una persona en una terminal y un JSON por línea es hostil para eso. Cada línea JSON lleva `timestamp` (ISO 8601 **en UTC**, comparable entre instancias sin pensar en husos), `level`, `logger`, `message`, el contexto, y en las excepciones tipo, mensaje y traza.
- **Contexto sin ensuciar los call sites.** Cualquier `extra={...}` se emite como campo propio del JSON, sin tocar el formateador (los atributos estándar de `LogRecord` se filtran por lista; se descarta el `color_message` con escapes ANSI que uvicorn adjunta a los suyos).
- **Propagación del request id con un `ContextVar`** (`app/core/request_context.py`). Cada petición corre en su propia *task* de asyncio y cada task hereda su copia del contexto, así que lo que escribe el middleware lo ven **todas** las llamadas de esa petición y **solo** de esa —peticiones concurrentes no se pisan—. Un `Filter` de logging lo cuelga de **todos** los registros, así que **ningún call site cambia**: `logger.warning("...")` ya sale correlacionado. La alternativa (pasarlo por parámetro) contaminaría firmas que no tienen nada que ver con logs —los servicios no tienen el `Request` ni deberían— y bastaría un olvido para perder la traza.
- **Un segundo canal, el scope ASGI**, por un caso concreto descubierto al implementarlo: Starlette monta su `ServerErrorMiddleware` como **el más externo de todos**, así que cuando una excepción llega hasta él el middleware de contexto ya ejecutó su `finally` y restauró la variable. El handler del 500 sí tiene el `Request`, y el scope es el mismo objeto de principio a fin de la petición.
- **Id entrante respetado pero SANEADO.** Se acepta `X-Request-ID` si encaja en `[A-Za-z0-9._:-]{1,64}` —así una traza que empieza en un proxy o en la web sigue siendo la misma aquí— y si no, se genera uno propio. Es **entrada no confiable** que acaba en cada línea de log y en una cabecera de respuesta: un salto de línea permitiría **falsificar líneas de log enteras** (*log injection*) y un valor de 10 KB engordaría todas las líneas de la petición. Se **devuelve siempre** en la respuesta, también en los 500.
- **Correlación `error_id` ↔ `request_id`: DOS campos, juntos en la misma línea.** No se unifican porque no son lo mismo ni se confían igual: el `request_id` identifica **la petición**, está en todas sus líneas y en toda respuesta, y **puede venir de fuera**; el `error_id` identifica **un fallo** concreto, existe solo en los 500 y es lo que el usuario cita al reportar. Unificarlos dejaría que un cliente **eligiera** el identificador con el que se archiva un error del servidor —cómodo para envenenar búsquedas en el log o hacer colisionar dos incidentes— y perdería la traza compartida con el proxy. Con los dos en la misma línea se navega en ambos sentidos sin renunciar a nada.
- **Una línea de acceso por petición** con método, ruta, status y duración, en su **propio logger `app.access`** —es un flujo distinto (una línea por petición, siempre) de los eventos puntuales del resto de la app, y quien opera querrá filtrarlo por separado—. Nivel según el status: `INFO` <400, `WARNING` 4xx, `ERROR` 5xx. Sustituye a `uvicorn.access`, que se **silencia**: dice lo mismo y además trae id y duración. Los demás loggers de uvicorn se reenganchan a nuestro handler, para que en producción no salgan líneas de texto suelto entre el JSON.
- **Qué NO se registra: cuerpo, cabeceras y query string.** Lo último es una **política deliberada**, no una omisión: hoy ningún endpoint recibe nada sensible por query, pero los que suelen llegar después (búsquedas, enlaces de confirmación con código, filtros con datos del usuario) sí, y para entonces nadie se acordaría de revisar el middleware. La ruta basta para saber qué se llamó. `Authorization` nunca se loguea.
- **`RequestContextMiddleware` es el más externo de la pila**, por delante de CORS y del rate limiting, para que **todo** lo de dentro —incluido un 429 o un preflight que CORS corta en seco— salga con id en logs y cabecera.
- **`@rover/shared`:** `ApiError` gana `requestId` (leído de la cabecera) y se exporta `REQUEST_ID_HEADER`. **Complementa** a `errorId` sin sustituirlo: el request id existe también en los errores que no son 500 (un 429, un 401) y en las respuestas correctas.
- **24 tests nuevos** (21 backend + 3 shared): JSON válido con sus campos, la línea de acceso con método/ruta/status/duración, el nivel por status, el id en **todas** las líneas y en la cabecera, id entrante respetado y el inválido descartado (incluido un intento de *log injection*), la correlación en un 500, y **la ausencia de secretos con una petición que lleva contraseña, token en `Authorization` y query string**.
- **Verificado contra un servidor real** en los dos formatos: en JSON, todas las líneas (arranque de uvicorn incluido) parsean; en texto, dos líneas de la misma petición compartiendo id.

**Tareas técnicas (como se hizo):** `app/core/request_context.py` (ContextVar + saneo + canal por scope) · `app/core/logging.py` (`JsonFormatter`, `TextFormatter`, `RequestIdFilter`, reenganche de uvicorn) · `Settings.log_format` + `effective_log_format` · `RequestContextMiddleware` · correlación y cabecera en `unhandled_exception_handler` · `@rover/shared` (`requestId` + `REQUEST_ID_HEADER`) · `tests/test_logging.py` y tests del cliente · README (§ Observabilidad) y `.env.example`.

> **Fuera de alcance, a propósito:** el `user_id` en las líneas de log. Lo pedía el criterio original, pero la identidad no existe hasta que `get_current_user` valida el token —dentro del router—, así que la línea de acceso (que corre en el middleware, por fuera) no puede tenerlo sin repetir la validación. Las líneas que **sí** conocen al usuario ya lo registran donde importa (auth, rate limiting), y el `request_id` permite cruzarlas con la de acceso. Añadirlo a todas exigiría un segundo `ContextVar` que rellene la dependencia; queda como mejora si algún día hace falta filtrar por usuario en el monitoreo.

---

### ✅ HU-1.13 — Limpieza de los fixtures de test *(deuda técnica)*
*Como* desarrollador, *quiero* que la suite corra sin warnings espurios, *para* que un aviso en los tests signifique siempre algo real.

> **HU de DEUDA TÉCNICA**, arrastrada desde la HU-1.3 y revisada sin éxito en la HU-1.7 y al cerrar la épica. No cambia el comportamiento de la app: **no se tocó una sola línea de `app/`**.

**Causa raíz (más profunda que el diagnóstico que veníamos arrastrando):**

- El diagnóstico anterior —"tres event loops para el mismo engine"— era **correcto pero incompleto**. Medido con una sonda, el pool real de los engines de test era **`AsyncAdaptedQueuePool`, que REUTILIZA conexiones**: una conexión abierta bajo un event loop terminaba usándose —o cerrándose— bajo otro que ya estaba muerto. Ésa es la mitad que faltaba.
- Con las **dos mitades** a la vista (un pool que recicla + un engine creado y cerrado con `asyncio.run(...)` en loops distintos) se explica por qué **el intento de la HU-1.7 falló**: probó `NullPool` **sin** quitar los `asyncio.run`. Atacar una sola mitad no arregla nada, y por eso la deuda parecía irreductible.

**Criterios de aceptación (como se construyó):**
- **Fixture central `bd` en `tests/conftest.py`, con tres piezas que se necesitan JUNTAS:**
  - **`NullPool`** — ninguna conexión se guarda para reutilizarse, así que **ninguna cruza de loop ni sobrevive al que la abrió**. Es la raíz.
  - **Un `BlockingPortal` por test** — un único event loop vivo durante todo el test, en el que el engine **nace, crea el esquema, se consulta y muere**. `bd.run(...)` sustituye a `asyncio.run(...)` con el mismo uso desde tests síncronos, sin fabricar y tirar un loop por llamada.
  - **Fichero temporal en vez de `:memory:`** — con `NullPool` cada conexión es nueva, y una base en memoria sería una base **vacía distinta por conexión** (el clásico "no such table"). Antes funcionaba de milagro: el pool reciclaba la única conexión que tenía el esquema. El fichero evita además el `StaticPool`, que arreglaría el esquema **volviendo a compartir una conexión entre loops** — justo lo que se quería quitar.
- **Scope de función**, un fichero por test: el aislamiento entre tests es exactamente el que ya había (cada uno montaba su propia base).
- **Módulos refactorizados:** `test_auth`, `test_auth_middleware`, `test_users_me`, `test_rate_limit`, `test_database` y **`test_models`** —este último no estaba en el diagnóstico y también montaba su engine—. Fuera cuatro copias de `_usar_sqlite`, las listas de engines/ficheros pendientes de limpiar y sus teardowns. El test de la carrera del `IntegrityError` deja de montar su `StaticPool` en memoria y corre entero dentro de `bd.run`. `tests/auth_utils.py` se reutiliza tal cual, sin duplicar nada. Neto: **−297/+235 líneas**.
- **Refactor de andamiaje, no de intención:** verificado **diffeando todos los `assert`** del cambio. Las únicas seis diferencias son el argumento de un helper (`factory` → `bd`); los valores esperados son idénticos.
- **Se conserva un `asyncio.run`**, en `_ejecutar` de `test_rate_limit`: corre corutinas del almacén en memoria, que no tocan la base ni nada que sobreviva al loop. Está documentado en su docstring para que no parezca un olvido.
- **Verificación:** **192 tests verdes en 17 corridas seguidas, sin un solo warning de aiosqlite**, más una corrida con **`-W error::pytest.PytestUnhandledThreadExceptionWarning`** (el aviso convertido en fallo duro) también en verde. Comprobado además que ningún módulo crea ya engines sueltos y que no quedan ficheros `.sqlite` huérfanos. Efecto lateral: la suite baja de **~3,8 s a ~1,7 s**, por dejar de levantar y tirar un event loop por consulta.
- **Dependencias: ninguna nueva.** Se **declara** `anyio>=4.14.1` en el grupo `dev` porque ya venía como transitiva de Starlette y ahora `conftest.py` la importa **directo** (`BlockingPortal`); dejarla implícita sería un import prestado que se rompe el día que Starlette cambie de dependencias. No se adoptó `pytest-asyncio`: la suite es síncrona y usa `TestClient`, así que habría obligado a convertir los tests a `async def` —un cambio de forma en todos ellos— sin resolver nada que el portal no resuelva ya.

**Tareas técnicas (como se hizo):** fixtures `loop_de_test` (portal) y `bd` (engine + esquema + `get_session_factory` parcheado) en `tests/conftest.py` · clase `BaseDeTest` (`engine`, `factory`, `run`) · refactor de los seis módulos · `anyio` declarada en `dev`.

> **Salvedad honesta, para que quede en el registro:** el warning **no se pudo reproducir a voluntad** —ni en 14 corridas previas al arreglo, ni forzando GC sobre engines huérfanos—. `aiosqlite` 0.22.1 ata el future al loop **que llama** (`future.get_loop()`) en vez de a uno capturado al nacer el hilo trabajador, lo que estrechó mucho la ventana de fallo desde que se escribió el diagnóstico original. Es decir: **lo corregido y objetivamente verificable es el defecto estructural** (conexiones cruzando loops), no una reproducción del síntoma. Se deja dicho para no atribuirle al arreglo más evidencia de la que tiene.

---

## Cierre de la Épica 1

**Las 15 HU están completadas** (1.1, 1.2, 1.3, 1.3b, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10a, 1.10b, 1.11, 1.12 y 1.13). El backend tiene API versionada con documentación, base async con migraciones, identidad delegada en Supabase Auth con validación local del JWT, perfil de usuario, rate limiting en tres ámbitos, contrato único de error, CORS por ambiente y logs estructurados correlacionables. **192 tests** en el backend y **53** en `@rover/shared`, con lint, formato y tipado estricto en verde, y **sin warnings espurios en la suite**.

### Deuda técnica

1. ~~**Limpieza de los fixtures de test (aiosqlite)**~~ — ✅ **RESUELTA en la HU-1.13**, que era el requisito recomendado antes de arrancar la Épica 2. Era la única deuda que **empeoraba sola** (cada HU con base de datos copiaba el patrón), y la que más iba a estorbar justo aquí: la Épica 2 trae streaming y concurrencia, donde un "Event loop is closed" espurio puede costar horas de diagnóstico. La suite entra en la Épica 2 **limpia**.
2. **Rate limiting en memoria del proceso** (HU-1.7): con varias instancias el límite efectivo se multiplica por el número de instancias. **Disparador explícito: la segunda instancia.** El punto de cambio está aislado tras la interfaz `RateLimitStore` (implementar `hit`/`peek`/`reset` con un `ZSET` + script Lua y llamar a `reset_rate_limit_store(...)` al arrancar); ni la política, ni el middleware, ni la dependencia, ni los endpoints cambian.
3. **Catálogo `ErrorCode` duplicado a mano** entre el backend y `@rover/shared` (HU-1.8). Duplicación consciente y barata (una línea por código); desaparece sola el día que se generen los tipos desde el esquema OpenAPI —idea anotada en el cliente compartido desde la HU-0.7—.

### Qué queda apuntado para las Épicas 3 y 4

La sesión y su renovación están resueltas **por escrito** en [`docs/auth.md`](auth.md) (HU-1.5), con checklists por épica: el backend nunca renueva, el SDK de Supabase es el dueño de la sesión, y el cliente que se loguee contra `/v1/auth/login` debe entregarle la sesión con `setSession(...)` acto seguido o el auto-refresh no funcionará. No hay `POST /v1/auth/refresh` y la decisión está justificada allí.

### Siguiente épica

**Épica 2 — El agente**, detallada abajo y **en curso**. El diseño se reenfocó respecto al esqueleto de `backlog-full.md`: la v1 es conversar con memoria, en streaming y con datos en vivo; RAG, caché semántico y voz quedaron diferidos con disparador.

---

# ÉPICA 2 — El agente 🚧 EN CURSO

**Objetivo:** el corazón del producto. Un agente que **conversa con memoria, en streaming, y consulta datos en vivo** — empezando por el clima. Text-first, con personalidad en el system prompt y un cerebro económico (DeepSeek V4 Flash) tras una abstracción de proveedor. Se apoya en toda la Épica 1: base async, auth, rate limiting, contrato único de error y logs correlacionables.

> **Progreso: 4 de 8 HU.** ✅ HU-2.1 (capa de LLM) · ✅ HU-2.2 (personalidad vía system prompt) · ✅ HU-2.3 (modelo de datos de conversaciones — la que estrenó el patrón de fixtures limpio de la HU-1.13; migración aplicada y verificada contra Supabase) · ✅ HU-2.4 (endpoint de chat con streaming SSE). **Rover ya conversa de verdad:** hay un `POST /v1/chat` protegido que responde token a token y deja la conversación guardada, verificado de punta a punta contra DeepSeek real. Siguiente: **HU-2.5** (contexto multi-turno y sesiones), que es lo que convierte esa conversación guardada en **memoria** — hoy se escribe entera, pero al modelo solo se le manda el mensaje actual.

> **Alcance deliberado de la v1:** RAG, caché semántico, voz y router por dificultad **no entran**. Cada uno queda abajo, en *Diferido a segunda iteración*, con su detalle técnico intacto y un **disparador** explícito. El criterio: hasta que el núcleo —conversar, recordar, consultar en vivo— no esté sólido, cualquiera de esas piezas es peso que se arrastra sin saber todavía si hace falta.

## Decisiones de arquitectura

- **Cerebro:** DeepSeek V4 Flash tras una abstracción de proveedor, **single-model**. La selección por **capacidad** (derivar a otro modelo lo que pida visión, cuando llegue) queda prevista como *seam* en el código; la selección por **dificultad** se difiere. El endpoint es **OpenAI-compatible**, lo que abarata cambiar de proveedor.
- **Streaming: SSE, no WebSockets.** Es HTTP estándar: encaja con la auth por header y el CORS ya montados (HU-1.6, HU-1.11), atraviesa proxies sin ceremonia, y el flujo es unidireccional — no hay nada que un socket bidireccional resuelva aquí.
- **Sesiones: dos tablas** (conversaciones y mensajes). Se **persisten los pasos intermedios** del tool-calling (qué herramienta, con qué argumentos, qué devolvió) porque son oro para depurar y para el router futuro, pero **al cliente solo se le expone el texto conversacional**. Título simple ahora, **soft-delete**, y la conversación pertenece al usuario **por el id del token** — nunca por un id que venga en el cuerpo.
- **Contexto: ventana por tokens**, no por número de turnos, y estructurada **stable-prefix-first** (system prompt → definiciones de tools → historial → mensaje nuevo) para que el **caché automático de DeepSeek** muerda. El resumen de historial largo se difiere.
- **Conocimiento (v1): modelo base + herramientas en vivo.** El RAG bajo demanda se difiere.
- **Herramientas: tool-calling directo, no LangGraph.** Un framework de orquestación se adopta cuando la orquestación duela de verdad; hoy no duele. El **clima** es la herramienta de referencia que fija el patrón, y **cada tool vive tras su propia abstracción**. El mapa **visual** es de las Épicas 3 y 4 — aquí solo viajan los **datos**.
- **Personalidad en system prompt, no fine-tuning:** portable entre modelos e iterable en minutos.
- **Las tools de pago se miden:** el rate limiting de la HU-1.7 acota *peticiones*; el control de consumo (HU-2.8) acota *consumo* — tokens y llamadas a APIs que se cobran.

---

### ✅ HU-2.1 — Integración con el LLM y abstracción de proveedor
*Como* sistema, *quiero* hablar con el LLM a través de una capa que abstraiga el proveedor, *para* cambiar de modelo sin reescribir el agente.

**Criterios de aceptación (como se construyó):**
- **Interfaz primero, proveedor después.** `LLMProvider` es un `Protocol` en `app/services/llm/base.py` con `complete` y `stream`; la implementación de **DeepSeek V4 Flash** sobre su endpoint OpenAI-compatible vive aislada en `deepseek.py`, y **nada fuera de ese archivo** conoce la forma de la API del proveedor. Misma jugada que `RateLimitStore` en la HU-1.7: la interfaz es lo estable, la implementación lo desechable.
- **Tipos de dominio propios** (`Message`/`Role`, `Completion`, `CompletionChunk`, `Usage`): el resto del backend habla **el idioma de Rover, no el de DeepSeek**, y el `dict` del proveedor no se pasea por el agente, el SSE ni la persistencia. **Errores traducidos** a excepciones propias (`LLMRateLimited`, `LLMUnavailable`, `LLMAuthError`, `LLMQuotaExceeded`, `LLMBadRequest`, `LLMProviderError`, `LLMNotConfigured`, `LLMCapabilityUnavailable`), con el mismo contrato que las de `services/auth.py`: el mensaje es **seguro para el usuario** y el diagnóstico del proveedor (status, `code`/`type` y su texto) viaja aparte, **solo para los logs**. La traducción es **por status** —el dato estable de una API HTTP—, nunca buscando palabras dentro del mensaje: mismo criterio que con GoTrue, donde clasificar por texto ya había clasificado mal.
- **Streaming real**, no un extra: `stream(...)` es un async generator cuyos `text` son **deltas** (concatenarlos reconstruye la respuesta) y cuyo último trozo trae el `usage` — se pide `stream_options.include_usage`, porque si no el camino de streaming, que es el normal del producto, sería un **agujero ciego** en las métricas. Un evento ilegible a mitad se **descarta y el stream sigue**: una respuesta a medias en pantalla vale más que un corte por un trozo roto.
- **Dos métodos (`complete`/`stream`) en vez de un flag `stream: bool`**, porque devuelven cosas de tipo distinto —un valor y un async generator—: el flag obligaría a todo llamador a desambiguar en tiempo de ejecución lo que el tipo ya sabe en tiempo de compilación.
- **`stream` devuelve `AsyncGenerator` y no `AsyncIterator`, a propósito:** obliga a que exista `aclose()`. El endpoint SSE de la HU-2.4 va a abandonar streams a mitad **de forma rutinaria** (el usuario cierra la pestaña), y sin `aclose()` la conexión con el proveedor queda colgando hasta que pase el recolector. Es la **misma lección de la HU-1.13**: un recurso que sobrevive a quien lo abrió no falla donde se creó, falla en el test —o en la petición— siguiente.
- **Config, nada hardcodeado:** `ROVER_LLM_API_KEY` (`SecretStr`, **en `_REQUIRED_IN_PRODUCTION`**), `ROVER_LLM_BASE_URL` (default DeepSeek; se le **concatena** `/chat/completions`, así que admite sufijo tipo `…/v1`), `ROVER_LLM_MODEL`, y los parámetros de generación (`TEMPERATURE`, `MAX_OUTPUT_TOKENS`, `TIMEOUT_SECONDS`). Cambiar a otro proveedor OpenAI-compatible es **cambiar entorno, no código**.
- **System prompt como prefijo estable:** es un parámetro **aparte**, no "un mensaje más", y la implementación lo antepone siempre en la misma posición (`system → tools (HU-2.6) → historial → mensaje nuevo`). La estructura **impide por construcción** que un llamador lo mueva o lo interpole con la fecha y tumbe el caché automático de todas las peticiones sin que nada se ponga rojo. El texto real llega en la HU-2.2; hoy `prompt.py` tiene un placeholder que ya cumple la única regla que importa para el caché: **es una constante**.
- **Seam de capacidad, sin router:** `get_llm_provider(Capability.VISION)` levanta `LLMCapabilityUnavailable` en vez de caer al de texto en silencio —un modelo de texto al que le mandas una imagen no protesta, **responde mal**, y ese fallo se leería como "el agente alucina"—. Añadir el modelo de visión es **una línea en `registry.py`**. El router por **dificultad NO se implementó**, como estaba previsto.
- **Instrumentación** (`instrumentation.py`): **una** línea del logger `app.llm` por llamada, con campos `llm_*` — proveedor, modelo, capacidad, streaming, resultado (`ok`/`error`/**`cancelled`**, este último para el stream abandonado: no es fallo del proveedor pero **los tokens ya se gastaron**), latencia total, **latencia hasta el primer trozo**, tokens de entrada/salida, tokens de caché y su **ratio**, motivo de fin y tamaño del contexto. **No** se registra el contenido: ni mensajes, ni prompt, ni respuesta, ni la key. El tamaño en **caracteres** es el sustituto deliberado del contenido — permite correlacionar contexto grande con latencia o fallos, que es para lo que se querría mirar el prompt, sin copiar una conversación privada a un sistema de logs. Es la **semilla del router por dificultad** y la base del consumo por plan de la HU-2.8.
- **Tests (50 nuevos: 44 de la capa + 6 de config; 242 en el backend y 53 en `@rover/shared`), verdes SIN la key real** — el CI no la tiene. La mayoría usa `httpx.MockTransport`, que ejerce el **camino real** —cuerpo, cabeceras, parseo del JSON y del SSE, traducción de errores, instrumentación— contra respuestas escritas a mano: un mock del método `complete` habría pasado igual aunque el cliente mandara el cuerpo al revés. Cubren: completado no-streaming, **streaming en orden** y reconstrucción por concatenación, chunk de `usage`, keep-alives y eventos ilegibles que **no tumban** el stream, los **nueve** status traducidos, red caída y timeout, error **antes** y **a mitad** del stream, la instrumentación emitida en éxito/error/cancelación, y que **no filtra secretos ni contenido** (frase señuelo en el mensaje del usuario: si aparece en el log, el test se pone rojo). Un doble que implementa el `Protocol` sin heredar de nada prueba que el contrato es sustituible, y un test vigila que **nada salga a la red**. Tres tests que construían `Settings` de producción se ajustaron para incluir la key: el **fail-fast funcionando**, no un daño colateral.
- **Verificado contra DeepSeek REAL**, no solo en tests, con `scripts/check_llm.py`: responde en modo **completo** y en **streaming** (los trozos llegan de a poco, no de golpe), y la línea de instrumentación sale con tokens, latencia y tiempo al primer trozo. La **traducción de errores se ejerció de verdad, sin provocarla**: un `402 Insufficient Balance` del proveedor salió como el mensaje de dominio —genérico y seguro— con el diagnóstico (`status`/`code`/mensaje del proveedor) **solo en el log**. Es justo el caso que más importaba: contarle al usuario que a Rover se le acabó el saldo no le sirve de nada y dice de más sobre la infraestructura.

**Decisión de integración: `httpx` directo, NO el SDK de OpenAI.** El endpoint es OpenAI-compatible, así que el SDK apuntado a otra `base_url` era la alternativa obvia. Se descartó porque: (1) devuelve **sus** modelos, que traduciríamos acto seguido a los tipos de dominio — una capa de más, no un paso menos; (2) el **`prompt_cache_hit_tokens`** de DeepSeek no existe en su esquema tipado y es media razón de ser de la instrumentación de esta HU; (3) queremos controlar la traducción de errores en vez de desempacar su jerarquía de excepciones para volver a empaquetarla; y (4) **`httpx` ya está en el proyecto** y su async es real (el SDK lo usa por debajo), así que **no se añadió ninguna dependencia**. Es el mismo razonamiento que llevó a hablar con GoTrue por HTTP en vez de con `supabase-py`. Lo que se renuncia, dicho claro: **reintentos automáticos** (política que se decidirá en la HU-2.4 — reintentar un stream a medias no es reintentar un POST) y el parseo de SSE hecho, que aquí son unas pocas líneas de un formato fijado por estándar.

**Tareas técnicas (como se hizo):** `app/services/llm/` (`base.py` interfaz + tipos, `errors.py`, `prompt.py`, `deepseek.py`, `instrumentation.py`, `registry.py`) · seis variables nuevas en `Settings` con la key en `_REQUIRED_IN_PRODUCTION` · aislamiento del registro de proveedores en `conftest.py` (mismo criterio que el contador de rate limiting) · `tests/test_llm.py` y tests de config · `scripts/check_llm.py` para comprobar contra el proveedor real en local · `.env.example` (sección reescrita: la variable estaba etiquetada como "Épica 1, más adelante") y README (§ Proveedor de LLM).

> **Corrección posterior (tras la HU-2.2) — razonamiento DESACTIVADO para el chat.** Al verificar la HU-2.2 apareció un dato que no cuadraba: los `output_tokens` salían muy por encima del texto visible. La causa: **DeepSeek V4 razona por defecto**, con esfuerzo alto, y ese razonamiento **se factura como salida** — ~1.163 tokens y ~15 s para una respuesta conversacional de cuatro frases. El cuerpo lleva ahora `thinking: {"type": "disabled"}` en los dos caminos (completo y streaming). Detalles de la decisión:
>
> - **Es config (`ROVER_LLM_THINKING`, default `disabled`), no una constante**, porque el router por dificultad —diferido— querrá justo lo contrario para lo que sí lo vale (un itinerario de tres ciudades con fechas y presupuesto). Misma filosofía que `ROVER_LLM_MODEL`: reactivarlo es cambiar entorno, no código. Un valor desconocido **corta el arranque** en vez de caer en silencio al modo caro.
> - **Tercer valor `provider_default`, que omite el campo:** `thinking` es una extensión **propietaria** de DeepSeek y esta clase sirve para cualquier proveedor OpenAI-compatible; el que rechace parámetros desconocidos se atiende sin editar `deepseek.py`. La forma del campo (`{"type": …}`, no un booleano) se queda dentro del módulo del proveedor, igual que `prompt_cache_hit_tokens`.
> - **El parseo no dependía de `reasoning_content` y sigue sin depender:** lee `message.content` y `delta.content`, así que funciona igual con el razonamiento activado (el campo extra se ignora; los eventos de la fase de pensamiento salen como texto vacío, que es justo lo que se quiere: no se enseña al usuario lo que el modelo rumia) y desactivado. Documentado en ambos parsers y con tests de los dos caminos.
> - **Aviso plantado para la HU-2.6:** con el razonamiento activado, DeepSeek **exige** que las peticiones multi-turno con tools devuelvan el `reasoning_content` del turno anterior o responde **400**. Hoy no aplica; quien lo reactive tendrá que preservar ese campo en los pasos intermedios (HU-2.3) y reenviarlo en el loop. Se descubre con un 400 en la **segunda** vuelta del loop, no en la primera — de ahí que quede escrito en el código y no solo aquí.
> - **Efecto lateral que vuelve a contar:** en modo razonamiento DeepSeek **ignora** `temperature` y `top_p`; en non-think mandan otra vez, así que el `ROVER_LLM_TEMPERATURE` de la config (0.7) pasa a tener efecto real.
> - **10 tests nuevos** (262 en el backend) y **verificado contra DeepSeek real**: *"¿dónde tomo el mejor café en Bogotá?"* → **346 tokens de salida y 7,0 s** para una respuesta de cuatro párrafos, frente a ~1.163 y ~15 s con una respuesta más corta. El caché del prefijo estable sigue acertando (512/575, 89 %).

> **Nota:** la tarea original decía `services/agent/llm.py`, un archivo. Se implementó como **paquete** `services/llm/` porque la HU pide seis cosas que quieren vivir separadas (contrato, errores, prompt, implementación, instrumentación, registro) y meterlas en un módulo habría hecho que el archivo del *contrato* —lo único que el resto del backend debería leer— llegara mezclado con el parseo de SSE de un proveedor concreto.

> **Contexto que hereda la HU-2.2 — `cached_input_tokens = 0` es lo ESPERADO hoy, no un fallo.** En las llamadas de verificación el acierto de caché salió en cero, y así debe ser: el system prompt real llega en la HU-2.2 y hoy `prompt.py` tiene un placeholder de una línea. **Sin un prefijo estable largo no hay nada que cachear** — DeepSeek cachea por bloques del prefijo común, y una frase suelta no llega. Lo que esta HU deja listo es la **estructura** (el prompt va primero, aparte y sin interpolar); el ahorro aparece cuando la HU-2.2 ponga un prompt de verdad delante, y **la métrica ya está instrumentada para comprobarlo**: si tras la HU-2.2 `llm_cache_hit_ratio` sigue en cero llamada tras llamada, hay algo invalidando el prefijo y se está pagando de más.
>
> **Confirmado en la HU-2.2:** con el prompt real delante (656 tokens de entrada), la segunda llamada idéntica sirvió **640 de caché — el 98 %**. La predicción de esta nota se cumplió tal cual.

---

### ✅ HU-2.2 — Personalidad vía system prompt
*Como* producto, *quiero* la personalidad de Rover en un system prompt versionado, *para* iterarla rápido y mantenerla portable entre modelos (sin fine-tuning).

**Criterios de aceptación (como se construyó):**
- **El texto vive en `app/services/llm/prompts/rover.md`**, versionado en el repo. Cambiar cómo habla Rover es **editar ese archivo** y ver el diff en git — no una fila de base de datos (invisible en un PR, distinta por ambiente, sin historial) ni un string incrustado en un endpoint. `prompt.py` queda como lo que debe ser —el **cargador**— y sigue exponiendo `DEFAULT_SYSTEM_PROMPT`, así que **nada del resto del backend cambió**: la capa de la HU-2.1 ya lo anteponía como prefijo estable.
- **Un directorio `prompts/`, no un archivo suelto,** porque la HU-2.6 puede querer un prompt propio para el loop de tools y el sitio ya está. Junto al prompt vive su `README.md` con las reglas de edición: es donde mira quien va a **editar el texto**, que no es necesariamente quien lee Python.
- **La personalidad refleja las decisiones de producto:** amigo cercano que además sabe de viajes (tuteo, energía **contenida** — sin exclamaciones ni emojis en cascada, el entusiasmo se nota en el interés, no en la puntuación); **recomienda con criterio** en vez de enumerar (dice cuál es la trampa de turistas y por qué), y pregunta lo justo **después** de dar valor, no antes; responde **en el idioma en que le escriben**; se mantiene en viajes y **reconduce con gracia** lo que se sale, sin sonar a política recitada; y es **honesto por encima de sonar seguro** — no inventa horarios, precios ni requisitos, y dice explícitamente que no tiene datos en tiempo real ni sabe qué día es hoy.
- **Carga UNA vez, al importar.** Es la definición operativa de "prefijo estable" (todas las llamadas de un despliegue mandan **los mismos bytes**; leer en cada petición abriría la puerta a que el prompt cambiara a mitad de la vida del proceso) y evita una **syscall bloqueante** en el camino de cada petición async. El precio, dicho claro: editar el archivo no entra en caliente en producción — entra con el deploy. Barato a cambio de la estabilidad del prefijo.
- **Un archivo ausente o vacío TUMBA el arranque**, con `RuntimeError` y **no** con `LLMNotConfigured`: esa la capturan los llamadores para devolver un `503` por petición, y esto no es un problema de una petición sino un **despliegue mal construido**. Mismo fail-fast que una variable obligatoria ausente (HU-0.8), y por la misma razón: un Rover sin personalidad **responde igual de bien a un `curl`**, así que el fallo sería invisible hasta que alguien leyera una conversación sosa en producción.
- **Normaliza CRLF y los espacios de los extremos, y nada más:** el prefijo depende del **commit**, no del editor con que se guardó. Sin eso, el mismo commit podría producir cachés distintos según el checkout.
- **La regla del prefijo estable está documentada donde se edita** (`prompts/README.md`), con lo que **no** puede entrar (fecha, nombre o plan del usuario, destino, marcadores de plantilla) y **dónde va lo variable**: detrás, como un mensaje más del contexto. Incluye la nota del **registro** (tú/vos/usted): cambiarlo exige tocar **la instrucción y la voz del propio texto**, porque el modelo imita el registro en que está escrito el prompt.
- **Tests (10 nuevos; 252 en el backend, 53 en `@rover/shared`).** `tests/test_prompt.py` vigila justo la propiedad que **no falla ruidosamente**: que el prompt sea una **constante**. Un prefijo dinámico no rompe nada visible —la app responde igual, solo que pagando la entrada completa en cada llamada—, así que el síntoma sería **una factura, no un fallo**. Cubre: que lo que se manda es **exactamente el archivo** (nada añadido por código), que no lleva **marcadores de plantilla** (`{…}`, `%s`, `${…}`), que **no lleva la fecha de hoy** (canario contra el error clásico de interpolarla), que **llega al mínimo para que el caché muerda**, que los finales de línea no lo cambian, y el fail-fast de archivo ausente/vacío. En `test_llm.py` se añadió que el prompt **también viaja en el camino de streaming** — el normal del producto: si faltara ahí, Rover tendría personalidad solo en las llamadas que casi nadie hace.
- **El test del largo mínimo (400 caracteres) es de negocio, no de estilo:** DeepSeek cachea en **bloques de 64 tokens** y lo que no llegue a un bloque **no se cachea nunca**. Sin ese test, un recorte "de limpieza" mataría el ahorro de esta HU en silencio.
- **Verificado contra DeepSeek REAL** con `scripts/check_llm.py`, que ahora hace **la misma llamada dos veces** y da un veredicto explícito: prompt de **1.946 caracteres → 656 tokens de entrada**; primera llamada `cached_input_tokens=0` (es la que **llena** el caché), segunda **`cached_input_tokens=640` — el 98 % de la entrada servida de caché**. Es el criterio observable de la HU cumplido: el prefijo estable funciona. La personalidad se ve en la respuesta (tuteo, tono cercano, consejo concreto: *"no te olvides de la chaqueta y el paraguas"*).

**Tareas técnicas (como se hizo):** `app/services/llm/prompts/rover.md` (el texto) y `prompts/README.md` (reglas de edición) · `prompt.py` convertido en cargador (`load_system_prompt` + `DEFAULT_SYSTEM_PROMPT`, con normalización y fail-fast) · `tests/test_prompt.py` · test de streaming en `tests/test_llm.py` · `scripts/check_llm.py` con la segunda llamada y el informe de caché · README del backend (§ La personalidad de Rover, y el bloque de verificación con el ejemplo de salida).

> **Observación anotada al verificar, ya resuelta:** en las llamadas reales los `output_tokens` salían muy por encima del texto visible (706 tokens para una respuesta de una frase). La sospecha —razonamiento interno facturado como salida— se confirmó y se corrigió: ver *Corrección posterior* en la HU-2.1, que desactiva el razonamiento para el chat. Lo que sigue siendo cierto y hereda la **HU-2.8**: la cuota por plan se calcula sobre los **tokens reportados**, nunca sobre los caracteres que ve el usuario. La instrumentación de la HU-2.1 ya los registra por llamada.

---

### ✅ HU-2.3 — Modelo de datos de conversaciones
*Como* usuario, *quiero* que mis conversaciones queden guardadas, *para* retomarlas después y que el agente tenga de dónde recordar.

**Criterios de aceptación (como se construyó):**
- **Dos tablas en `app/models/conversation.py`** (estilo SQLAlchemy 2.0, como el resto del backend). `conversations`: `id` **UUID propio** —generado en Python, no con `gen_random_uuid()`, porque el stream SSE de la HU-2.4 necesita el id **antes** de que vuelva el INSERT para anunciarlo en el primer evento—, `user_id` con FK a `user_profiles.id` `ON DELETE CASCADE` e **índice**, `title` (`VARCHAR(120)`, vacío por defecto y **nunca NULL**: una sola forma de decir "sin título"), `created_at`/`updated_at` del lado de la base, y `deleted_at` para el **soft-delete**. `messages`: `id`, `conversation_id` con FK `ON DELETE CASCADE`, `role`, `sequence`, `content` (`Text`, sin límite: un itinerario largo es una respuesta legítima), `tool_steps` y `created_at`.
- **`deleted_at` es un timestamp, no un booleano `is_deleted`:** cuesta lo mismo y responde una pregunta más —**cuándo**—, que es justo la que necesitan el purgado por retención ("borra de verdad lo que lleve 30 días en la papelera") y una duda de soporte ("perdí la conversación de ayer"). El booleano **no se convierte después** en timestamp sin inventarse las fechas; el timestamp sí se proyecta a booleano cuando haga falta (`Conversation.is_deleted`).

**Decisiones de diseño:**
- **FK a `user_profiles` CON cascade — y sí, es distinto del caso de la HU-1.10a.** Allí se evitó a propósito una FK **cross-schema** a `auth.users`: esquema ajeno, gestionado por el tooling de Supabase y ausente en SQLite. `user_profiles` la crea **esta misma cadena de migraciones**, así que aquí la FK no acopla nada externo y a cambio hace **imposible** una conversación huérfana. La creación **perezosa** del perfil no la pone en riesgo: `get_current_user` (`api/deps.py`) materializa el perfil y hace **commit antes** del cuerpo de cualquier endpoint protegido, así que cuando la HU-2.4 inserte una conversación la fila del perfil ya existe. Y el `ON DELETE CASCADE` es una regla de **retención / derecho al olvido escrita en la base**, no en la memoria de quien acabe escribiendo el borrado de cuenta.
- **El orden es `sequence` explícito, NO `created_at`.** `now()` en Postgres es la hora de **inicio de la transacción**: el mensaje del usuario y la respuesta del asistente se escriben en la misma transacción, reciben el **mismo instante** y su orden queda **indefinido** — y con un `id` UUID **aleatorio** no hay desempate posible. El loop de tools (HU-2.6) solo empeora el empate, con varias filas de una vez. La **`UNIQUE(conversation_id, sequence)`** convierte el bug en un `IntegrityError` **en el INSERT**, ruidoso y en el sitio, en vez de un contexto reordenado en silencio la próxima vez que se lea; también sirve la consulta "los mensajes de esta conversación, en orden", y por eso `conversation_id` **no** lleva índice propio (sería un segundo índice con el mismo prefijo, pagando escrituras en el camino más caliente del producto). `created_at` se conserva, pero para responder **"cuándo"**, no **"en qué orden"**.
- **`tool_steps` va DENTRO de la fila del mensaje del asistente** (JSONB, una **lista** de pasos — lo que se guarda es una secuencia ordenada: llamada 1 → resultado 1 → llamada 2 → …), **no como filas sueltas con `role="tool"`**. El `role="tool"` de la API OpenAI-compatible es un **formato de cable, no un modelo de almacenamiento**: copiarlo obligaría a **cada** lectura —la que arma el contexto (HU-2.5) y la que responde al cliente (HU-2.4)— a acordarse de filtrar por rol, y el día que a una se le olvidara el usuario vería el JSON crudo de una API del clima. Con `content` como **lo público** y `tool_steps` como **lo interno en la misma fila**, un serializador que exponga `content` **no puede** filtrar los pasos por descuido: la frontera está en la forma de la tabla, no en la disciplina de quien escriba el endpoint. Por eso `MessageRole` solo tiene `user` y `assistant` (**VARCHAR + CHECK, no ENUM nativo** —mismo criterio que `plan` en la HU-1.10a—, para que añadir `tool` mañana sea reemplazar una constraint y no un `ALTER TYPE`). **Hoy `tool_steps` nace vacío**: las tools son la HU-2.6; existe para que la tabla nazca con la forma correcta y no haya que migrar datos después. `system` no se persiste nunca: la personalidad es un archivo versionado (HU-2.2) que se antepone en cada llamada.
- **Helpers de consulta** (`select_live_conversations`, `select_conversation_messages`) para que el filtro `deleted_at IS NULL` y el `ORDER BY sequence` se escriban **en un solo sitio**. Repartidos por los endpoints de la HU-2.4 y la HU-2.5, el día que a una consulta se le olvide el filtro, el usuario ve **reaparecer** una conversación que borró — y nada falla.

**Migración y verificación:**
- **`e98b4722e99b`, autogenerate revisada a mano:** la variante SQLite del JSON vive **solo en el modelo** (los tests crean el esquema desde `Base.metadata`, no con migraciones) y la migración usa **JSONB a secas**, que es lo único que corre en Postgres; el `downgrade` borra `messages` **antes** que `conversations`, por la FK. **Verificada contra un Postgres efímero**: `upgrade` / `downgrade -1` / `upgrade` limpios y un autogenerate de sonda **vacío** después — cero deriva entre modelo y esquema. Las constraints se ejercieron de verdad (rol inválido, secuencia duplicada, secuencia negativa, `user_id` inexistente, y el CASCADE llevándose conversaciones y mensajes al borrar el perfil). Después se **APLICÓ contra Supabase**: las dos tablas creadas y verificadas.
- **Tests (15 nuevos; 277 en el backend, 53 en `@rover/shared`), con el patrón de fixtures de la HU-1.13** —una sola base y un solo event loop por test, sin base de datos real—. Cubren: la **declaración** de ambas tablas (columnas, tipos, nullability, defaults, índices y FKs, incluido el `ondelete`), el **orden por `sequence`** aunque se inserten desordenados, `tool_steps` como **lista JSON** que sobrevive el viaje de ida y vuelta y nace vacía, el **soft-delete** sacando la conversación de las vivas (y que las vivas son solo las del dueño), los **defaults del lado de la base**, y el **CHECK del rol** rechazando en las **dos** capas. Un test extra vigila que `MessageRole` (almacenamiento) y el `Role` del proveedor (`services/llm/base.py`, con `system` y `tool`) **no se separen**: responden a preguntas distintas y coinciden a propósito para que la traducción sea directa.

**Tareas técnicas (como se hizo):** `app/models/conversation.py` (`Conversation`, `Message`, `MessageRole` y los dos helpers de consulta) · registro en `app/models/__init__.py` · índice por `user_id` y `UNIQUE(conversation_id, sequence)` sirviendo también el orden · migración `e98b4722e99b` revisada a mano · `tests/test_conversation_models.py` sobre el patrón de la HU-1.13.

> **Nota para la HU-2.5 — `updated_at` NO salta al añadir un mensaje.** El `onupdate` se dispara cuando se actualiza **esa** fila, y escribir un mensaje no toca la conversación. Si la HU-2.5 quiere listar por **actividad reciente** (que es como `select_live_conversations` ordena hoy), tendrá que **tocar la conversación al escribir el mensaje**. Queda dicho aquí y en el modelo porque el síntoma sería **una lista mal ordenada, no un error**.

> **Lo que esta HU deliberadamente NO trae:** el título derivado del primer mensaje y el `user_id` sacado del token son criterios que **se cumplen en la HU-2.4**, donde existe la petición — aquí solo está la **forma** que los admite (`title` vacío por defecto; `user_id` como columna que nadie llena todavía). Esta HU es modelo de datos: no hay endpoint ni escritura en producción hasta la HU-2.4.

---

### ✅ HU-2.4 — Endpoint de chat con streaming SSE (conversación pura)
*Como* usuario, *quiero* ver la respuesta aparecer token a token, *para* una experiencia fluida en vez de una espera en blanco.

**Criterios de aceptación (como se construyó):**
- **`POST /v1/chat`**, protegido por `get_current_user` (HU-1.6) y con la **cuota por usuario** declarada a nivel de **router** (HU-1.7), igual que `users`: así una ruta protegida nueva nace con límite en vez de olvidarlo — y aquí importa el doble, porque una petición de chat cuesta tokens de verdad. Responde en **SSE** con cuatro eventos: `start` (trae el `conversation_id` y si la conversación acaba de nacer), `delta` (un trozo de texto), `done` (fin correcto, con el `sequence` del mensaje del asistente) y `error`. El request es Pydantic con **`extra="forbid"`**: `message` (recortado, 1–8.000 caracteres) y `conversation_id` opcional; un campo de más responde 422 en vez de ignorarse, que aquí pesa más que en un PATCH normal — el **dueño sale siempre del token**, y un campo que pareciera aceptarse invitaría a un cliente a intentarlo.
- **Un solo `data:` con JSON discriminado por `type`, y NO el campo `event:` del estándar** (`app/api/sse.py`). Dos razones: (1) **nadie va a consumir esto con `EventSource`** —solo sabe hacer GET y no deja poner cabeceras, así que no podría mandar ni el mensaje ni el `Authorization: Bearer`—, y web y móvil lo leen con `fetch`, donde el nombre del evento no aporta nada que no dé el discriminante; (2) con `event:` **y** `type` habría dos fuentes para lo mismo y podrían discrepar. El JSON no lleva saltos de línea reales, así que un evento siempre cabe en una línea `data:` — que es justamente por lo que el texto viaja como JSON y no crudo, donde un salto de línea del modelo habría partido el marco en dos.
- **Persistencia y streaming:** se crea la conversación si es nueva (**título** derivado del inicio del primer mensaje —simple y determinista, nada de gastar una llamada al modelo justo antes de la respuesta que el usuario está esperando—, `user_id` **del token** y **UUID generado en Python**, que es lo que permite anunciarlo en el primer evento sin releer la fila); se persiste el **mensaje del usuario** al arrancar el turno; se emite el texto trozo a trozo **acumulándolo**; y **solo si el stream termina completo** se persiste la respuesta del asistente con el `sequence` siguiente. La respuesta del asistente se escribe en su **propia sesión** de base de datos: el cuerpo de un `StreamingResponse` corre DESPUÉS de que la función del endpoint devolvió, y cuándo cierra FastAPI una dependencia con `yield` es un detalle de su versión — no es sitio para apoyar el camino más caliente del producto.
- **Contexto de UN turno, con el punto de extensión marcado:** `services/chat.build_context` ya recibe un `historial` (hoy vacío) y ya lo ordena como el prefijo estable manda (`system aparte → tools (HU-2.6) → historial → mensaje nuevo`). La ventana por presupuesto de tokens es la HU-2.5 y será una llamada distinta desde el endpoint, no una reescritura de la firma.

**El invariante del que salen los tres finales del stream.** Un endpoint normal tiene un momento para fallar; este tiene tres. En vez de decidir caso por caso, hay **una sola regla**:

> **El mensaje del usuario se guarda al arrancar el turno; el del asistente SOLO si el stream terminó completo.** De ahí: **toda fila `assistant` es una respuesta completa.**

Que sea una regla y no tres decisiones es el punto. Si el aborto descartara y el error a mitad guardara —o al revés—, el estado de una conversación tras un fallo dependería de **cuál** fallo, y nadie podría razonar sobre un historial sin conocer la historia de cada turno. Lo que deriva:

- **Aborto del cliente** (cierra la pestaña) → **se descarta la respuesta parcial**. No es por comodidad: esa fila **reentraría en el contexto del modelo** en el turno siguiente (HU-2.5) y se leería como *"esto fue lo que Rover respondió"* — una frase cortada a mitad, para siempre, contaminando cada turno posterior de esa conversación. Guardarla "para no perder los tokens ya gastados" **confunde la memoria con el libro de cuentas**: el consumo ya quedó anotado en la serie `llm_outcome=cancelled` de la HU-2.1, que es donde se factura (HU-2.8); la tabla de mensajes es la memoria. Se llama **`aclose()`** sobre el generador del proveedor (vía `aclosing`) para que la conexión no quede colgando hasta que pase el recolector — para eso la HU-2.1 tipó `stream` como `AsyncGenerator` y no como `AsyncIterator`. Precio asumido, dicho claro: quien se va tras leer el 90 % de una respuesta larga la pierde.
- **Error a MITAD del stream** → misma regla, **se descarta**. El `200` ya salió y el status no se puede cambiar, así que el error va **dentro del SSE** como un evento con el **mismo cuerpo de la HU-1.8** (mismo catálogo de `code`; se construye desde `ErrorBody`, no a mano, para que un campo nuevo del contrato aparezca aquí solo), el stream se cierra limpio y la **causa real** —status, `code` y mensaje del proveedor— va al **log con el `request_id`** (HU-1.12), nunca al cliente.
- **Error ANTES del stream** → **no deja rastro ninguno**, porque el turno se escribe **después** del primer trozo: ni conversaciones vacías ni preguntas duplicadas, y reintentar es limpio. Se responde con un **status HTTP normal** en formato HU-1.8, con sus handlers y sus cabeceras de CORS (`503` proveedor caído/sin saldo/sin key, `429` si nos limita, `422` si rechazó el mensaje). **Costo asumido:** para poder distinguir este caso, el endpoint **le pide el primer trozo al modelo antes de devolver las cabeceras**, así que el tiempo hasta la primera cabecera incluye la latencia del modelo. A cambio, "el proveedor está caído" es un error HTTP que los clientes ya saben tratar, en vez de un `200 OK` que se desdice dos bytes después.

**Resto de los criterios:**
- **Conversación ajena, inexistente o borrada → `404 not_found`, no 403.** Un 403 **confirmaría que ese id existe**: convertiría el endpoint en un oráculo para enumerar UUIDs y averiguar qué conversaciones tienen otras personas. Y los tres casos no son indistinguibles por disciplina de quien escribió el `if`: **colapsan dentro de la CONSULTA** (`load_conversation` se construye sobre `select_live_conversations`, que ya filtra `deleted_at IS NULL`), así que un refactor no puede separarlos sin querer. Mismo criterio que hizo que la ruta de perfil sea `/users/me` y no `/users/{id}`. Hay un test que compara los **dos cuerpos byte a byte**.
- **Cabeceras anti-buffering** (`Cache-Control: no-cache, no-transform`, `Connection: keep-alive`, `X-Accel-Buffering: no`) y **ninguna compresión montada** en la app — comprimir un stream obliga a llenar un bloque antes de emitir, que es buffering con otro nombre. El detalle de proxies (Render, nginx, Cloudflare) vive en [`docs/deploy.md`](deploy.md) y la sección **Chat en streaming** del README del backend. Verificado además que el **429 de `/v1/chat` sale con cabeceras de CORS** —el rate limiting va por dentro de CORS a propósito (HU-1.7)— y que el preflight se responde sin consumir cupo.
- **`@rover/shared`:** tipos del request y de los cuatro eventos como **unión discriminada**, un **type guard por variante** (más `parseChatStreamEvent`, que devuelve `null` en vez de lanzar: un marco roto no debe tumbar una respuesta que ya se está pintando) y `readSseFrames`, un parser de marcos que **reconstruye los cortados entre chunks de red** y no corrompe un multibyte partido en la frontera. `client.streamChat(token, …)` lo entrega con un `for await` tipado: un fallo **antes** del stream lanza `ApiError`; uno **a mitad** llega como evento y **no lanza** —para entonces puede haber texto en pantalla que el usuario está leyendo—. Mismo espíritu que el contrato discriminado de la HU-1.3b.
- **Tests: 38 nuevos en el backend (315) y 17 en `@rover/shared` (70)**, sin DeepSeek real y sin base real (doble del `Protocol` + fixture de la HU-1.13). El foco no es "¿responde 200?" sino **qué queda en la base tras cada uno de los tres finales**, que es la parte que no falla ruidosamente. El **aborto se ejerce contra el generador directamente** —un TCP cortado no se simula bien con `TestClient`— verificando que el `aclose()` **llegó al proveedor** y que **no hay fila `assistant`**. Cubren además: orden de los trozos y que su concatenación **es igual al contenido guardado**, continuar hilo con el `sequence` correcto (y sin reescribir el título), el 404 indistinguible, los cuatro errores pre-stream traducidos, que el **diagnóstico del proveedor no aparece en el cuerpo** (`402`, `insufficient_balance`), el **`request_id` presente en el log emitido DENTRO del generador**, la cuota por usuario y el 429 con CORS. `test_openapi.py` —que lleva un inventario explícito de rutas protegidas y de tags— se amplió para `/v1/chat`: el test haciendo su trabajo, no un daño colateral.
- **Verificado end-to-end.** El streaming incremental **no se puede comprobar con `TestClient`**: `httpx.ASGITransport` bufferiza y da un falso negativo. Se comprobó contra **`uvicorn` real**, y los trozos llegan **separados en el tiempo** (~0,4 s entre eventos con un proveedor lento), no de golpe; `--no-buffer` es imprescindible en el `curl`, porque si no el que acumula es la propia herramienta y el diagnóstico sale mal por su culpa. La **persistencia se confirmó en Supabase**: roles alternando, `sequence` sin huecos y `tool_steps` vacío (las tools son la HU-2.6). Y cortando el `curl` a mitad, la conversación quedó **con la pregunta y sin respuesta** — la decisión del aborto, funcionando.

**Tareas técnicas (como se hizo):** `app/api/sse.py` (forma del cable + cabeceras + el error de la HU-1.8 adaptado) · `app/services/chat.py` (conversaciones, `sequence`, `build_context`; sin saber de HTTP) · `app/api/v1/chat.py` (endpoint, request, traducción de errores del LLM y el generador de eventos) · registro del router y su tag en `api/v1/router.py` · `packages/shared/src/types/chat.ts` y `client.streamChat` · `tests/test_chat.py`, `chat.test.ts` y ampliación de `client.test.ts` y `test_openapi.py` · README del backend (§ Chat en streaming) y `docs/deploy.md` (§ Streaming SSE en producción).

> **Nota heredada para la HU-2.5 — `updated_at` sigue sin saltar al añadir un mensaje.** La HU-2.3 lo dejó anotado y esta HU **no lo cambió**, a propósito: la 2.3 asignó explícitamente ese trabajo a la 2.5 y traérselo aquí habría sido ampliar el alcance. Como `select_live_conversations` ordena por `updated_at desc`, la HU-2.5 tendrá que **tocar la fila de la conversación al escribir el mensaje** para que la lista por actividad reciente salga bien. El síntoma si se olvida sería **una lista mal ordenada, no un error** — por eso queda escrito en tres sitios (el modelo, la HU-2.3 y aquí).

> **Lo que esta HU NO trae, y estaba previsto que no:** herramientas (HU-2.6) y memoria multi-turno (HU-2.5). El agente recuerda **dentro del turno**, no entre turnos: hoy el contexto que se le manda al modelo es el mensaje actual. La conversación **ya queda guardada entera**, así que la 2.5 es leerla y recortarla, no rehacer nada de esto.

---

### HU-2.5 — Contexto multi-turno (ventana por tokens) y sesiones
*Como* usuario, *quiero* hacer preguntas de seguimiento sin repetir contexto, *para* conversar de verdad y no lanzar preguntas sueltas.

**Criterios de aceptación:**
- El historial se trunca por **presupuesto de tokens**, no por número de turnos, y se arma **stable-prefix-first** (coherente con la HU-2.1).
- Queda **documentada la decisión** de qué pasos intermedios de tool-calling se reenvían al modelo y cuáles no: reenviarlo todo infla el costo, no reenviar nada pierde el hilo de una herramienta ya usada.
- `GET /v1/chat/sessions` lista las conversaciones del usuario; `GET /v1/chat/sessions/{id}` devuelve el historial **solo con el texto conversacional** (los pasos intermedios se quedan del lado del servidor).
- `DELETE /v1/chat/sessions/{id}` hace **soft-delete**; una conversación borrada no vuelve a aparecer en el listado.
- Un test verifica la **coherencia multi-turno**: una pregunta de seguimiento se responde usando el turno anterior.
- `@rover/shared` actualizado con los tipos y métodos nuevos.

**Tareas técnicas:** conteo de tokens y truncado por presupuesto · armado stable-prefix-first · política documentada de reenvío de pasos intermedios · endpoints de sesiones · soft-delete · tests de coherencia multi-turno · `@rover/shared`.

---

### HU-2.6 — Maquinaria de tool-calling + herramienta de clima (referencia)
*Como* viajero, *quiero* que el agente consulte datos en vivo —el clima de un destino, para empezar—, *para* recibir respuestas útiles y no solo lo que el modelo recuerda.

**Criterios de aceptación:**
- Existe un **registro de herramientas** con esquema (nombre, descripción, parámetros) y una interfaz común para implementarlas.
- El **loop de tool-calling funciona con streaming**: el usuario ve texto mientras el agente decide, invoca y procesa el resultado.
- El **clima** es la primera herramienta, **tras su propia abstracción** de proveedor (cambiar de API de clima no toca el agente); la key va fuera del repo, en config.
- Los **pasos intermedios se persisten** (HU-2.3) y **no se exponen** al cliente.
- Un error de una herramienta **no tumba la conversación**: el agente lo dice y sigue (degradación elegante).
- Tests con tool mockeada: **ciclo completo** (el agente la pide, se ejecuta, el resultado vuelve al modelo) y **camino de fallo**.

**Tareas técnicas:** registro e interfaz de tools · loop de tool-calling sobre el stream · abstracción e integración de la API de clima · persistencia de los pasos intermedios · manejo de fallo de tool · tests de ciclo y de fallo.

---

### HU-2.7 — Herramientas adicionales (patrón repetido)
*Como* viajero, *quiero* que el agente consulte más fuentes en vivo además del clima, *para* resolver preguntas de planeación reales.

> **Se concreta al priorizarla.** La maquinaria y el patrón ya los fija la HU-2.6: cada herramienta nueva es una repetición del mismo molde, no un diseño nuevo. Candidatas identificadas:
>
> - **Lugares** (comer, ver, hacer): Google Places, Mapbox o alternativa. Es **API de pago** — hay que medir el consumo y elegir por **costo y lock-in**, no solo por cobertura.
> - **Búsqueda web** (Tavily u otra): para lo que ni el modelo ni las tools específicas cubren.
> - **Datos geográficos**: distancias, rutas, geocoding. **Solo el dato** — la visualización en mapa es de las Épicas 3 y 4.

**Criterios de aceptación:**
- Cada herramienta vive **tras su propia abstracción**: cambiar de proveedor no toca el agente.
- Su key es un **secreto en config**, fuera del repo.
- Su consumo se **mide**, y si es de pago **cuenta para la cuota de la HU-2.8**.
- Devuelve resultados **estructurados** que el agente integra de forma natural; el fallo se degrada con gracia.
- Test con la API mockeada.

**Tareas técnicas:** elegir proveedor por costo y lock-in al priorizar · abstracción e integración · esquema de la tool · medición de consumo · tests.

---

### HU-2.8 — Control de consumo del agente por plan (freemium)
*Como* operador del freemium, *quiero* limitar el consumo del agente según el plan, *para* que un usuario intensivo no vuelva insostenible el costo.

**Criterios de aceptación:**
- Cuota por plan sobre lo que **cuesta dinero**: mensajes/tokens del modelo y **llamadas a tools de pago**, con reseteo por periodo.
- Se apoya en el **enganche por plan ya montado en la HU-1.7** (`rule_for_user(multiplier=…)`) como **ámbito nuevo**: la 1.7 acota *peticiones*, esto acota *consumo*.
- Al agotarse la cuota, la respuesta usa el **contrato de error de la HU-1.8** con un mensaje claro que invita al upgrade, no un error críptico.
- El conteo es **consistente entre instancias**: hoy en memoria del proceso, con Redis **cuando llegue la segunda instancia** — mismo disparador y mismo punto de cambio aislado que la deuda #2 del cierre de la Épica 1.
- La cuota **distingue** el consumo servido desde caché (barato o gratis) del que golpea el modelo o una API de pago.
- Tests: se respeta la cuota, se resetea por periodo, y el mensaje de límite trae el `code` correcto.

**Tareas técnicas:** modelo de cuota por plan · contador tras la interfaz de store (memoria hoy, Redis con la segunda instancia) · mensaje de límite en formato HU-1.8 · conteo diferenciado de tools de pago · tests.

---

## Diferido a segunda iteración (con disparador)

Nada de esto es un descarte: es **detalle ya pensado que se guarda entero** para no rediseñarlo cuando toque. Cada entrada lleva su **disparador** — la señal concreta que la devuelve al backlog activo.

### Caché semántico de respuestas

**Disparador:** volumen de preguntas repetidas que justifique el ahorro. Sin tráfico real es complejidad sin beneficio medible; con tráfico, en viajes las preguntas frecuentes se repiten muchísimo **entre usuarios distintos**, y ahí pasa a ser la mayor palanca de ahorro del producto.

**Detalle técnico conservado (de la antigua HU-2.12):**
- Antes de llamar al LLM, se busca una respuesta cacheada **semánticamente similar** (por embedding).
- Si hay un match **por encima de un umbral**, se sirve del caché sin tocar el LLM.
- El caché tiene **expiración/invalidez configurable** y **no sirve respuestas obsoletas de datos en vivo**: el clima y demás datos vivos **no se cachean igual** que el contenido estable — servir un clima viejo desde caché es peor que no cachear.
- **Métricas:** tasa de aciertos del caché observable.
- **Test:** una pregunta repetida no llama al LLM.
- **Tareas:** store de caché con embeddings · lógica de umbral y expiración · regla para no cachear datos en vivo · métricas de hit-rate · tests.

*Enganche ya previsto:* la HU-2.8 distingue el consumo servido por caché del que golpea el modelo.

### RAG bajo demanda (efímero)

**Forma que tomará:** el usuario pasa un **link o un archivo**, se procesa **al vuelo**, el agente responde con eso y **no se persiste**. Es lo contrario de la biblioteca curada que planteaba el diseño viejo: el conocimiento lo trae el usuario en el momento, no lo mantiene el operador. La **variante persistente** (base de conocimiento propia, ingestión curada) se evalúa aparte y solo si aparece la necesidad.

**Disparador:** núcleo del agente sólido (HU-2.1–2.6 en producción y estables) **y** necesidad real de que el usuario aporte contenido propio.

**Detalle técnico conservado (de las antiguas HU-2.5, 2.6 y 2.7)** — sirve tanto para la variante efímera como para la persistente:

- **Ingestión, job async (antigua 2.5):** `POST /v1/ingest` recibe una fuente, **encola un job y responde de inmediato** (no bloquea la API). El job **descarga, limpia y trocea** el contenido en chunks. Los **chunk IDs se derivan de un hash de url+contenido**, para que no haya colisiones entre fuentes. El **estado del job** es consultable (pendiente/procesando/listo/error). Backend de jobs a decidir: `BackgroundTasks`/Upstash al inicio, Celery si el volumen lo pide. *(En la variante efímera el "responde de inmediato" pierde sentido —el usuario está esperando su respuesta—, pero el pipeline de limpieza, chunking y hashing se conserva igual.)*
- **Embeddings y almacenamiento en pgvector (antigua 2.6):** cada chunk genera su **embedding** y se almacena en **Supabase con pgvector**; el **modelo de embeddings sale de config** (intercambiable); existe **índice vectorial** para búsqueda eficiente; migración Alembic asociada. **Test:** un chunk ingerido queda consultable por similitud.
- **Recuperación y armado de contexto (antigua 2.7):** dada una consulta se recuperan los **top-k** chunks por similitud; se inyectan en el prompt **de forma acotada**, sin inflar el contexto sin control; si **no hay contexto relevante**, el agente lo maneja con gracia y **no inventa**. **Test:** una pregunta sobre contenido ingerido recupera el chunk correcto.

### Router por dificultad

**Disparador:** que la **instrumentación de la HU-2.1** (tokens, latencia, modelo, cache hit) muestre que el modelo barato **falla o exige reintentos en una fracción significativa del tráfico**. Solo entonces el router se diseña **contra ejemplos reales** de dónde falla, en vez de contra una intuición previa.

> **La instrumentación ya está emitiendo** (✅ HU-2.1): una línea de `app.llm` por llamada, con `llm_model`, `llm_outcome`, `llm_duration_ms`, `llm_ttfc_ms`, tokens de entrada/salida y `llm_cache_hit_ratio`. O sea: el disparador **ya se puede medir**; lo que falta es tráfico real que medir. Cuando llegue, el sitio donde encajaría el router es `registry.py`, tomando la petición como entrada además de la capacidad.

*No confundir con la selección por **capacidad*** (derivar a un modelo con visión), que sí queda prevista como *seam* en la HU-2.1.

### Voz (pipeline opcional)

**Disparador:** núcleo de texto sólido **y** una decisión de producto de priorizar voz. La voz siempre fue un **modo opcional**: el agente funciona al 100 % en texto.

**Requisito no-funcional de latencia (transversal a todo lo de voz, conservado):** tiempo hasta el **primer audio < 2 s** en los modos de **pipeline**, logrado con **streaming encadenado** — STT parcial en vivo → modelo en streaming → TTS que arranca en la primera frase, sin esperar la respuesta completa. El modo **speech-to-speech** apunta a latencia **sub-segundo**. Ninguna HU de voz está *Done* si no cumple su objetivo de latencia.

**Detalle técnico conservado:**
- **Voz de entrada, STT (antigua 2.14):** endpoint que recibe audio y devuelve la **transcripción**; el texto transcrito entra **al mismo flujo de chat** que un mensaje escrito; la transcripción es **en streaming** (parcial en vivo mientras el usuario habla), no se espera al final — clave para la fluidez; el proveedor de STT sale de **config**; fallo degradado a *"no te entendí, ¿puedes escribir?"*; test con STT mockeado.
- **Voz de salida, TTS (antigua 2.15):** la respuesta de texto se convierte a audio vía TTS, en **pipeline desacoplado del LLM**; proveedor desde **config** (arrancar con uno económico de baja latencia); el TTS **arranca en cuanto está lista la primera frase**, sin esperar la respuesta completa (**< 2 s** al primer audio); **solo se genera audio cuando el usuario está en modo voz** (no se gasta TTS de más); fallo de TTS degradado a solo texto; test con TTS mockeado.
- **Audio servido por URL, no base64 (antigua 2.16):** el audio TTS se sube a **Supabase Storage** y la API devuelve una **URL** (prefirmada si aplica); la respuesta de chat **no incluye base64** — respuestas ligeras y audio **cacheable**, que en móvil es determinante; respuestas repetidas **no regeneran** el mismo audio; test: la respuesta trae URL y no base64.
- **Manos libres / VAD** y **speech-to-speech**: **nunca llegaron a escribirse como HU** en el backlog viejo — la única huella era la referencia a "HU-2.18 (speech-to-speech)" dentro de la nota de latencia. Quedan aquí como **piezas por diseñar**, con su objetivo ya fijado: detección de actividad de voz para conversar sin tocar la pantalla, y un modo speech-to-speech de latencia **sub-segundo** que se salta el pipeline STT→LLM→TTS.

---

> **Nota de renumeración:** esta Épica 2 sustituye por completo a la versión previa (HU-2.1 a 2.16). Correspondencias que conviene tener a mano: el **clima** pasó de la antigua 2.9 a la **HU-2.6**; el **control de consumo** de la antigua 2.13 a la **HU-2.8**; las **sesiones** se desdoblaron en **HU-2.3** (modelo de datos) y **HU-2.5** (contexto y endpoints); RAG (antiguas 2.5–2.7), caché semántico (2.12) y voz (2.14–2.16) viven ahora en *Diferido a segunda iteración*. Cualquier referencia a la numeración vieja fuera de esta sección está desactualizada.
