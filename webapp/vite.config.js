import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 팀원이 관리하는 서류 추천 렌더러(원본 단일 소스) — 복사하지 않고 alias로 참조
const DOC_RECO_DIR = fileURLToPath(
  new URL("../src/frontend/ui/assets/demo/document_recommendation", import.meta.url),
);

// dev: /api 요청을 Flask 백엔드(8060)로 프록시 — CORS 설정 불필요, SSE 지원
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@docreco": DOC_RECO_DIR,
    },
  },
  server: {
    port: 5173,
    fs: {
      allow: [fileURLToPath(new URL("..", import.meta.url))],
    },
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8060",
        changeOrigin: true,
      },
    },
  },
});
