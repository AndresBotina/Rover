# Rover — Backlog inicial

> Documento de trabajo para convertir en Issues de GitHub. Cubre la metodología, la Definition of Done, el mapa de épicas y el desglose detallado de las **Épicas 0 y 1** (las que arrancas ya). Las demás épicas quedan listadas como roadmap.

---

## Cómo usar este documento

**Jerarquía de tres niveles:**

- **Épica** — bloque grande de valor. Es una *milestone* o una *label* en GitHub.
- **Historia de Usuario (HU)** — porción demostrable y verificable. Es un *Issue*.
- **Tarea técnica** — paso concreto para completar la HU. Es un checklist dentro del Issue (o sub-issues si prefieres).

**Formato de cada HU:** "Como [rol], quiero [acción], para [beneficio]" + criterios de aceptación verificables + tareas técnicas. Una HU **no está hecha** si no trae sus pruebas (ver DoD).

**Tablero (GitHub Projects):** `Backlog → En progreso → En revisión → Done`.

**Sprints:** úsalos solo como *timeboxes* de foco (ej. 2 semanas, eliges 4–6 HU, no tocas nada fuera de ese alcance). Nada de estimación en story points ni dailies contigo mismo.

**Convención de labels sugerida:**

- `epica:0-fundacion`, `epica:1-backend`, … (una por épica)
- `tipo:hu`, `tipo:bug`, `tipo:tech-debt`
- `prioridad:alta | media | baja`
- `bloqueante` (cuando algo bloquea otra HU)

**Convención de ramas y PRs:** una rama por HU (`feat/hu-1.3-registro-usuario`), un PR por HU enlazado al Issue con `Closes #N`. Aunque te revises tú mismo, el PR es obligatorio.

---

## Definition of Done (global — aplica a TODA historia, sin excepción)

Una HU está **Done** solo cuando:

- [ ] El código pasa el **linter** y el **type-check** sin errores.
- [ ] Todas las **pruebas** (unitarias e integración relevantes) están en verde.
- [ ] Se cumplen **todos los criterios de aceptación** de la HU.
- [ ] Si tocó el esquema de base de datos: la **migración Alembic** está escrita y aplicada.
- [ ] Si cambió un endpoint o un tipo: el **paquete compartido** (cliente API tipado) está actualizado.
- [ ] El cambio pasó por un **Pull Request** revisado (aunque sea por ti mismo), con su diff leído en frío.
- [ ] El **CI está verde** antes de hacer merge a `main`.
- [ ] No se introdujeron **secretos** en el repo ni valores hardcodeados que deban ir en config.

---

## Mapa de épicas (roadmap)

| Épica | Nombre | Objetivo | Estado |
|-------|--------|----------|--------|
| **0** | Fundación | Monorepo, tooling, CI/CD desplegando desde el día uno | **Arranca ya** |
| **1** | Backend core | API `/v1`, conexión async a Supabase, Alembic, auth JWT, rate limiting, errores, config | **Arranca ya** |
| **2** | El agente | Conversación con memoria, streaming SSE, sesiones y tool-calling con datos en vivo (clima primero). RAG, caché semántico y voz **diferidos con disparador** | **En curso** |
| **3** | Web | Next.js con auth, chat con streaming, pricing | Después de validar agente |
| **4** | Mobile | Expo reusando la capa compartida | Después de la web |
| **5** | Monetización | Stripe / Play Billing / Apple IAP, lógica freemium | Diferida hasta demanda real |
| **6** | Operaciones / Automatización | n8n y/o cron jobs para tareas internas (avisos, onboarding, sync) — **nunca en el camino de la petición del usuario** | Solo cuando aparezca una automatización real |

**Decisiones que se resuelven en el camino (no bloquean):** PaaS específico (Railway / Render / Fly.io), proveedor de TTS *(cuando la voz se retome — ver diferidos de la Épica 2)*, gestor del monorepo (Turborepo vs pnpm workspaces a secas). La orquestación del agente **ya está decidida**: tool-calling directo, sin LangGraph (Épica 2).

