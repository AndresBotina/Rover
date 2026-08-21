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

## Streaming SSE en producción: que nadie bufferee `/v1/chat` (HU-2.4)

`POST /v1/chat` responde en **Server-Sent Events**. El endpoint funciona igual
si algo por el camino lo acumula… pero entonces el usuario recibe la respuesta
**entera y al final**, que es exactamente lo que el streaming existe para
evitar. El fallo es especialmente traicionero porque **en local no se ve**: sin
proxy delante, `uvicorn` entrega los trozos según los produce, y el problema
solo aparece desplegado.

### Lo que ya hace el backend

La respuesta sale con estas cabeceras (`apps/backend/app/api/sse.py`):

| Cabecera | Para qué |
|----------|----------|
| `Content-Type: text/event-stream; charset=utf-8` | marca la respuesta como stream y fija el UTF-8 |
| `Cache-Control: no-cache, no-transform` | `no-cache` para el navegador; **`no-transform`** prohíbe a los intermediarios recomprimir o reempaquetar el cuerpo, que es como un proxy acaba bufferizando sin querer |
| `Connection: keep-alive` | convención de SSE sobre HTTP/1.1 (en HTTP/2 la cabecera no existe y el protocolo ya multiplexa) |
| `X-Accel-Buffering: no` | apaga el buffer de respuesta de **nginx** y de todo lo que lo lleva por dentro |

Además, la app **no monta compresión** (no hay `GZipMiddleware`): comprimir un
stream obliga a llenar un bloque antes de emitir, y eso es buffering con otro
nombre. Si algún día se añade compresión, `/v1/chat` tiene que quedar excluido.

### Render

Render **no bufferiza respuestas en streaming**: su proxy pasa los bytes según
llegan, así que no hay que activar nada en el panel. Lo que sí conviene tener
presente del plan **free**:

- **Arranque en frío**: si el servicio estaba dormido, la primera petición de
  chat tarda lo que tarde el contenedor en levantar *más* lo que tarde el
  modelo en empezar a responder. No es el streaming fallando.
- **Timeout de petición**: una respuesta larga del modelo mantiene la conexión
  abierta varios minutos. Render no corta conexiones activas mientras haya
  tráfico, y el stream lo hay (cada trozo es tráfico); un stream que se quedara
  callado mucho rato sí sería candidato a que alguien lo cortara. Si eso llega
  a pasar, la solución es emitir un **comentario de keep-alive** (`: ping\n\n`)
  cada N segundos desde el generador — el parser de `@rover/shared` ya los
  ignora, así que es un cambio de una línea en el backend y ninguno en los
  clientes.

### Si algún día hay otro proxy delante (nginx, Cloudflare, un balanceador)

Lo que hay que desactivar, por si el `X-Accel-Buffering` no basta:

```nginx
location /v1/chat {
    proxy_pass              http://backend;
    proxy_buffering         off;   # no acumular la respuesta
    proxy_cache             off;
    proxy_read_timeout      300s;  # una respuesta larga tarda minutos
    proxy_http_version      1.1;
    chunked_transfer_encoding on;
}
```

En **Cloudflare**, el proxy naranja bufferiza según el tipo de contenido;
`text/event-stream` está entre los que deja pasar, pero conviene comprobarlo
con el `curl` de abajo antes de darlo por bueno.

### Cómo comprobar que NO se está bufferizando

Contra el entorno desplegado, con un token válido:

```bash
curl -N --no-buffer https://rover-backend.onrender.com/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"cuéntame algo largo sobre Colombia"}'
```

- **Bien**: las líneas `data:` van apareciendo poco a poco durante segundos.
- **Mal**: la terminal se queda quieta y de golpe imprime todo el bloque. Ahí
  hay algo acumulando entre el backend y tú.

`--no-buffer` es imprescindible en la prueba: sin él, el que acumula es el
propio `curl` y el diagnóstico saldría mal por culpa de la herramienta.
