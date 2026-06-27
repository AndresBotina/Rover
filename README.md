# Rover

Asistente de viajes con IA. Este repositorio es un **monorepo híbrido**:

- La parte **JS/TS** (web, mobile, paquetes compartidos) se gestiona con
  **pnpm workspaces + Turborepo**.
- El **backend Python** (FastAPI) vive en el mismo repo pero **fuera** del
  workspace de pnpm, con su propio tooling (**uv**).

> Marca vs. nombre técnico: el nombre de marca visible ("Rover") está desacoplado
> de los nombres técnicos. Vive en un único lugar configurable
> (`packages/shared/src/config.ts` → `APP_NAME`); los paquetes usan el scope
> `@rover/*` y no dependen de ese valor.

## Estructura

```
rover/
├── apps/
│   ├── backend/      # Python + FastAPI — gestionado con uv (real en HU-0.4)
│   ├── web/          # Next.js — placeholder (real en HU-3.1)
│   └── mobile/       # Expo — placeholder (real en HU-4.1)
├── packages/
│   └── shared/       # TS: tipos + cliente API — stub (se llena en HU-0.7)
├── package.json      # raíz privado "rover-app": scripts + Turborepo
├── pnpm-workspace.yaml
├── turbo.json
└── .gitignore
```

## Requisitos

- **Node** 22 LTS o superior.
- **pnpm** vía corepack (fijado en `packageManager` del `package.json` raíz):
  ```bash
  corepack enable
  ```
- Para el backend: **Python ≥ 3.12** y **uv**.

## Comandos (JS/TS, desde la raíz)

| Comando            | Descripción                                            |
| ------------------ | ------------------------------------------------------ |
| `pnpm install`     | Instala dependencias y enlaza los workspaces.          |
| `pnpm dev`         | Arranca las apps en desarrollo (`turbo run dev`).      |
| `pnpm build`       | Compila todos los paquetes (`turbo run build`).        |
| `pnpm lint`        | Linter en todos los paquetes (`turbo run lint`).       |
| `pnpm type-check`  | Chequeo de tipos (`turbo run type-check`).             |
| `pnpm test`        | Tests (`turbo run test`).                              |

> Algunas tareas aún no están implementadas en todos los paquetes (web/mobile son
> placeholders); el pipeline está definido en `turbo.json` desde ya.

## Backend Python (aparte)

El backend **no** se gestiona con pnpm. Ver [`apps/backend/README.md`](apps/backend/README.md):

```bash
cd apps/backend
uv sync
```
