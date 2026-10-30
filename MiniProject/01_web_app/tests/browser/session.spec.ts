import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const base = 'http://127.0.0.1:3003';
const members = {
  A: { id: 'A', name: 'สมาชิก A', email: 'a@example.test', role: 'user', status: 'active' },
  B: { id: 'B', name: 'สมาชิก B', email: 'b@example.test', role: 'user', status: 'active' },
  admin: {
    id: 'admin',
    name: 'ผู้ดูแล',
    email: 'admin@example.test',
    role: 'admin',
    status: 'active',
  },
};
type Account = keyof typeof members;

async function fixture(page: Page, initial: Account | null = null) {
  let account = initial;
  let status = 200;
  let logoutFails = false;
  let waitForJob = false;
  let jobReads = 0;
  let adminReads = 0;
  const requests: { path: string; body: unknown; headers: Record<string, string> }[] = [];
  const session = (id: Account) => ({
    member: { ...members[id] },
    sessionId: `opaque-${id}`,
    csrfToken: `csrf-${id}`,
    csrfHeader: 'X-Fixture-CSRF',
    adminSections: id === 'admin' ? ['overview', 'members', 'videos', 'jobs', 'audit'] : [],
  });
  await page.route('https://accounts.google.com/gsi/client', (route) =>
    route.fulfill({
      contentType: 'application/javascript',
      body: `window.google={accounts:{id:{initialize(o){window.__gisCallback=o.callback},renderButton(el){const b=document.createElement('button');b.textContent='Continue with Google';b.onclick=()=>window.__gisCallback({credential:window.__testCredential||'fixture-A'});el.appendChild(b)},disableAutoSelect(){}}}};`,
    }),
  );
  await page.route('**/__test__/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON();
    requests.push({ path, body, headers: route.request().headers() });
    const json = (data: unknown, code = 200) =>
      route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(data) });
    if (path.endsWith('/session')) return json(account ? session(account) : null);
    if (path.endsWith('/csrf')) return json({ token: 'login-nonce' });
    if (path.endsWith('/google')) {
      if (body.credential === 'suspended')
        return json(
          { error: { code: 'account_suspended', message: 'บัญชีนี้ถูกระงับการใช้งาน' } },
          403,
        );
      account =
        body.credential === 'fixture-B' ? 'B' : body.credential === 'fixture-admin' ? 'admin' : 'A';
      return json(session(account));
    }
    if (path.endsWith('/logout')) {
      if (logoutFails) return json({ error: { message: 'Unavailable' } }, 503);
      account = null;
      return json({ ok: true });
    }
    if (path.endsWith('/admin')) {
      adminReads++;
      return json({ members: Object.values(members), videos: [], jobs: [], audit: [] });
    }
    if (path.endsWith('/admin/member')) return json({ ok: true });
    return json({ error: { message: 'not found' } }, 404);
  });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON();
    requests.push({ path, body, headers: route.request().headers() });
    const json = (data: unknown, code = 200) =>
      route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(data) });
    if (!account)
      return json(
        { error: { code: 'session_expired', message: 'Session expired', retryable: false } },
        401,
      );
    if (status !== 200) {
      if (status === 401) account = null;
      return json(
        { error: { code: 'denied', message: 'ไม่มีสิทธิ์ทำงานนี้', retryable: true } },
        status,
      );
    }
    const id = account === 'B' ? 'wD3NSzYtsMc' : 'dQw4w9WgXcQ';
    if (path === '/api/videos')
      return json({
        items: [
          {
            video_id: id,
            title: `คลังส่วนตัว ${account}`,
            channel_id: 'c',
            channel_title: 'Fixture',
            published_at: '2026-10-01',
            status: 'ready',
            generation: 1,
            indexed_version: 'v1',
            canonical_url: `https://youtu.be/${id}`,
            thumbnail_url: null,
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
        mode: 'fixture',
      });
    if (path === '/api/chat') {
      if (waitForJob) return json({ job_id: 'pending', state: 'queued' }, 202);
      return json({
        answer: `คำตอบส่วนตัว ${account}`,
        status: 'answered',
        conversation_id: `conversation-${account}`,
        citations: [],
        coverage: {
          expected_videos: 1,
          processed_videos: 1,
          expected_chunks: 1,
          processed_chunks: 1,
          complete: true,
          notes: [],
        },
      });
    }
    if (path === '/api/jobs/pending') {
      jobReads++;
      return json({
        job_id: 'pending',
        kind: 'chat',
        state: 'running',
        stage: 'running',
        attempt_count: 1,
        max_attempts: 3,
        result: null,
      });
    }
    return json({ error: { code: 'missing', message: 'not found', retryable: false } }, 404);
  });
  return {
    requests,
    setStatus: (next: number) => {
      status = next;
    },
    setLogoutFailure: (next: boolean) => {
      logoutFails = next;
    },
    pending: () => {
      waitForJob = true;
    },
    jobReads: () => jobReads,
    adminReads: () => adminReads,
  };
}
async function openChat(page: Page) {
  await page.getByRole('button', { name: 'วิดีโอของฉัน', exact: true }).click();
  await page.getByRole('checkbox').first().check();
  await page.getByRole('button', { name: 'ถาม Buddy จากวิดีโอที่เลือก' }).click();
  await page.getByLabel('คำถามของคุณ').fill('ถามจากแหล่งข้อมูลของฉัน');
}

