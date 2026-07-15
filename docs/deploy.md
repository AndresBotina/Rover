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
