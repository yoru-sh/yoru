import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Allow serving TS sources from the shared workspace package.
    fs: { allow: ['..'] },
  },
})
