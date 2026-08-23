import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
    plugins: [vue()],
    base: './',
    build: {
      outDir: 'static/music-console',
      emptyOutDir: true,
      rollupOptions: {
        output: {
          entryFileNames: 'assets/music-console.js',
          chunkFileNames: 'assets/[name].js',
          assetFileNames: ({ names }) =>
            names?.some((name) => name.endsWith('.css'))
              ? 'assets/music-console.css'
              : 'assets/[name][extname]',
        },
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': env.VITE_API_TARGET || 'http://127.0.0.1:8004',
      },
    },
  }
})
