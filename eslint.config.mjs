import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // The Python side is not this linter's business. It matters because
    // `shap` (feature 32) vendors a bundled JavaScript plot widget into its
    // site-packages, which ESLint would otherwise walk.
    "pipeline/.venv/**",
  ]),
]);

export default eslintConfig;
