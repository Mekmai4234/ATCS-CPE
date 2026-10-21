import { spawn } from 'node:child_process';
import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
const server = spawn(
  process.execPath,
  [
    'node_modules/vite/bin/vite.js',
    'preview',
    '--host',
    '127.0.0.1',
    '--port',
    '3010',
    '--strictPort',
  ],
  { stdio: 'ignore', windowsHide: true },
);
let browser;
try {
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch('http://127.0.0.1:3010')).ok) break;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage();
  const privateRequests = [];
  const authRequests = [];
  await page.route('**/api/auth/me', (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'authentication_required' } }),
    }),
  );
  await page.route('**/api/auth/challenge', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        error: { code: 'auth_not_configured', message: 'Google login is not configured' },
      }),
    }),
  );
  page.on('request', (request) => {
    if (request.url().includes('/api/auth/')) authRequests.push(request.url());
    else if (/\/api\/|accounts\.google\.com/.test(request.url()))
      privateRequests.push(request.url());
  });
  for (const path of ['/', '/admin', '/chat']) {
    await page.goto(`http://127.0.0.1:3010${path}`);
    await page.getByText('Google login is not configured', { exact: true }).waitFor();
    assert.equal(await page.getByRole('checkbox').count(), 0);
    assert.equal(await page.getByRole('button', { name: 'ทดลองด้วยบัญชี A' }).count(), 0);
  }
  assert.deepEqual(privateRequests, []);
  assert.equal(authRequests.filter((url) => url.includes('/me')).length, 3);
  assert.equal(authRequests.filter((url) => url.includes('/challenge')).length, 3);
  console.log(
    'Production preview: HttpSessionPort calls me/challenge; unconfigured auth gates private routes without demo, GIS or workspace requests.',
  );
} finally {
  await browser?.close();
  server.kill();
}
