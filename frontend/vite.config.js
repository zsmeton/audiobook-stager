import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Dev server. The production build uses base /static/ and FastAPI serves frontend/dist.
const apiOrigin = process.env.STAGER_API_ORIGIN || "http://127.0.0.1:9570";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: apiOrigin,
        changeOrigin: true,
      },
    },
  },
});
