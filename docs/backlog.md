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

> **Decisión de arquitectura: Supabase Auth como proveedor de identidad.** El backend **no emite JWT propios**: delega registro y login en Supabase Auth y **valida** los tokens que este emite. Motivos: el login social con Google/Apple que exigen las stores viene resuelto de serie, la seguridad de credenciales (hashing, rotación de refresh tokens, recuperación de contraseña) queda en un servicio probado en vez de código propio, y es coherente con el Postgres de Supabase que ya usamos (HU-1.1). Trade-off asumido: **acoplamiento al proveedor** — migrar de Supabase Auth tendría costo; se mitiga concentrando la integración en el servicio de auth del backend. Consecuencia en el modelo de datos: la tabla local de usuarios pasa a ser un **perfil** que referencia el id de Supabase (`auth.users`), no una fuente de identidad (ver HU-1.10).

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
- La primera migración es una **baseline que ancla el versionado sin crear tablas** (solo aparece la tabla de control `alembic_version`): los modelos de dominio —incluida la tabla de usuarios— corresponden a la HU-1.10, y crearlos aquí habría adelantado ese diseño.
- La estrategia de migración en producción (manual desde local; por qué no está automatizada en el plan free de Render) está documentada en `docs/deploy.md`, y los comandos del día a día en el README del backend.

> **Nota:** la tabla de usuarios y su migración llegan con la HU-1.10 (modelos de dominio).

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
- La contraseña **no aparece** en las respuestas de error de validación (handler propio en `app/core/errors.py` que elimina el campo `input` de errores sobre campos sensibles; se verificó que `SecretStr` por sí solo no lo evitaba).
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

> **Deuda técnica (infra de tests):** la suite emite 4 warnings de *teardown* de aiosqlite (engines de SQLite async que los tests de registro no cierran; solo afloran al correr el **conjunto completo**, por timing del GC). **No son fallos** y el CI no los trata como error, pero conviene una limpieza más adelante: cerrar los engines explícitamente en los fixtures/ayudantes de test (p. ej. un fixture que haga `engine.dispose()`). No es urgente ni bloquea nada.

---

### HU-1.5 — Renovación de sesión
*Como* usuario, *quiero* renovar mi sesión sin volver a loguearme, *para* una experiencia fluida sobre todo en móvil.

**Criterios de aceptación:**
- El refresh y la **rotación** de tokens son responsabilidad de Supabase (y de su SDK en los clientes web/móvil); el backend **no** implementa lógica propia de refresh ni de rotación.
- El flujo queda documentado: cómo renuevan sesión los clientes contra Supabase.
- Solo si aporta a los clientes, se expone un `POST /v1/auth/refresh` que **delega** en Supabase; en ese caso, refresh token inválido o expirado responde `401` y hay tests con el cliente mockeado.

**Tareas técnicas:** documentar el flujo de refresh de Supabase · decidir si se expone un endpoint de refresh delegado (y si sí: endpoint + tests con mock).

---

### HU-1.6 — Middleware de autenticación (validación del JWT de Supabase)
*Como* sistema, *quiero* proteger rutas que requieren sesión, *para* que solo usuarios autenticados accedan a recursos privados.

**Criterios de aceptación:**
- Existe una dependencia `get_current_user` que **valida el JWT emitido por Supabase** (verificación de firma y expiración) y resuelve el **perfil local** a partir del id que trae el token.
- Rutas protegidas sin token o con token inválido/expirado responden `401`.
- El `user_id` y el plan quedan disponibles en el contexto del request.
- Tests con tokens de prueba, sin depender de Supabase real.

**Tareas técnicas:** dependency de auth (verificación de firma y expiración del JWT de Supabase) · resolución del perfil local · manejo de token expirado/inválido · tests con tokens de prueba · marcar rutas protegidas.

---

### HU-1.7 — Rate limiting por plan
*Como* operador del producto, *quiero* limitar peticiones según el plan del usuario, *para* controlar costos y habilitar el freemium.

**Criterios de aceptación:**
- Rate limiting aplicado por usuario, con límites distintos según plan (free vs pago).
- Excederse responde `429` con mensaje claro y cabecera de cuándo reintentar.
- El contador es consistente aunque haya varios workers (estado compartido, no en memoria local).
- Test verifica que el límite se respeta y se resetea.

