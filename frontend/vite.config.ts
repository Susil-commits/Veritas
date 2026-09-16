import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react/') || id.includes('node_modules/react-dom/') || id.includes('node_modules/react-router-dom/')) {
            return 'vendor-react'
          }
          if (id.includes('node_modules/lucide-react/')) {
            return 'vendor-icons'
          }
          if (id.includes('node_modules/recharts/')) {
            return 'vendor-charts'
          }
          if (id.includes('node_modules/framer-motion/')) {
            return 'vendor-motion'
          }
          if (id.includes('node_modules/@supabase/')) {
            return 'vendor-supabase'
          }
        },
      },
    },
  },
})
