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
| **1** | Backend core | API `/v1`, async Supabase, Alembic, auth JWT, rate limiting, errores | **En curso** |
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

### ✅ HU-0.5 — Pipeline de CI (calidad en cada PR)
*Como* desarrollador, *quiero* que cada PR corra lint, type-check y tests, *para* que nada roto llegue a `main`.

**Criterios de aceptación:**
- GitHub Action que en cada PR corre `lint` + `type-check` + `test`.
- El merge se **bloquea** si cualquier paso falla (branch protection en `main`).
- El pipeline corre en un tiempo razonable (cachea dependencias).
- El estado del check aparece visible en el PR.

**Tareas técnicas:** workflow de CI en `.github/workflows/` · cache de deps · branch protection rule en `main` · badge de estado en README.

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

**Objetivo:** el backend permanente y bien construido. API versionada, conexión async a Supabase, migraciones, autenticación con JWT, rate limiting por plan, manejo de errores centralizado y observabilidad básica. Esto no se bota cuando crezcas; solo le pones más máquinas detrás.

### HU-1.1 — Conexión async a base de datos
*Como* sistema, *quiero* conectarme a Supabase Postgres de forma asíncrona, *para* no bloquear el event loop bajo carga.

**Criterios de aceptación:**
- SQLAlchemy 2.0 async + asyncpg conectando a Supabase Postgres.
- Pool de conexiones configurado y cerrado limpiamente al apagar la app.
- Existe una dependencia de FastAPI que entrega sesiones de DB por request.
- Un test de integración verifica que se puede leer/escribir contra una DB de prueba.

**Tareas técnicas:** `core/database.py` (engine async + sessionmaker) · dependency `get_db` · configuración del pool · test de conexión.

---

### HU-1.2 — Alembic y primera migración
*Como* desarrollador, *quiero* migraciones versionadas, *para* controlar el esquema en producción sin sorpresas.

**Criterios de aceptación:**
- Alembic configurado contra el mismo engine async.
- `alembic upgrade head` y `downgrade` funcionan en local.
- La primera migración crea el esquema base (al menos la tabla de usuarios).
- El proceso de migración está documentado y se puede correr en el deploy.

**Tareas técnicas:** init de Alembic · configurar `env.py` para async · primera migración · documentar comando de migración en CD.

---

### HU-1.3 — Registro de usuario
*Como* viajero nuevo, *quiero* crear una cuenta con email y contraseña, *para* guardar mis conversaciones y preferencias.

**Criterios de aceptación:**
- `POST /v1/auth/register` crea el usuario vía Supabase Auth.
- La contraseña nunca se almacena en texto plano (lo maneja Supabase).
- Email ya existente responde `409` con mensaje claro, no `500`.
- Email inválido o contraseña débil responde `422` con detalle.
- En éxito devuelve JWT + refresh token.
- Test de integración cubre el caso feliz y los dos casos de error.

**Tareas técnicas:** schema Pydantic request/response · servicio de auth (integración Supabase) · endpoint · tests · actualizar cliente compartido.

---

### HU-1.4 — Login y emisión de JWT
*Como* usuario registrado, *quiero* iniciar sesión, *para* acceder a mi cuenta de forma segura.

**Criterios de aceptación:**
- `POST /v1/auth/login` valida credenciales y devuelve JWT + refresh token.
- Credenciales inválidas responden `401` sin revelar si el email existe.
- El JWT incluye el `user_id` y el plan del usuario en los claims.
- Test cubre login exitoso y fallido.

**Tareas técnicas:** schema de login · servicio de login · firma/validación de JWT en `core/security.py` · endpoint · tests.

---

### HU-1.5 — Renovación de sesión (refresh token)
*Como* usuario, *quiero* renovar mi sesión sin volver a loguearme, *para* una experiencia fluida sobre todo en móvil.

**Criterios de aceptación:**
- `POST /v1/auth/refresh` emite un nuevo JWT a partir de un refresh token válido.
- Refresh token inválido o expirado responde `401`.
- El refresh rota el token (el anterior queda inutilizable).
- Test cubre refresh válido e inválido.

**Tareas técnicas:** lógica de refresh + rotación · endpoint · tests.

---

### HU-1.6 — Middleware de autenticación
*Como* sistema, *quiero* proteger rutas que requieren sesión, *para* que solo usuarios autenticados accedan a recursos privados.

**Criterios de aceptación:**
- Existe una dependencia `get_current_user` que valida el JWT y entrega el usuario.
- Rutas protegidas sin token o con token inválido responden `401`.
- El `user_id` y el plan quedan disponibles en el contexto del request.
- Test verifica acceso permitido y denegado.

**Tareas técnicas:** dependency de auth · manejo de token expirado/ inválido · tests · marcar rutas protegidas.

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
- Modelo de usuario con: id, email, plan, fecha de creación, preferencias (json).
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

---

## Cómo arrancamos la Épica 1

- **Orden sugerido** (de `backlog-full.md`): empezar por **HU-1.1 → 1.2** (base de datos y migraciones) **antes de auth**; luego 1.3 → 1.4 → 1.5 → 1.6 (auth completa), y de ahí 1.7–1.12.
- **Decisiones que se resuelven en el camino (no bloquean):** backend de estado para rate limiting (Redis serverless tipo Upstash, o Supabase) — necesaria recién en la HU-1.7.
- **Siguiente épica:** cuando las 12 HU estén *Done*, añadimos la Épica 2 (El agente) a este documento.
