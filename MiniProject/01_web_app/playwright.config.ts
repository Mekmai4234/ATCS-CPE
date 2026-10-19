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
      command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3001',
      url: 'http://127.0.0.1:3001',
      reuseExistingServer: false,
      env: { VITE_DEMO_MODE: 'true' },
    },
    {
      command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3002',
      url: 'http://127.0.0.1:3002',
      reuseExistingServer: false,
      env: {
        VITE_DEMO_MODE: 'false',
        NEXT_PUBLIC_API_BASE_URL: process.env.WEB_TEST_API_URL || 'http://127.0.0.1:8000',
      },
    },
  ],
});
