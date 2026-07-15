# @rover/shared — tipos compartidos + cliente API

Paquete TypeScript compartido del monorepo: el lugar ÚNICO donde viven los
tipos de datos de la API y el cliente HTTP tipado. `apps/web` y `apps/mobile`
lo consumen como fuente (sin build) vía `"@rover/shared": "workspace:*"`.

## Estructura

```
src/
├── config.ts            # APP_NAME (marca visible; única fuente de verdad)
├── types/               # tipos de datos, A MANO por ahora
│   └── health.ts        # HealthResponse + type guard de runtime
├── client/
│   ├── config.ts        # base URL configurable (default: http://localhost:8000)
│   ├── client.ts        # ApiClient (fetch nativo) + ApiError
│   └── client.test.ts   # tests con fetch mockeado (node:test)
└── index.ts             # API pública del paquete
```

## Uso

```ts
import { ApiClient, type HealthResponse } from "@rover/shared";

// La base URL la inyecta cada app (NEXT_PUBLIC_API_URL / EXPO_PUBLIC_API_URL);
// sin argumento usa el backend local (http://localhost:8000).
const api = new ApiClient({ baseUrl: process.env.NEXT_PUBLIC_API_URL });
const health: HealthResponse = await api.getHealth(); // GET /v1/health
```

Errores tipados: cualquier fallo (red caída, status no-2xx, cuerpo con forma
inesperada) lanza `ApiError` con `url` y `status` (`null` si no hubo respuesta).
`getHealth()` valida la forma del JSON en runtime antes de devolverlo: nunca
retorna algo mal tipado en silencio.

## Decisión: tipos a mano hoy, OpenAPI mañana

Los tipos de `types/` se escriben a mano mientras la API es pequeña. En Épica 1
(cuando existan los endpoints de auth) pasarán a generarse desde el esquema
OpenAPI del backend (FastAPI ya lo expone). La separación tipos/cliente y el
`index.ts` como única API pública existen para que ese cambio no toque a los
consumidores.

## Comandos

```bash
pnpm --filter @rover/shared type-check   # tsc --noEmit estricto
pnpm --filter @rover/shared test         # node --test (sin deps extra)
pnpm --filter @rover/shared lint         # eslint
```

> Los tests corren `.ts` directo con el type stripping de Node (≥ 22.18); por
> eso los imports relativos del paquete llevan extensión `.ts` explícita.
