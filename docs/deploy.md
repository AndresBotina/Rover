# Deploy a Render

El backend (`apps/backend`) se despliega en [Render](https://render.com) como
**web service Docker** en el plan **free**, definido como infraestructura como
código en [`render.yaml`](../render.yaml) (raíz del repo).

## Qué define `render.yaml`

- **Servicio**: `rover-backend`, construido desde `apps/backend/Dockerfile`
  (contexto `apps/backend`).
- **Deploy automático**: cada push a `develop` dispara un deploy
  (`autoDeploy: true`).
- **Healthcheck**: Render consulta `GET /v1/health` y solo marca el deploy como
  sano (y enruta tráfico) cuando responde `200`.
- **Entorno**: `ROVER_ENV=production`. El puerto **no** se configura: Render lo
  inyecta vía la variable `PORT` y el contenedor lo respeta
  (`--port ${PORT:-8000}`; en local cae a `8000`).
- **Región**: `virginia` (US East), la más cercana a Latinoamérica en el plan
  free; se cambia editando el campo `region`.

## Primer deploy (paso manual, una sola vez)

En el panel de Render: **New → Blueprint**, conectar el repo y seleccionar la
rama `develop`. Render lee `render.yaml` y crea el servicio; los pushes
posteriores a `develop` despliegan solos.

> **NOTA — plan free**: el servicio **se duerme tras ~15 minutos de
> inactividad**. La primera petición después de dormir sufre un arranque en
> frío (puede tardar del orden de un minuto en responder). Es esperado en el
> plan free; no es un fallo del deploy.

## Migraciones de base de datos en producción (estrategia, HU-1.2)

Por ahora las migraciones **NO están automatizadas** en el deploy; se aplican
**a mano desde local**, antes de pushear código que dependa del esquema nuevo:

```bash
cd apps/backend
uv run alembic upgrade head   # usa ROVER_DATABASE_URL del .env (Supabase)
```

Por qué así y no automatizado todavía:

- El plan **free** de Render no tiene `preDeployCommand` (el gancho natural
  para migrar antes de arrancar la app; es de planes de pago).
- Migrar en el arranque del contenedor (`alembic upgrade && uvicorn…`) es
  frágil en free: cada arranque en frío re-ejecuta la migración, y un fallo de
  migración deja el servicio en bucle de reinicio.
- El orden seguro es: **primero** migrar (con cambios compatibles hacia atrás),
  **después** desplegar el código que los usa.

Cuando haya plan de pago o CD propio, el camino recomendado es
`preDeployCommand: uv run alembic upgrade head` en `render.yaml` (o un paso
equivalente en CI antes del deploy).