---

# ÉPICA 0 — Fundación

**Objetivo:** que todo el proyecto nazca con calidad: monorepo estructurado, linting, type-checking y un pipeline de CI/CD que despliega a un PaaS *desde el primer día*. Esta épica va primero porque desbloquea la disciplina de todo lo demás.

### HU-0.1 — Inicializar el monorepo
*Como* desarrollador, *quiero* un monorepo con espacios para backend, web, mobile y paquetes compartidos, *para* compartir lógica entre plataformas sin duplicar código.

**Criterios de aceptación:**
- Existe la estructura `apps/` (backend, web, mobile) y `packages/` (shared).
- El gestor de workspaces está configurado y `install` desde la raíz instala todo.
- Un `README` raíz documenta la estructura y los comandos básicos.
- Cada workspace puede ejecutarse de forma independiente.

**Tareas técnicas:** elegir pnpm workspaces (o Turborepo) · estructura de carpetas · `package.json` raíz con scripts · README inicial · `.gitignore` completo.

---

### HU-0.2 — Linting y formateo
*Como* desarrollador, *quiero* linting y formateo automáticos, *para* mantener consistencia y atrapar errores antes de ejecutar.

**Criterios de aceptación:**
- Ruff (backend Python) y ESLint + Prettier (TS) configurados.
- `lint` corre desde la raíz sobre todos los workspaces.
- Existe configuración de pre-commit que bloquea commits con errores de lint.
- Las reglas están documentadas y son las mismas en local y en CI.

**Tareas técnicas:** configurar Ruff · configurar ESLint + Prettier · pre-commit hooks (husky/lefthook o pre-commit de Python) · script `lint` en la raíz.

---

### HU-0.3 — Type-checking estricto
*Como* desarrollador, *quiero* chequeo de tipos estricto, *para* que los errores de tipos no lleguen a runtime.

**Criterios de aceptación:**
- `mypy` (o pyright) en backend en modo estricto, `tsc --noEmit` en TS.
- `type-check` corre desde la raíz.
- Cero errores de tipos en el estado base del repo.

**Tareas técnicas:** configurar mypy/pyright · `tsconfig` estricto · script `type-check`.

---

### HU-0.4 — Esqueleto del backend desplegable (healthcheck)
*Como* desarrollador, *quiero* un FastAPI mínimo con un endpoint de salud, *para* tener algo real que desplegar desde el día uno.

**Criterios de aceptación:**
- `GET /health` responde `200` con `{"status": "ok"}` y versión.
- La app arranca con un comando documentado y corre en contenedor.
- Existe `Dockerfile` y `docker-compose.yml` para desarrollo local.
- Hay al menos un test que verifica el healthcheck.

**Tareas técnicas:** scaffold FastAPI · endpoint `/health` · Dockerfile · docker-compose · primer test.

---

### HU-0.5 — Pipeline de CI (calidad en cada PR)
*Como* desarrollador, *quiero* que cada PR corra lint, type-check y tests, *para* que nada roto llegue a `main`.

**Criterios de aceptación:**
- GitHub Action que en cada PR corre `lint` + `type-check` + `test`.
- El merge se **bloquea** si cualquier paso falla (branch protection en `main`).
- El pipeline corre en menos de un tiempo razonable (cachea dependencias).
- El estado del check aparece visible en el PR.

**Tareas técnicas:** workflow de CI en `.github/workflows/` · cache de deps · branch protection rule en `main` · badge de estado en README.

---

### HU-0.6 — Pipeline de CD (deploy en merge a main)
*Como* desarrollador, *quiero* que un merge a `main` despliegue solo al PaaS, *para* no integrar la infraestructura al final del proyecto.

**Criterios de aceptación:**
- Merge a `main` dispara un deploy automático del backend al PaaS elegido.
- El deploy usa la imagen contenedorizada de la HU-0.4.
- Si el deploy falla, hay notificación visible y `main` no queda en estado roto silencioso.
- La URL desplegada responde el `/health` correctamente tras el deploy.

