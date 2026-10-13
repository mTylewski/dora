import { defineConfig } from "vitest/config";

// Prompts are imported as text in the Worker (wrangler [[rules]] Text); mirror that here.
export default defineConfig({
  plugins: [{
    name: "md-as-text",
    transform(code, id) {
      if (id.endsWith(".md")) return { code: `export default ${JSON.stringify(code)};`, map: null };
    },
  }],
  test: { include: ["shared/**/*.test.ts", "worker/**/*.test.ts", "web/src/**/*.test.ts"] },
});
