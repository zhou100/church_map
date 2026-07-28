import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // eslint-disable-next-line no-undef
      '/api': process.env.VITE_DEV_API_PROXY || 'http://localhost:8000',
    },
  },
})
