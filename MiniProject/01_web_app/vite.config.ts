import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode, command }) => {
  if (command === 'build' && ['workspace-tests', 'session-tests'].includes(mode))
    throw new Error('Test harness modes cannot produce a deployment build');
  // Read only these public names; never expose the shared server .env wholesale.
  const shared = loadEnv(mode, '..', 'NEXT_PUBLIC_API_BASE_URL');
  const local = loadEnv(mode, '.', ['NEXT_PUBLIC_API_BASE_URL', 'VITE_']);
  const apiUrl =
    local.NEXT_PUBLIC_API_BASE_URL || shared.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
  // Same-origin /api also preserves readable 401/403 responses and host-only cookies.
  // Production must provide the equivalent reverse proxy; Vite's proxy is dev-only.
  const sameOrigin = local.VITE_API_SAME_ORIGIN !== 'false';
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
    plugins: [
      react(),
      {
        name: 'development-test-entry',
        apply: 'serve',
        configureServer(server) {
          if (!['workspace-tests', 'session-tests'].includes(mode)) return;
          server.middlewares.use((req, _res, next) => {
            const path = req.url?.split('?')[0] || '';
            if (
              !path.includes('.') &&
              !path.startsWith('/@') &&
              !path.startsWith('/api/') &&
              !path.startsWith('/__test__/')
            )
              req.url =
                mode === 'workspace-tests' ? '/tests/workspace.html' : '/tests/session.html';
            next();
          });
        },
      },
    ],
    define: {
      'import.meta.env.NEXT_PUBLIC_API_BASE_URL': JSON.stringify(
        sameOrigin ? '' : apiUrl.replace(/\/$/, ''),
      ),
    },
    server: {
      strictPort: true,
      ...(sameOrigin ? { proxy: { '/api': { target: parsed.origin, changeOrigin: false } } } : {}),
    },
  };
});
