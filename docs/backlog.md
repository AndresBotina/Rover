# Rover — Backlog activo

> **Documento de trabajo vivo.** Crece **épica por épica**: aquí solo se detalla la épica en curso. Cuando cerremos todas sus HU (cumpliendo la Definition of Done), añadimos la siguiente. El panorama completo de las 7 épicas vive en `backlog-full.md` como referencia.
>
> **Épica en curso: 0 — Fundación.**

---

## Cómo usar este documento

- **Jerarquía:** Épica → Historia de Usuario (HU = un Issue) → Tareas técnicas (checklist dentro del Issue).
- **Tablero (GitHub Projects):** `Backlog → En progreso → En revisión → Done`.
- **Ramas y PRs:** una rama por HU (`feat/hu-0.1-monorepo`), un PR por HU enlazado al Issue con `Closes #N`. El PR es obligatorio aunque te revises tú mismo.
- **Labels sugeridas:** `epica:0-fundacion` · `tipo:hu | bug | tech-debt` · `prioridad:alta | media | baja` · `bloqueante`.
- **Sprints:** solo como *timeboxes* de foco (elige unas pocas HU, no toques nada fuera de ese alcance). Sin story points ni dailies.

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

## Roadmap (panorama — detalle se añade épica por épica)

| Épica | Nombre | Objetivo | Estado |
|-------|--------|----------|--------|
| **0** | Fundación | Monorepo, tooling, CI/CD desplegando desde el día uno | **En curso** |
| 1 | Backend core | API `/v1`, async Supabase, Alembic, auth JWT, rate limiting, errores, config | Pendiente |
| 2 | El agente | RAG + tool-calling, streaming, sesiones, caché semántico, voz opcional (pipeline) | Pendiente |
| 3 | Web | Next.js con auth, chat con streaming, pricing | Pendiente |
| 4 | Mobile | Expo reusando la capa compartida | Pendiente |
| 5 | Monetización | Stripe / Play Billing / Apple IAP, freemium | Diferida |
| 6 | Operaciones | n8n / cron para tareas internas (nunca en el camino de la petición) | Pendiente |

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
- El pipeline corre en un tiempo razonable (cachea dependencias).
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

## Cómo arrancamos la Épica 0

- **Orden sugerido:** HU-0.1 → 0.2 → 0.3 → 0.4 → 0.5 → 0.6 (aquí ya tienes deploy vivo) → 0.7 → 0.8.
- **Dos micro-decisiones a resolver:**
  - **Monorepo** (pnpm workspaces vs Turborepo) → necesaria **ya**, para la HU-0.1.
  - **PaaS** (Railway / Render / Fly.io) → necesaria recién en la HU-0.6, no bloquea el arranque.
- **Siguiente épica:** cuando las 8 HU estén *Done*, añadimos la Épica 1 (Backend core) a este documento.
