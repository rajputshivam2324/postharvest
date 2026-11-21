import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { loadEnv, type Plugin } from 'vite';

/** The static landing page lives in public/site. Without this, /site/ falls through to the SPA. */
function landingIndex(): Plugin {
  type Req = { url?: string };
  type Res = { statusCode: number; setHeader: (n: string, v: string) => void; end: () => void };
  const rewrite = (req: Req, res: Res, next: () => void) => {
    const url = req.url ?? '';
    const [path, query] = url.split('?');
    const suffix = query ? `?${query}` : '';
    if (path === '/site') {
      // The page uses relative asset paths, so it must be served from a trailing-slash URL.
      res.statusCode = 302;
      res.setHeader('Location', `/site/index.html${suffix}`);
      res.end();
      return;
    }
    if (path === '/site/') req.url = `/site/index.html${suffix}`;
    next();
  };
  return {
    name: 'landing-index',
    configureServer: (server) => void server.middlewares.use(rewrite),
    configurePreviewServer: (server) => void server.middlewares.use(rewrite),
  };
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), landingIndex()],
  server: {
    proxy: {
      '/api': {
        target: loadEnv(mode, process.cwd(), '').API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
}));
