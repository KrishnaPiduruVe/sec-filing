import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
const target = process.env.ATLAS_API_URL || "http://127.0.0.1:8501";
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      [
        "/health",
        "/research",
        "/status",
        "/jobs",
        "/prepare",
        "/query",
        "/filings",
        "/companies",
        "/usage",
      ].map((path) => [
        path,
        {
          target,
          changeOrigin: true,
          configure(proxy) {
            proxy.on("proxyReq", (req) => req.removeHeader("origin"));
          },
        },
      ]),
    ),
  },
  test: { environment: "jsdom", setupFiles: "./src/test-setup.js", css: false },
});
