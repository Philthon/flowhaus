import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `flowhaus dev --port 8010 --web-port 5180` sets these; the defaults match `uvicorn` and Vite.
const apiPort = process.env.FLOWHAUS_API_PORT ?? '8000'
const webPort = Number(process.env.FLOWHAUS_WEB_PORT ?? 5173)

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  build: { chunkSizeWarningLimit: 1500 },
  server: {
    port: webPort,
    strictPort: true,
    proxy: { '/api': { target: `http://127.0.0.1:${apiPort}`, changeOrigin: true } },
  },
})
