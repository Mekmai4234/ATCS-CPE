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
  page.on('request', (request) => {
    if (/\/api\/|accounts\.google\.com/.test(request.url())) privateRequests.push(request.url());
  });
  for (const path of ['/', '/admin', '/chat']) {
    await page.goto(`http://127.0.0.1:3010${path}`);
    await page.getByText('กำลังเตรียมการเข้าสู่ระบบ', { exact: true }).waitFor();
    assert.equal(
      await page.getByRole('button', { name: 'เข้าสู่ระบบด้วย Google', exact: true }).isDisabled(),
      true,
    );
    assert.equal(await page.getByRole('checkbox').count(), 0);
    assert.equal(await page.getByRole('button', { name: 'ทดลองด้วยบัญชี A' }).count(), 0);
  }
  assert.deepEqual(privateRequests, []);
  console.log(
    'Production preview: private routes gated; no demo account selector, GIS or API requests.',
  );
} finally {
  await browser?.close();
  server.kill();
}
