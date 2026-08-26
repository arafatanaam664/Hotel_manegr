import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// التطوير: الوكيل /api ← خادم FastAPI على 8000 (المتصفح خارج الرملة — لا localhost في الواجهة)
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})
