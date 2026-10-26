import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

// Keep the limit in bytes: Vite's displayed kB are decimal, not KiB.
const MAX_CHUNK_BYTES = 500_000
const chunkBudget: Plugin = {
  name: 'thrive-chunk-budget',
  apply: 'build',
  generateBundle(_, bundle) {
    for (const [name, output] of Object.entries(bundle)) {
      if (output.type === 'chunk') {
        const bytes = new TextEncoder().encode(output.code).byteLength
        if (bytes >= MAX_CHUNK_BYTES) {
          this.error(`${name} is ${bytes} bytes; JavaScript chunks must be below ${MAX_CHUNK_BYTES} bytes.`)
        }
      }
    }
  },
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), chunkBudget],
  base: '/',
  build: {
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // CommonJS helpers must not live in the entry chunk: vendors import
          // them, and that would create vendor -> entry -> vendor cycles.
          if (id.includes('commonjsHelpers')) return 'vendor-runtime'
          if (!id.includes('/node_modules/')) return undefined
          if (/\/(react|react-dom|scheduler)\//.test(id)) return 'vendor-react'
          if (/\/(recharts|recharts-scale)\//.test(id)) return 'vendor-charts'
          if (/\/(victory-vendor|d3-[^/]+)\//.test(id)) return 'vendor-chart-math'
          if (/\/(lodash|lodash-es)\//.test(id)) return 'vendor-utilities'
          if (/\/(framer-motion|motion-dom|motion-utils)\//.test(id)) return 'vendor-motion'
          if (id.includes('/lucide-react/')) return 'vendor-icons'
          return 'vendor-shared'
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5000,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})