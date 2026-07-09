import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev: /api 요청을 Flask 백엔드(8060)로 프록시 — CORS 설정 불필요, SSE 지원
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8060",
        changeOrigin: true,
      },
    },
  },
});