**Tareas técnicas:** elegir PaaS (Railway / Render / Fly.io) · workflow de CD · configurar secretos del deploy en GitHub · verificación post-deploy del healthcheck.

---

### HU-0.7 — Paquete compartido de tipos y cliente API
*Como* desarrollador, *quiero* un paquete compartido con los tipos de datos y el cliente HTTP tipado, *para* que web y mobile consuman la misma API sin duplicar lógica.

**Criterios de aceptación:**
- Existe `packages/shared` con tipos y un cliente API tipado importable desde web y mobile.
- Un cambio en un tipo se refleja en ambos consumidores sin copiar y pegar.
- El paquete está cubierto por type-check en el CI.

**Tareas técnicas:** scaffold `packages/shared` · definir tipos base · cliente HTTP tipado · wiring en los workspaces consumidores.

---

### HU-0.8 — Configuración por ambiente y manejo de secretos
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

# ÉPICA 2 — El agente

**Objetivo:** el corazón del producto. Un agente que **conversa con memoria, en streaming, y consulta datos en vivo** — empezando por el clima. Text-first, con personalidad en el system prompt y un cerebro económico (DeepSeek V4 Flash) tras una abstracción de proveedor. Se apoya en toda la Épica 1: base async, auth, rate limiting, contrato único de error y logs correlacionables.

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

### HU-2.1 — Integración con el LLM y abstracción de proveedor
*Como* sistema, *quiero* hablar con el LLM a través de una capa que abstraiga el proveedor, *para* cambiar de modelo sin reescribir el agente.

**Criterios de aceptación:**
- Existe una interfaz de proveedor con una implementación para **DeepSeek V4 Flash** sobre su endpoint OpenAI-compatible.
- La API key es un **secreto**: `SecretStr` en config, dentro de `_REQUIRED_IN_PRODUCTION`, nunca en el repo ni en los logs.
- Modelo, proveedor y parámetros de generación salen de **config**, no hardcodeados.
- El *seam* de **selección por capacidad** está documentado en el código: dónde entraría un segundo modelo (visión) sin tocar el agente. La selección por **dificultad no se implementa**.
- La interfaz soporta **streaming**, no solo respuesta completa.
- El system prompt se envía como **prefijo estable**, para aprovechar el caché automático del proveedor.
- **Instrumentación de uso y calidad** en cada llamada: tokens de entrada/salida, latencia, modelo usado y si hubo *cache hit*, sobre los logs estructurados de la HU-1.12. Es la **semilla del router por dificultad**: sin estos datos, ese router se diseñaría a ciegas.
- Tests con el proveedor mockeado que verifican el contrato de la capa, **incluido el camino de streaming**.

**Tareas técnicas:** `services/agent/llm.py` con la interfaz de proveedor · cliente DeepSeek (OpenAI-compatible) · key como `SecretStr` en `_REQUIRED_IN_PRODUCTION` · modelo y parámetros en config · streaming en la interfaz · campos de uso/latencia/modelo/cache-hit en el log estructurado · mocks de respuesta completa y de streaming.

---

### HU-2.2 — Personalidad vía system prompt
*Como* producto, *quiero* la personalidad de Rover en un system prompt versionado, *para* iterarla rápido y mantenerla portable entre modelos (sin fine-tuning).

**Criterios de aceptación:**
- El system prompt vive **en el repo, versionado**: ni en base de datos ni incrustado en el endpoint.
- Cambiar la personalidad es **editar un archivo**, sin tocar lógica.
- Se inyecta como **prefijo estable**, primero, en cada llamada (caché-friendly, coherente con la HU-2.1).
- Existe un test que verifica que el prompt viaja en la petición al LLM.

**Tareas técnicas:** archivo de prompt versionado · carga en el servicio del agente · test de inclusión.

---

### HU-2.3 — Modelo de datos de conversaciones
*Como* usuario, *quiero* que mis conversaciones queden guardadas, *para* retomarlas después y que el agente tenga de dónde recordar.

