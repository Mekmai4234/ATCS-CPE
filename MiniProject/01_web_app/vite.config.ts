import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import type { IncomingMessage, ServerResponse } from 'node:http';

function canonicalLocalNavigation(req: IncomingMessage, res: ServerResponse, next: () => void) {
  if (
    req.method === 'GET' &&
    req.headers.host === '127.0.0.1:3000' &&
    req.headers.accept?.includes('text/html') &&
    req.url?.startsWith('/')
  ) {
    res.writeHead(307, {
      Location: `http://localhost:3000${req.url}`,
      'Cache-Control': 'no-store',
    });
    res.end();
    return;
  }
  next();
}

export default defineConfig(({ mode, command }) => {
  if (command === 'build' && ['workspace-tests', 'session-tests'].includes(mode))
    throw new Error('Test harness modes cannot produce a deployment build');
  // Read only these public names; never expose the shared server .env wholesale.
  const shared = loadEnv(mode, '..', 'NEXT_PUBLIC_API_BASE_URL');
  const local = loadEnv(mode, '.', ['NEXT_PUBLIC_API_BASE_URL', 'VITE_']);
  const apiUrl =
    local.NEXT_PUBLIC_API_BASE_URL || shared.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
  // Same-origin /api also preserves readable 401/403 responses and host-only cookies.
  // Local dev/preview provide the proxy; deployed static files need a reverse proxy.
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
        configurePreviewServer(server) {
          server.middlewares.use(canonicalLocalNavigation);
        },
        configureServer(server) {
          // The local Google OAuth client and backend trust localhost:3000.
          // Normalize document navigations before GIS creates an origin-bound challenge.
          if (mode === 'development') server.middlewares.use(canonicalLocalNavigation);
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
    preview: {
      strictPort: true,
      ...(sameOrigin ? { proxy: { '/api': { target: parsed.origin, changeOrigin: false } } } : {}),
    },
    server: {
      strictPort: true,
      ...(sameOrigin ? { proxy: { '/api': { target: parsed.origin, changeOrigin: false } } } : {}),
    },
  };
});
