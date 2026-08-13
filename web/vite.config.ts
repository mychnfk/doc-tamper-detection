import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  // dev 时前端跑 5173，后端跑 8000；生产由 api.py 直接托管 dist，不经此代理
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
})
