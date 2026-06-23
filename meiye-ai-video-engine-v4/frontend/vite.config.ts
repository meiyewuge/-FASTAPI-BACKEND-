import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // 开发时把 /api 代理到后端
    proxy: { "/api": "http://localhost:8000" },
  },
});
