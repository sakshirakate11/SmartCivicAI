import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  if (mode === 'production') {
    const apiUrl = loadEnv(mode, process.cwd(), 'VITE_').VITE_API_URL?.trim()
    if (!apiUrl) {
      throw new Error('Production builds require VITE_API_URL to point to the deployed backend API.')
    }

    let parsedApiUrl
    try {
      parsedApiUrl = new URL(apiUrl)
    } catch {
      throw new Error('VITE_API_URL must be an absolute HTTPS URL ending in /api.')
    }
    if (parsedApiUrl.protocol !== 'https:' || !parsedApiUrl.pathname.replace(/\/+$/, '').endsWith('/api')) {
      throw new Error('VITE_API_URL must be an absolute HTTPS URL ending in /api.')
    }
  }

  return {
    plugins: [react()],
  }
})
