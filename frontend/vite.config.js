import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend runs on :8000 with permissive CORS, so the dev server can talk
// to it directly. A proxy is also configured so relative /api calls work if you
// prefer to avoid cross-origin requests entirely.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