test('pending real backend keeps private routes closed and makes no workspace requests', async ({
  page,
}) => {
  const server = await fixture(page);
  await page.goto(`${base}/admin?pending=1`);
  await expect(page.getByRole('heading', { name: 'ยินดีต้อนรับ' })).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'เข้าสู่ระบบด้วย Google', exact: true }),
  ).toBeDisabled();
  expect(server.requests).toEqual([]);
  await expect(page.getByRole('textbox')).toHaveCount(0);
});
test('Google button exchanges only the credential and never persists credentials', async ({
  page,
}) => {
  const server = await fixture(page);
  await page.goto(base);
  await page.getByRole('button', { name: 'Continue with Google' }).click();
  await expect(page.getByRole('heading', { name: /รู้ให้/ })).toBeVisible();
  const exchange = server.requests.find((request) => request.path === '/__test__/google')!;
  expect(exchange.body).toEqual({ credential: 'fixture-A' });
  expect(exchange.headers['x-test-login-csrf']).toBe('login-nonce');
  expect(
    await page.evaluate(() => ({
      local: Object.keys(localStorage),
      session: Object.keys(sessionStorage),
    })),
  ).toEqual({ local: [], session: [] });
  await expect(page.getByRole('button', { name: 'จัดการระบบ', exact: true })).toHaveCount(0);
});
test('user cannot enter the admin URL and never fetches admin content', async ({ page }) => {
  const server = await fixture(page, 'A');
  await page.goto(`${base}/admin`);
  await expect(page.getByRole('heading', { name: 'ไม่มีสิทธิ์เข้าถึงหน้านี้' })).toBeVisible();
  expect(server.adminReads()).toBe(0);
});
test('admin sections come from session capabilities and omit private conversations', async ({
  page,
}) => {
  const server = await fixture(page, 'admin');
  await page.goto(`${base}/admin`);
  await page.getByRole('button', { name: 'สมาชิก', exact: true }).click();
  await expect(page.getByRole('table')).toBeVisible();
  await page.getByRole('searchbox', { name: 'ค้นหาสมาชิก' }).fill('สมาชิก B');
  await expect(page.getByRole('cell', { name: /สมาชิก B/ })).toBeVisible();
  await expect(page.getByRole('cell', { name: /สมาชิก A/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /บทสนทนา|ตั้งค่า/ })).toHaveCount(0);
  await expect.poll(() => server.adminReads()).toBe(2); // Initial load + server-side search.
});
test('logout clears old answers and history cannot reveal A after B signs in', async ({ page }) => {
  await fixture(page, 'A');
  await page.goto(base);
  await openChat(page);
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByText('คำตอบส่วนตัว A', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'ออกจากระบบ', exact: true }).click();
  await expect(page.getByText('คำตอบส่วนตัว A', { exact: true })).toHaveCount(0);
  await page.evaluate(() => {
    (window as Window & { __testCredential?: string }).__testCredential = 'fixture-B';
  });
  await page.getByRole('button', { name: 'Continue with Google' }).click();
  await page.goBack();
  await expect(page.getByText('คำตอบส่วนตัว A', { exact: true })).toHaveCount(0);
  await expect(page.locator('.video-card').filter({ hasText: 'คลังส่วนตัว A' })).toHaveCount(0);
  await page.getByRole('button', { name: 'วิดีโอของฉัน', exact: true }).click();
  await expect(page.getByText('คลังส่วนตัว B', { exact: true }).last()).toBeVisible();
});
test('logout aborts old polling and does not resume it on the login screen', async ({ page }) => {
  const server = await fixture(page, 'A');
  server.pending();
  await page.goto(base);
  await openChat(page);
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByText(/Job ID: pending/)).toBeVisible();
  await page.getByRole('button', { name: 'ออกจากระบบ', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Continue with Google' })).toBeVisible();
  const afterLogout = server.jobReads();
  await page.waitForTimeout(1800);
  expect(server.jobReads()).toBe(afterLogout);
});
test('401 discards private UI and returns to login', async ({ page }) => {
  const server = await fixture(page, 'A');
  await page.goto(base);
  await openChat(page);
  server.setStatus(401);
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByText('เซสชันหมดอายุ กรุณาเข้าสู่ระบบอีกครั้ง', { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('คำถามของคุณ')).toHaveCount(0);
});
test('403 preserves the session, sends negotiated CSRF, and never auto-resubmits', async ({
  page,
}) => {
  const server = await fixture(page, 'A');
  await page.goto(base);
  await openChat(page);
  server.setStatus(403);
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'ไม่มีสิทธิ์ทำงานนี้' })).toBeVisible();
  await page.waitForTimeout(1700);
  const calls = server.requests.filter((request) => request.path === '/api/chat');
  expect(calls).toHaveLength(1);
  expect(calls[0].headers['x-fixture-csrf']).toBe('csrf-A');
  expect(calls[0].body).not.toHaveProperty('user_id');
  expect(calls[0].body).not.toHaveProperty('role');
  await expect(page.getByRole('button', { name: 'ออกจากระบบ', exact: true })).toBeVisible();
});
test('suspended sign-in stays outside private workspace', async ({ page }) => {
  await fixture(page);
  await page.goto(base);
  await page.evaluate(() => {
    (window as Window & { __testCredential?: string }).__testCredential = 'suspended';
  });
  await page.getByRole('button', { name: 'Continue with Google' }).click();
  await expect(page.getByText('บัญชีนี้ถูกระงับการใช้งาน', { exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox')).toHaveCount(0);
});

test('an expired admin session discards management content and returns to login', async ({
  page,
}) => {
  await fixture(page, 'admin');
  await page.route('**/__test__/admin', (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'session_expired', message: 'Session expired' } }),
    }),
  );
  await page.goto(`${base}/admin`);
  await expect(
    page.getByText('เซสชันหมดอายุ กรุณาเข้าสู่ระบบอีกครั้ง', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'เมนูผู้ดูแล' })).toHaveCount(0);
});
test('failed logout cannot silently switch to another account', async ({ page }) => {
  const server = await fixture(page, 'A');
  await page.goto(base);
  server.setLogoutFailure(true);
  await page.getByRole('button', { name: 'ออกจากระบบ', exact: true }).click();
  await expect(
    page.getByText('ยังยืนยันการออกจากระบบไม่ได้ กรุณาลองออกจากระบบอีกครั้ง', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Continue with Google' })).toHaveCount(0);
  server.setLogoutFailure(false);
  await page.getByRole('button', { name: 'ลองออกจากระบบอีกครั้ง' }).click();
  await expect(page.getByRole('button', { name: 'Continue with Google' })).toBeVisible();
});

test('a slow session check never flashes the private workspace', async ({ page }) => {
  const server = await fixture(page, 'A');
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route('**/__test__/session', async (route) => {
    await gate;
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        member: members.A,
        sessionId: 'opaque-A',
        csrfToken: 'csrf-A',
        csrfHeader: 'X-Fixture-CSRF',
        adminSections: [],
      }),
    });
  });
  await page.goto(base);
  await expect(page.getByText('กำลังตรวจสอบเซสชัน…', { exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  expect(server.requests.filter((request) => request.path.startsWith('/api/'))).toHaveLength(0);
  release();
  await expect(page.getByRole('heading', { name: /รู้ให้/ })).toBeVisible();
});

test('Google script network errors provide a retry without a password fallback', async ({
  page,
}) => {
  await fixture(page);
  await page.route('https://accounts.google.com/gsi/client', (route) => route.abort('failed'));
  await page.goto(base);
  await expect(
    page.getByText('เชื่อมต่อ Google ไม่ได้ กรุณาตรวจสอบเครือข่าย', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'ลองโหลด Google อีกครั้ง' })).toBeVisible();
  await page.screenshot({
    path: 'runtime/screenshots/mint-login-network-error.png',
    fullPage: true,
  });
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
});

for (const width of [375, 768, 1440]) {
  test(`reference layout fits ${width}px login and home`, async ({ page }) => {
    await fixture(page);
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`${base}/login?demo=1`);
    await expect(page.getByRole('button', { name: 'ทดลองด้วยบัญชี A' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: `runtime/screenshots/login-${width}.png`, fullPage: true });
    await page.getByRole('button', { name: 'ทดลองด้วยบัญชี A' }).click();
    await expect(page.getByRole('heading', { name: /รู้ให้/ })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: `runtime/screenshots/home-${width}.png`, fullPage: true });
  });
}
test('keyboard login and contrast checks on reading surfaces', async ({ page }) => {
  await fixture(page);
  await page.goto(`${base}/login?demo=1`);
  await page.getByRole('button', { name: 'ทดลองด้วยบัญชี A' }).focus();
  await page.keyboard.press('Enter');
  await openChat(page);
  await expect(page.getByLabel('คำถามของคุณ')).toBeVisible();
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(
    results.violations.map((violation) => ({
      id: violation.id,
      nodes: violation.nodes.map((node) => node.target),
    })),
  ).toEqual([]);
});