**Tareas técnicas:** elegir backend de estado (Redis serverless tipo Upstash, o Supabase) · integrar slowapi o equivalente · límites por plan en config · tests.

> Nota: arranca con límites simples por nº de requests. El control de **tokens/voz** del agente irá en la Épica 2, apoyado en estos cimientos.

---

### HU-1.8 — Manejo centralizado de errores
*Como* consumidor de la API, *quiero* errores consistentes y predecibles, *para* manejarlos bien en web y móvil.

**Criterios de aceptación:**
- Existe un formato único de error (código, mensaje, detalle opcional).
- Excepciones no controladas devuelven `500` con un id de error para rastrear en logs, sin filtrar stack traces al cliente.
- Errores de validación (`422`), auth (`401/403`), no encontrado (`404`) y rate limit (`429`) siguen el formato único.
- Test verifica el formato en al menos dos tipos de error.

**Tareas técnicas:** exception handlers globales · modelo de error · mapping de excepciones comunes · tests.

---

### HU-1.9 — Estructura de API versionada `/v1`
*Como* equipo, *quiero* versionar la API desde el inicio, *para* poder evolucionar sin romper clientes existentes (web/móvil).

**Criterios de aceptación:**
- Todos los endpoints cuelgan de `/v1`.
- La documentación automática (OpenAPI/Swagger) está disponible y refleja `/v1`.
- La estructura de routers está organizada por dominio (`auth`, `users`, …).
- El cliente compartido apunta a `/v1`.

**Tareas técnicas:** router raíz `/v1` · organización de routers · habilitar docs OpenAPI · wiring del cliente compartido.

> **Nota (estado real):** dos criterios YA se cumplen desde la Épica 0 — todos los endpoints cuelgan de `/v1` (HU-0.4) y el cliente compartido apunta a `/v1` (HU-0.7). Lo **pendiente** de esta HU es: organizar los routers por dominio (`auth`, `users`, …) y habilitar/documentar las docs OpenAPI. No duplicar el trabajo ya hecho.

---

### HU-1.10 — Modelo de usuario y perfil
*Como* usuario, *quiero* tener un perfil con mis datos y preferencias de viaje, *para* que el agente me dé respuestas personalizadas más adelante.

**Criterios de aceptación:**
- Modelo de **perfil** de usuario con: id (el de Supabase `auth.users`, que lo referencia como clave), email, plan, fecha de creación, preferencias (json). No es fuente de identidad ni almacena contraseñas: eso vive en Supabase Auth.
- `GET /v1/users/me` devuelve el perfil del usuario autenticado.
- `PATCH /v1/users/me` actualiza preferencias con validación.
- Migración Alembic asociada.
- Test cubre lectura y actualización del perfil.

**Tareas técnicas:** modelo SQLAlchemy · schema Pydantic · endpoints `me` · migración · tests · actualizar cliente compartido.

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

> **Ya adelantado (HU-1.3b):** el **logging básico ya está resuelto** — `app/core/logging.py` (`configure_logging`, llamado desde `create_app`) enruta los loggers `app.*` a **stdout** con formato consistente y sin filtrar secretos, así que los diagnósticos de la app son visibles junto a los de uvicorn. **Pendiente de esta HU:** el logging **estructurado** (JSON), el **request id** y la **correlación** entre la línea de entrada/salida de cada request y el id de error de la HU-1.8.

---

## Cómo arrancamos la Épica 1

- **Orden sugerido** (de `backlog-full.md`): empezar por **HU-1.1 → 1.2** (base de datos y migraciones) **antes de auth**; luego 1.3 → 1.4 → 1.5 → 1.6 (auth completa), y de ahí 1.7–1.12.
- **Decisiones que se resuelven en el camino (no bloquean):** backend de estado para rate limiting (Redis serverless tipo Upstash, o Supabase) — necesaria recién en la HU-1.7.
- **Siguiente épica:** cuando las 12 HU estén *Done*, añadimos la Épica 2 (El agente) a este documento.
