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
├── docs/             # Documentación del proyecto (backlog incluido)
├── package.json      # raíz privado "rover-app": scripts + Turborepo
├── pnpm-workspace.yaml
├── turbo.json
└── .gitignore
```

> La documentación del proyecto (backlog incluido) vive en
> [`docs/`](docs/): `backlog.md` (Épica 0 en curso) y `backlog-full.md`
> (panorama de las 7 épicas).

## Requisitos

- **Node** 22 LTS o superior.
- **pnpm** vía corepack (fijado en `packageManager` del `package.json` raíz):
  ```bash
  corepack enable
  ```
- Para el backend: **Python ≥ 3.12** y **uv**.

## Comandos (JS/TS, desde la raíz)

| Comando           | Descripción                                       |
| ----------------- | ------------------------------------------------- |
| `pnpm install`    | Instala dependencias y enlaza los workspaces.     |
| `pnpm dev`        | Arranca las apps en desarrollo (`turbo run dev`). |
| `pnpm build`      | Compila todos los paquetes (`turbo run build`).   |
| `pnpm lint`       | ESLint en todos los paquetes (`turbo run lint`).  |
| `pnpm format`     | Formatea los archivos JS/TS con Prettier.         |
| `pnpm type-check` | Chequeo de tipos (`turbo run type-check`).        |
| `pnpm test`       | Tests (`turbo run test`).                         |

> Algunas tareas aún no están implementadas en todos los paquetes (web/mobile son
> placeholders); el pipeline está definido en `turbo.json` desde ya.

## Calidad de código (lint & formato)

El repo es híbrido, así que el linting/formateo vive en **dos mundos**:

**JS/TS** (web, mobile, shared) — ESLint (flat config en `eslint.config.mjs`) +
Prettier (`.prettierrc.json`). ESLint solo revisa calidad; el formato lo decide
Prettier (las reglas de formato de ESLint quedan apagadas con `eslint-config-prettier`).

```bash
pnpm lint            # ESLint en los workspaces JS/TS
pnpm format          # Prettier escribe los archivos JS/TS
pnpm format:check    # Prettier en modo verificación (no escribe)
```

**Python** (`apps/backend`) — [Ruff](https://docs.astral.sh/ruff/) como linter
**y** formateador (reemplaza black + flake8 + isort), gestionado con uv **fuera**
de Turborepo:

```bash
cd apps/backend
uv run ruff check .        # lintea (añade --fix para autocorregir)
uv run ruff format .       # formatea
```

## Type-checking (estricto)

Chequeo de tipos estricto, también en los **dos mundos**. No va en el pre-commit
hook (es más pesado); corre como script y en CI (HU-0.5).

**JS/TS** — `tsc --noEmit` por workspace, orquestado por Turborepo. La estrictez
vive en `tsconfig.base.json` (raíz) y los workspaces la heredan vía `extends`
(`strict` + `noUncheckedIndexedAccess`, `noImplicitOverride`,
`exactOptionalPropertyTypes`, `noFallthroughCasesInSwitch`,
`forceConsistentCasingInFileNames`).

```bash
pnpm type-check      # tsc --noEmit en los workspaces JS/TS
```

> `web` y `mobile` aún no tienen fuentes: su `tsconfig.json` está listo y su
> `type-check` es un no-op hasta que su HU (3.1 / 4.1) agregue `src/`.

**Python** (`apps/backend`) — [mypy](https://mypy-lang.org/) en modo estricto
(`strict = true` en `pyproject.toml`), fuera de Turborepo:

```bash
cd apps/backend
uv run mypy .
```

### Hooks de pre-commit (lefthook)

Usamos [**lefthook**](https://lefthook.dev/) porque maneja TS y Python en un solo
repo con un único binario, es muy rápido y corre solo sobre los archivos _staged_.
En cada commit: Prettier + ESLint `--fix` en TS/JS y `ruff format` + `ruff check --fix`
en Python (ver `lefthook.yml`). No corre type-check ni tests (eso es HU-0.3 / HU-0.5).

Tras un clone fresco, los hooks se instalan solos con `pnpm install` (script
`prepare`). Si necesitas (re)instalarlos a mano:

```bash
pnpm lefthook install
```

## Backend Python (aparte)

El backend **no** se gestiona con pnpm. Ver [`apps/backend/README.md`](apps/backend/README.md):

```bash
cd apps/backend
uv sync
```
