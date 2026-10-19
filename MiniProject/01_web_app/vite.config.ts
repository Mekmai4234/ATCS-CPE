import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  // Read only these public names; never expose the shared server .env wholesale.
  const shared = loadEnv(mode, '..', 'NEXT_PUBLIC_API_BASE_URL');
  const local = loadEnv(mode, '.', ['NEXT_PUBLIC_API_BASE_URL', 'VITE_']);
  const apiUrl =
    local.NEXT_PUBLIC_API_BASE_URL || shared.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
  const parsed = new URL(apiUrl);
  if (
    !['http:', 'https:'].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error(
      'NEXT_PUBLIC_API_BASE_URL must be an HTTP(S) URL without credentials/query/fragment',
    );
  }
  return {
    plugins: [react()],
    define: {
      'import.meta.env.NEXT_PUBLIC_API_BASE_URL': JSON.stringify(apiUrl.replace(/\/$/, '')),
    },
    server: { strictPort: true },
  };
});
