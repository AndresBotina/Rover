// ESLint flat config para todo el monorepo JS/TS (web, mobile, shared).
// Los workspaces heredan esta config (ESLint la busca subiendo desde su carpeta).
// El backend Python NO se lintea aquí: usa Ruff (ver apps/backend).
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import prettier from "eslint-config-prettier";
import globals from "globals";

export default tseslint.config(
  {
    // Nada de esto debe lintarse.
    ignores: [
      "**/node_modules/**",
      "**/dist/**",
      "**/.next/**",
      "**/.turbo/**",
      "apps/backend/**",
      "docs/**",
    ],
  },
  // Reglas base recomendadas (JS + TS, sin type-checking para mantenerlo ágil).
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: {
      globals: {
        ...globals.node,
        ...globals.browser,
      },
    },
  },
  // SIEMPRE al final: apaga las reglas de formato para no pelear con Prettier.
  prettier,
);
