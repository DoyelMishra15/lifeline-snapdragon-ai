import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The proxy is what makes the Codespaces networking story simple: the
// browser only ever talks to Vite's single forwarded origin (port
// 5173). Vite itself — running server-side, inside the same
// devcontainer as the backend — forwards /api/* to `sam local
// start-api` on port 3000. This avoids needing the browser to reach a
// second forwarded port directly (which would need CORS and a
// Codespaces-specific forwarded URL baked into the frontend build)
// and needs zero configuration beyond VITE_API_BASE_URL=/api in
// frontend/.env. See docs/local-development.md.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:3000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
