import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Build straight into the Databricks App source folder so `bundle deploy` ships it.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../src/app/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://localhost:8000" } },
});
