import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './tests/browser',
  timeout: 30000,
  expect: { timeout: 10000 },
  fullyParallel: true,
  workers: 2,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    ...devices['Desktop Chrome'],
    channel: 'chrome',
    baseURL: 'http://127.0.0.1:3001',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command:
        'node node_modules/vite/bin/vite.js --mode workspace-tests --host 127.0.0.1 --port 3001',
      url: 'http://127.0.0.1:3001',
      reuseExistingServer: false,
      env: { VITE_DEMO_MODE: 'true' },
    },
    {
      command:
        'node node_modules/vite/bin/vite.js --mode workspace-tests --host 127.0.0.1 --port 3002',
      url: 'http://127.0.0.1:3002',
      reuseExistingServer: false,
      env: {
        VITE_DEMO_MODE: 'false',
        NEXT_PUBLIC_API_BASE_URL: process.env.WEB_TEST_API_URL || 'http://127.0.0.1:8000',
      },
    },
    {
      command:
        'node node_modules/vite/bin/vite.js --mode session-tests --host 127.0.0.1 --port 3003',
      url: 'http://127.0.0.1:3003',
      reuseExistingServer: false,
      env: {
        VITE_DEMO_MODE: 'false',
        VITE_GOOGLE_CLIENT_ID: 'test-client.apps.googleusercontent.com',
        NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:3003',
      },
      // Auth tests use a test-only SessionPort, not an assumed backend contract.
    },
    ...(process.env.WEB_IDENTITY_TEST === 'true'
      ? [
          {
            command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3004',
            url: 'http://127.0.0.1:3004',
            reuseExistingServer: false,
            env: {
              VITE_DEMO_MODE: 'false',
              NEXT_PUBLIC_API_BASE_URL: process.env.WEB_IDENTITY_API_URL!,
            },
          },
        ]
      : []),
  ],
});
