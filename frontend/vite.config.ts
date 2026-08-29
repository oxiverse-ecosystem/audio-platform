import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API and (dev) CDN live on the FastAPI server. In dev, proxy /v1 and /cdn to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://localhost:8000",
      "/cdn": "http://localhost:8000",
      "/metrics": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
});
