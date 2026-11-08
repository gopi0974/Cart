import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiUrl = env.VITE_API_URL || process.env.VITE_API_URL || env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_URL;

  // Fail production builds on cloud providers if VITE_API_URL is missing
  if (command === 'build') {
    const isCloudBuild = Boolean(process.env.VERCEL || process.env.RENDER || process.env.CI || process.env.CF_PAGES || process.env.NETLIFY);
    if (isCloudBuild && !apiUrl) {
      throw new Error(
        '\n\n[FATAL CONFIGURATION ERROR] VITE_API_URL environment variable is missing at build time.\n' +
        'You must configure VITE_API_URL in your hosting platform (e.g. Vercel Project Settings > Environment Variables) ' +
        'pointing to your Render backend API (e.g. https://smartcart-api-...onrender.com).\n'
      );
    }
  }

  return {
    plugins: [react()],
    server: {
      port: 5173,
      host: true
    }
  };
})
