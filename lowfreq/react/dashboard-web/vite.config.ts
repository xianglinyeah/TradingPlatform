import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite dev server proxies /api to the Dashboard.Service backend so
// the front-end can call relative URLs and avoid CORS in local dev.
// In production the dashboard.Service is served behind the same origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_DASHBOARD_API ?? 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
});
