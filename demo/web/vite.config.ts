import { defineConfig } from "vite";

// VITE_API_URL: URL of the deployed Worker, e.g. https://claims-demo-api.<account>.workers.dev
export default defineConfig({
  server: { fs: { allow: [".."] } },
  build: { outDir: "dist", emptyOutDir: true },
});