**Criterios de aceptación:**
- Tabla `conversations`: id, `user_id`, título, timestamps de creación/actualización y **soft-delete** (`deleted_at`).
- Tabla `messages`: id, `conversation_id`, rol, contenido, **pasos intermedios de tool-calling en JSONB**, orden dentro de la conversación y timestamp.
- El **título** se deriva de forma simple del primer mensaje; nada de generarlo con el modelo por ahora.
- El `user_id` sale **del token** (HU-1.6), nunca del cuerpo de la petición.
- Migración Alembic asociada; modelos en estilo **SQLAlchemy 2.0**, como el resto del backend.
- Tests **sin base de datos real**, con el patrón limpio de fixtures de la HU-1.13 (una sola base y un solo event loop por test).

**Tareas técnicas:** modelos `Conversation` y `Message` · índices por `user_id` y por orden dentro de la conversación · migración Alembic · tests sobre el patrón de la HU-1.13.

---

### HU-2.4 — Endpoint de chat con streaming SSE (conversación pura)
*Como* usuario, *quiero* ver la respuesta aparecer token a token, *para* una experiencia fluida en vez de una espera en blanco.

**Criterios de aceptación:**
- `POST /v1/chat` responde con **Server-Sent Events**, haciendo streaming de la respuesta del modelo.
- La ruta está protegida por **auth** (HU-1.6) y sujeta a **rate limiting** (HU-1.7).
- El mensaje del usuario y la respuesta del agente **se persisten** (HU-2.3).
- Un fallo a mitad de stream emite un **evento de error con el contrato de la HU-1.8** adaptado a SSE (mismo catálogo de `code`), no un corte mudo.
- La **configuración anti-buffering en Render** queda documentada: un proxy que acumule la respuesta anula el streaming aunque el backend lo haga bien.
- `@rover/shared` expone el **consumo tipado del SSE**, para que las Épicas 3 y 4 no lo improvisen.
- Tests de integración: llega un stream con contenido, y un fallo a mitad emite el evento de error.

**Tareas técnicas:** endpoint SSE · puente del stream del LLM a SSE · evento de error en formato HU-1.8 · nota de despliegue anti-buffering · consumo tipado del SSE en `@rover/shared` · tests.

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

---

# ÉPICA 3 — Web (Next.js)

**Objetivo:** la web que valida la idea con usuarios reales. Next.js sobre Vercel, consumiendo la misma API y la capa compartida del monorepo. Empieza después de tener el agente funcionando.

### HU-3.1 — Scaffold Next.js integrado al monorepo
*Como* desarrollador, *quiero* la app web en el monorepo reusando el paquete compartido, *para* no duplicar tipos ni cliente API.

**Criterios de aceptación:** Next.js 15 (App Router) en `apps/web` · importa `packages/shared` · corre en dev y build sin errores · entra en el CI (lint + type-check).

**Tareas técnicas:** scaffold Next.js · wiring del paquete compartido · scripts · CI.

---

### HU-3.2 — Flujo de autenticación en web
*Como* usuario web, *quiero* registrarme, iniciar sesión y mantener sesión, *para* usar la app de forma segura.

**Criterios de aceptación:** pantallas de registro/login · manejo de JWT + refresh automático · rutas protegidas redirigen a login · errores de auth mostrados con claridad.

**Tareas técnicas:** páginas auth · integración con endpoints `/v1/auth/*` · manejo de tokens · guard de rutas.

---

### HU-3.3 — Interfaz de chat con streaming
*Como* usuario, *quiero* chatear con el agente viendo la respuesta en tiempo real, *para* una experiencia fluida.

**Criterios de aceptación:** UI de chat consumiendo el SSE de `/v1/chat` · render token a token · historial de conversación visible · estados de carga y error.

**Tareas técnicas:** componente de chat · cliente SSE · render incremental · manejo de estados.

---

### HU-3.4 — Modo voz opcional en web
*Como* usuario, *quiero* poder hablar y escuchar en la web, *para* usar el agente en modo conversación.

**Criterios de aceptación:** botón de voz que graba y envía audio (STT) · reproducción del audio de respuesta (URL) · el modo texto sigue intacto · degradación elegante si el navegador no soporta micrófono.

