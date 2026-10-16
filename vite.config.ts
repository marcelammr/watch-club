import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "frontend"),
    },
  },
  build: {
    outDir: "app/static/js",
    emptyOutDir: false,
    rollupOptions: {
      input: path.resolve(__dirname, "frontend/main.tsx"),
      output: {
        entryFileNames: "command.js",
        chunkFileNames: "command-[name].js",
        assetFileNames: "command-[name][extname]",
      },
    },
  },
  appType: "custom",
});