**Tareas técnicas:** captura de audio · integración STT/TTS endpoints · player de audio · fallback.

---

### HU-3.5 — Página de pricing
*Como* visitante, *quiero* ver los planes y qué incluye cada uno, *para* decidir si me suscribo.

**Criterios de aceptación:** página pública con planes (free vs pago) y límites claros · CTA de registro/upgrade · renderizada con SSR para SEO.

**Tareas técnicas:** página de pricing · contenido de planes · SSR/SEO.

---

### HU-3.6 — Perfil y preferencias
*Como* usuario, *quiero* editar mis preferencias de viaje, *para* recibir respuestas personalizadas.

**Criterios de aceptación:** pantalla de perfil consumiendo `/v1/users/me` · edición de preferencias con validación · feedback de guardado.

**Tareas técnicas:** página de perfil · formularios · integración endpoints `me`.

---

### HU-3.7 — Manejo de cuotas y límites en la UI
*Como* usuario, *quiero* entender cuánto me queda de mi plan, *para* no chocar con un límite sin aviso.

**Criterios de aceptación:** indicador de cuota restante · mensaje claro y CTA de upgrade al agotar · sin errores crípticos.

**Tareas técnicas:** indicador de cuota · manejo del `429`/mensaje de límite · CTA de upgrade.

---

# ÉPICA 4 — Mobile (Expo)

**Objetivo:** la app móvil reusando toda la capa compartida. Mismo backend, misma API; el móvil es "otro cliente". Empieza cuando la web haya validado la idea.

### HU-4.1 — Scaffold Expo integrado al monorepo
**Criterios de aceptación:** Expo (React Native) en `apps/mobile` · importa `packages/shared` · corre en simulador iOS y Android · entra en el CI de type-check/lint.
**Tareas técnicas:** scaffold Expo Router · wiring del paquete compartido · scripts · CI.

### HU-4.2 — Autenticación nativa (incluye login social)
**Criterios de aceptación:** registro/login funcionando · login social Google y Apple (requerido por las stores) · manejo de JWT + refresh · sesión persistente entre aperturas de la app.
**Tareas técnicas:** flujos de auth · login social · almacenamiento seguro de tokens · refresh.

### HU-4.3 — Chat con streaming en móvil
**Criterios de aceptación:** UI de chat con streaming · historial · estados de carga/error · rendimiento fluido en listas largas.
**Tareas técnicas:** componente de chat · cliente SSE en RN · render incremental.

### HU-4.4 — Modo voz nativo
**Criterios de aceptación:** grabación de audio nativa (STT) · reproducción del audio de respuesta · permisos de micrófono manejados · modo texto intacto.
**Tareas técnicas:** captura de audio nativa · permisos · integración STT/TTS · player.

### HU-4.5 — Animaciones y sensación premium
**Criterios de aceptación:** transiciones y gestos fluidos con Reanimated + Gesture Handler · 60fps en interacciones clave · se siente nativo.
**Tareas técnicas:** Reanimated · Gesture Handler · animaciones de las pantallas clave.

### HU-4.6 — Builds y distribución a stores
**Criterios de aceptación:** builds de producción con EAS · publicación en Play Store y App Store · proceso documentado.
**Tareas técnicas:** configurar EAS Build · perfiles de build · submission a stores · documentar.

---

# ÉPICA 5 — Monetización (diferida)

**Objetivo:** convertir el freemium en ingresos. **No empezar hasta que haya demanda real.** Es por sí sola un proyecto de varias semanas por la sincronización entre tres facturadores.

### HU-5.1 — Modelo de planes y suscripciones en backend
**Criterios de aceptación:** modelo de planes y estado de suscripción por usuario · el plan determina cuotas (Épica 2) y rate limits (Épica 1) · migración asociada.
**Tareas técnicas:** modelos de plan/suscripción · wiring con cuotas y rate limiting · migración.

### HU-5.2 — Pagos web (Stripe)
**Criterios de aceptación:** checkout de Stripe · webhooks que actualizan el estado de suscripción · manejo de éxito/fallo/cancelación.
**Tareas técnicas:** integración Stripe · webhooks · actualización de entitlements.

### HU-5.3 — Google Play Billing
**Criterios de aceptación:** compra in-app en Android · verificación de la compra en backend · entitlement actualizado.
**Tareas técnicas:** integración Play Billing · verificación server-side · sync.

### HU-5.4 — Apple IAP
**Criterios de aceptación:** compra in-app en iOS · verificación de recibo en backend · entitlement actualizado.
**Tareas técnicas:** integración StoreKit/IAP · verificación server-side · sync.

### HU-5.5 — Sincronización de entitlements entre facturadores
**Criterios de aceptación:** un usuario tiene un único estado de suscripción coherente sin importar dónde pagó · cambios (renovación, cancelación, reembolso) se reflejan en su acceso.
**Tareas técnicas:** capa única de entitlements · reconciliación entre Stripe/Play/Apple · manejo de estados.

---

# ÉPICA 6 — Operaciones / Automatización interna

**Objetivo:** lo que mantiene el producto sano por detrás. **Nada de esto toca el camino de la petición del usuario.** n8n entra solo cuando aparezca una automatización real que lo justifique; si el flujo es crítico o necesita tests, va en código.

### HU-6.1 — Monitoreo y alertas de fallos
**Criterios de aceptación:** alertas cuando el backend falla o el deploy se rompe · errores `500` rastreables por su id (HU-1.8/1.12).
**Tareas técnicas:** integrar monitoreo de errores · alertas · dashboards básicos.

### HU-6.2 — Ambiente de staging
**Criterios de aceptación:** un ambiente de staging separado de producción · el CD despliega a staging antes que a prod · datos de prueba aislados.
**Tareas técnicas:** ambiente staging en el PaaS · pipeline de CD a staging · config separada.

### HU-6.3 — Correos de onboarding y operativos
**Criterios de aceptación:** correo de bienvenida al registro · avisos operativos según se definan · no en el camino de la petición.
**Tareas técnicas:** integración de email · plantillas · disparadores (cron job o n8n).

### HU-6.4 — Automatizaciones internas (n8n, cuando aplique)
**Criterios de aceptación:** solo se crea cuando hay una automatización operativa real · documentada · sin lógica crítica de producto escondida en un flujo visual.
**Tareas técnicas:** evaluar n8n vs cron+código caso por caso · implementar la automatización concreta.

---

## Notas de cierre

- **Orden sugerido de arranque:** HU-0.1 → 0.2 → 0.3 → 0.4 → 0.5 → 0.6 (ya tienes deploy vivo) → 0.7 → 0.8. Luego Épica 1, empezando por 1.1 → 1.2 (base de datos y migraciones) antes de auth.
- **Dependencias entre épicas:** la Épica 2 (agente) necesita la base de datos, la auth y el rate limiting de la Épica 1. La 3 (web) necesita el agente funcionando. La 4 (móvil) reusa la capa compartida y conviene tras validar con la web. La 5 (pagos) se apoya en planes/cuotas y se difiere hasta tener demanda. La 6 (operaciones) entra cuando haga falta, nunca preventivamente.
- **Dentro de la Épica 2, secuencia sugerida:** 2.1 → 2.2 (cerebro y personalidad) → 2.3 → 2.4 (chat en vivo persistido) → 2.5 (memoria multi-turno) → 2.6 (tool-calling con el clima como referencia) → 2.7 (más tools) → 2.8 (control de consumo). RAG, caché semántico, router por dificultad y voz **no entran en la v1**: viven en *Diferido a segunda iteración*, cada uno con su disparador.
- **Lo que se decide en el camino (no bloquea):** PaaS específico, proveedores de STT/TTS *(solo si se retoma la voz)*, y la elección final de Turborepo vs pnpm workspaces.
- **n8n:** vive solo en la Épica 6 y nunca en el flujo de chat ni en el camino de la petición del usuario.
