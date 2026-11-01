import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const base = 'http://127.0.0.1:3003';
const video = {
  video_id: 'dQw4w9WgXcQ',
  title: 'บทเรียนส่วนตัว',
  status: 'ready',
  generation: 1,
  indexed_version: 'v1',
  channel_id: 'c',
  channel_title: 'ช่องของฉัน',
  published_at: '2026-10-01',
  canonical_url: 'https://youtu.be/dQw4w9WgXcQ',
  thumbnail_url: null,
};
const scope = {
  video_ids: [video.video_id],
  channel_ids: ['c'],
  date_from: '2026-10-01',
  date_to: null,
};
async function fixture(page: Page) {
  const posts: Record<string, unknown>[] = [];
  await page.route('**/__test__/session', (route) =>
    route.fulfill({
      json: {
        member: {
          id: 'history-owner',
          name: 'ผู้ทดสอบ',
          email: 'history@example.test',
          role: 'user',
          status: 'active',
        },
        sessionId: 'history-session',
        csrfToken: 'history-csrf',
        csrfHeader: 'X-Fixture-CSRF',
        adminSections: [],
      },
    }),
  );
  await page.route('**/api/**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/videos')
      return route.fulfill({
        json: { items: [video], total: 1, offset: 0, limit: 50, mode: 'custom' },
      });
    if (url.pathname === '/api/conversations') {
      const all = Array.from({ length: 21 }, (_, i) => ({
        conversation_id: `chat-${i}`,
        title: `คำถามที่ ${i}`,
        created_at: '2026-10-20T10:00:00Z',
        updated_at: '2026-10-26T03:00:00Z',
        message_count: 2,
        video_ids: [video.video_id],
      })).filter((item) => item.title.includes(url.searchParams.get('q') || ''));
      const offset = Number(url.searchParams.get('offset') || 0);
      return route.fulfill({
        json: { items: all.slice(offset, offset + 20), total: all.length, limit: 20, offset },
      });
    }
    if (url.pathname.startsWith('/api/conversations/')) {
      const id = url.pathname.split('/').at(-1)!;
      if (id === 'foreign')
        return route.fulfill({
          status: 404,
          json: { error: { code: 'not_found', message: 'Resource not found', retryable: false } },
        });
      const common = {
        job_id: 'saved-job',
        scope: [{ video_id: video.video_id, generation: 1, transcript_version: 'v1' }],
        state: 'completed',
        citations: [],
      };
      return route.fulfill({
        json: {
          conversation_id: id,
          total: 2,
          limit: 50,
          offset: 0,
          scope,
          messages: [
            { ...common, message_id: 'q', role: 'user', content: 'คำถามที่บันทึกไว้' },
            { ...common, message_id: 'a', role: 'assistant', content: 'คำตอบที่บันทึกไว้' },
          ],
        },
      });
    }
    if (url.pathname === '/api/chat') {
      const body = route.request().postDataJSON();
      posts.push(body);
      return route.fulfill({
        json: {
          answer: 'คำตอบต่อเนื่องจากประวัติ',
          conversation_id: body.conversation_id || 'new-chat',
          citations: [],
        },
      });
    }
    if (url.pathname === '/api/jobs/saved-job')
      return route.fulfill({
        json: {
          job_id: 'saved-job',
          kind: 'chat',
          state: 'completed',
          stage: 'completed',
          sources_available: true,
          result: null,
        },
      });
    return route.fulfill({
      status: 404,
      json: { error: { code: 'not_found', message: 'Missing', retryable: false } },
    });
  });
  return posts;
}

test('leaving a slow archive keeps the new chat and Buddy usable', async ({ page }) => {
  await fixture(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route('**/api/conversations/slow?*', async (route) => {
    await gate;
    await route
      .fulfill({
        json: { conversation_id: 'slow', messages: [], total: 0, limit: 50, offset: 0, scope },
      })
      .catch(() => {});
  });
  await page.goto(`${base}/chat/slow`);
  await expect(page.getByText('กำลังเปิดบทสนทนา…', { exact: true })).toBeVisible();
  await page
    .getByRole('navigation', { name: 'เมนูหลัก', exact: true })
    .getByRole('button', { name: 'หน้าแรก', exact: true })
    .click();
  release();
  await page
    .getByRole('navigation', { name: 'เมนูหลัก', exact: true })
    .getByRole('button', { name: 'ประวัติแชท', exact: true })
    .click();
  await page.getByRole('button', { name: 'เริ่มแชตใหม่', exact: true }).click();
  await expect(page.getByLabel('คำถามของคุณ', { exact: true })).toBeVisible();
  await expect(page.getByText('กำลังเปิดบทสนทนา…', { exact: true })).toHaveCount(0);
});

test('reload discovers the existing job and follows GET without another POST', async ({ page }) => {
  await fixture(page);
  let posts = 0,
    reads = 0,
    finished = false;
  const request = { question: 'คำถามเดิม', scope, conversation_id: null };
  const job = () => ({
    job_id: 'recover-job',
    kind: 'chat',
    state: finished ? 'completed' : 'running',
    stage: 'running',
    request,
    sources: [{ video_id: video.video_id, generation: 1, transcript_version: 'v1' }],
    result: finished
      ? { answer: 'ผลจากงานเดิม', conversation_id: 'restored', citations: [] }
      : null,
  });
  await page.route('**/api/member/jobs?*', (route) =>
    route.fulfill({
      json: { items: posts ? [job()] : [], total: posts ? 1 : 0, limit: 50, offset: 0 },
    }),
  );
  await page.route('**/api/worker-status', (route) =>
    route.fulfill({ json: { status: 'stale', ready: false } }),
  );
  await page.route('**/api/chat', (route) => {
    posts++;
    return route.fulfill({ status: 202, json: { job_id: 'recover-job', state: 'queued' } });
  });
  await page.route('**/api/jobs/recover-job', (route) => {
    reads++;
    return route.fulfill({ json: job() });
  });
  await page.goto(`${base}/chat`);
  await page.getByRole('button', { name: 'เลือกหรือเปลี่ยนวิดีโอ', exact: true }).click();
  await page.getByRole('checkbox').check();
  await page.getByLabel('คำถามของคุณ', { exact: true }).fill('คำถามเดิม');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect.poll(() => reads).toBeGreaterThan(0);
  await page.reload();
  await page
    .getByRole('region', { name: 'ติดตามงาน', exact: true })
    .getByRole('button', { name: 'ดูงานทั้งหมด', exact: true })
    .click();
  const drawer = page.getByRole('dialog', { name: 'งานของฉัน', exact: true });
  await expect(drawer.getByText(/ตัวประมวลผลยังไม่พร้อม/)).toBeVisible();
  finished = true;
  await drawer.getByRole('button', { name: 'ติดตามงาน', exact: true }).click();
  await expect(page.getByText('ผลจากงานเดิม', { exact: true })).toBeVisible();
  await expect(drawer).not.toBeVisible();
  expect(posts).toBe(1);
});

test('completed learning artifacts can reopen from member history', async ({ page }) => {
  await fixture(page);
  const job = {
    job_id: 'old-quiz',
    kind: 'artifact',
    state: 'completed',
    stage: 'completed',
    request: { type: 'quiz', topic: 'แบบฝึกเดิม', scope },
    sources: [{ video_id: video.video_id, generation: 1, transcript_version: 'v1' }],
    result: {
      artifacts: [
        {
          artifact_id: 'old-artifact',
          type: 'quiz',
          citations: [],
          content: {
            questions: [
              { question: 'คำถามที่กู้คืน', answer: 'คำตอบ', explanation: 'อธิบาย', citations: [] },
            ],
          },
        },
      ],
    },
  };
  await page.route('**/api/member/jobs?*', (route) => {
    const show = new URL(route.request().url()).searchParams.get('include_completed') === 'true';
    return route.fulfill({
      json: { items: show ? [job] : [], total: show ? 1 : 0, limit: 50, offset: 0 },
    });
  });
  await page.route('**/api/jobs/old-quiz', (route) => route.fulfill({ json: job }));
  await page.goto(`${base}/learning`);
  await page.getByRole('button', { name: 'ดูงานทั้งหมด', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'งานของฉัน', exact: true });
  await drawer.getByRole('tab', { name: 'ประวัติ', exact: true }).click();
  await drawer.getByRole('button', { name: 'ดูผลลัพธ์', exact: true }).click();
  await expect(page.getByText('1. คำถามที่กู้คืน', { exact: true })).toBeVisible();
  await expect(drawer).not.toBeVisible();
});

test('completed import result opens its video in the library', async ({ page }) => {
  await fixture(page);
  const job = {
    job_id: 'saved-import',
    kind: 'import',
    video_id: video.video_id,
    state: 'completed',
    stage: 'ready',
    request: {},
    sources: [],
  };
  await page.route('**/api/member/jobs?*', (route) => {
    const all = new URL(route.request().url()).searchParams.get('include_completed') === 'true';
    return route.fulfill({
      json: { items: all ? [job] : [], total: all ? 1 : 0, offset: 0, limit: 50 },
    });
  });
  await page.route('**/api/jobs/saved-import', (route) => route.fulfill({ json: job }));
  await page.goto(`${base}/learning`);
  await page.getByRole('button', { name: 'ดูงานทั้งหมด', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'งานของฉัน', exact: true });
  await drawer.getByRole('tab', { name: 'ประวัติ', exact: true }).click();
  await drawer.getByRole('button', { name: 'ดูผลลัพธ์', exact: true }).click();
  await expect(page).toHaveURL(`${base}/library`);
  await expect(page.getByRole('checkbox')).toBeChecked();
  await expect(drawer).not.toBeVisible();
});

test('real v2 media path loads authorized images without a fixture bridge', async ({ page }) => {
  await fixture(page);
  const hash = 'a'.repeat(64),
    version = 'b'.repeat(64),
    asset = 'c'.repeat(64);
  let revoked = false;
  await page.route('**/api/v2/videos/*/evidence', (route) =>
    route.fulfill(
      revoked
        ? { status: 404, json: { error: { code: 'video_not_found', message: 'not found' } } }
        : {
            json: {
              contract_version: 2,
              video_id: video.video_id,
              generation: 1,
              state: 'ready',
              evidence: [
                {
                  frame_id: hash,
                  asset_id: asset,
                  evidence_version: version,
                  timestamp_seconds: 12,
                  kind: 'ocr',
                  text: '<img src=x onerror=alert(1)> OCR จริง',
                },
              ],
            },
          },
    ),
  );
  await page.route('**/api/media/assets/*', (route) =>
    route.fulfill({
      contentType: 'image/png',
      body: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
        'base64',
      ),
    }),
  );
  await page.goto(`${base}/library`);
  const panel = page.locator('.media-evidence-panel');
  await panel.locator('summary').click();
  await expect(panel.locator('.frame-evidence img')).toBeVisible();
  await expect(
    panel.getByText('<img src=x onerror=alert(1)> OCR จริง', { exact: true }),
  ).toBeVisible();
  await expect(panel.locator('img[onerror]')).toHaveCount(0);
  revoked = true;
  await panel.locator('summary').click();
  await panel.locator('summary').click();
  await expect(panel.getByRole('alert')).toBeVisible();
  await expect(panel.locator('.frame-evidence img')).toHaveCount(0);
});

test('work strip reports running, queued and paused jobs without counting a paused job as running', async ({
  page,
}) => {
  await fixture(page);
  const jobs = [
    {
      job_id: 'working',
      kind: 'research',
      state: 'running',
      stage: 'running',
      request: { goal: 'ค้นคว้าที่กำลังทำ' },
      sources: [],
      created_at: '2026-11-01T01:00:00Z',
    },
    {
      job_id: 'waiting',
      kind: 'artifact',
      state: 'queued',
      stage: 'queued',
      request: { topic: 'แฟลชการ์ดในคิว' },
      sources: [],
      created_at: '2026-11-01T01:01:00Z',
    },
    {
      job_id: 'paused',
      kind: 'artifact',
      state: 'paused',
      stage: 'paused',
      error_code: 'quota_wait',
      retryable: true,
      request: { topic: 'แผนเรียนรอโควตา' },
      sources: [],
      created_at: '2026-11-01T01:02:00Z',
      wait: {
        estimated_retry_at: '2026-11-01T13:10:58Z',
        reason: 'quota_wait',
        time_source: 'estimate',
      },
    },
  ];
  await page.route('**/api/member/jobs?*', (route) =>
    route.fulfill({ json: { items: jobs, total: 3, limit: 50, offset: 0 } }),
  );
  await page.goto(base);
  const strip = page.getByRole('region', { name: 'ติดตามงาน', exact: true });
  for (const status of ['กำลังทำ 1', 'รอคิว 1', 'พักรอ 1'])
    await expect(strip).toContainText(status);
  await expect(strip).not.toContainText('ค้นคว้าที่กำลังทำ');
  await expect(strip.getByRole('button')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'งานที่ผ่านมา', exact: true })).toHaveCount(0);
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    const heroBox = await page.locator('.v5-home-stage').boundingBox();
    const stripBox = await strip.boundingBox();
    const libraryBox = await page.locator('#library-title').boundingBox();
    expect(heroBox!.y + heroBox!.height).toBeLessThanOrEqual(stripBox!.y);
    expect(stripBox!.y + stripBox!.height).toBeLessThanOrEqual(libraryBox!.y);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await strip.getByRole('button', { name: 'ดูงานทั้งหมด', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'งานของฉัน', exact: true });
  await expect(drawer.locator('article').first()).toContainText('ค้นคว้าที่กำลังทำ');
  await expect(drawer.locator('article').nth(1)).toContainText('แฟลชการ์ดในคิว');
  await expect(drawer.locator('article').nth(2)).toContainText('แผนเรียนรอโควตา');
  await expect(drawer).toContainText('ประมาณ');
  expect(
    await drawer.evaluate((element) => element.getBoundingClientRect().right),
  ).toBeLessThanOrEqual(320);
  await page.keyboard.press('Escape');
  await expect(strip.getByRole('button', { name: 'ดูงานทั้งหมด', exact: true })).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await strip.screenshot({ path: 'runtime/screenshots/work-queue-20261101.png' });
});

test('history loads on demand, paginates and stays keyboard accessible', async ({ page }) => {
  await fixture(page);
  const pages: number[] = [];
  const jobs = Array.from({ length: 51 }, (_, i) => ({
    job_id: `history-${i}`,
    kind: 'artifact',
    state: 'completed',
    stage: 'completed',
    request: { type: 'summary', topic: `สรุปบทเรียน ${i + 1}` },
    sources: [],
    created_at: new Date(Date.UTC(2026, 10, 1, 0, 60 - i)).toISOString(),
  }));
  await page.route('**/api/member/jobs?*', (route) => {
    const query = new URL(route.request().url()).searchParams;
    const all = query.get('include_completed') === 'true';
    const offset = Number(query.get('offset'));
    const limit = Number(query.get('limit'));
    if (all && limit === 50) pages.push(offset);
    return route.fulfill({
      json: {
        items: all ? jobs.slice(offset, offset + limit) : [],
        total: all ? jobs.length : 0,
        offset,
        limit,
      },
    });
  });
  await page.goto(base);
  const open = page.getByRole('button', { name: 'ดูงานทั้งหมด', exact: true });
  await expect(page.getByText('มีผลลัพธ์พร้อมดู', { exact: true })).toBeVisible();
  expect(pages).toEqual([]);
  await open.click();
  const drawer = page.getByRole('dialog', { name: 'งานของฉัน', exact: true });
  await drawer.getByRole('tab', { name: 'กำลังดำเนินการ', exact: true }).focus();
  await page.keyboard.press('ArrowRight');
  const history = drawer.getByRole('tab', { name: 'ประวัติ', exact: true });
  await expect(history).toBeFocused();
  await expect(history).toHaveAttribute('aria-selected', 'true');
  await expect(drawer.locator('article')).toHaveCount(50);
  await drawer.getByRole('button', { name: 'โหลดงานเพิ่มเติม', exact: true }).click();
  await expect(drawer.locator('article')).toHaveCount(51);
  await expect(drawer.getByRole('button', { name: 'โหลดงานเพิ่มเติม', exact: true })).toHaveCount(
    0,
  );
  expect(pages).toEqual([0, 50]);
  const accessibility = await new AxeBuilder({ page }).include('.job-drawer').analyze();
  expect(accessibility.violations).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(open).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden');
});

test('quota retry failure retains the job and estimates do not permanently disable retry', async ({
  page,
}) => {
  await fixture(page);
  let posts = 0;
  const job = {
    job_id: 'quota-job',
    kind: 'artifact',
    state: 'paused',
    stage: 'paused',
    error_code: 'quota_wait',
    retryable: true,
    request: { type: 'summary', topic: 'สรุปคลิปที่บันทึกไว้' },
    sources: [],
    wait: {
      reason: 'quota_wait',
      time_source: 'estimate',
      estimated_retry_at: '2099-01-01T13:10:00Z',
    },
  };
  await page.route('**/api/member/jobs?*', (route) =>
    route.fulfill({ json: { items: [job], total: 1, offset: 0, limit: 50 } }),
  );
  await page.route('**/api/worker-status', (route) => route.fulfill({ json: { ready: true } }));
  await page.route('**/api/jobs/quota-job/resume', (route) => {
    posts++;
    return route.fulfill({
      status: 429,
      json: { error: { code: 'quota_wait', message: 'Not yet', retryable: true } },
    });
  });
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto(base);
  const strip = page.getByRole('region', { name: 'ติดตามงาน', exact: true });
  await expect(strip).toContainText('พักรอ 1 งาน');
  await page.evaluate(() => document.fonts.ready);
  expect(
    await page.evaluate(() =>
      [...document.fonts].some((font) => font.family === 'Kanit' && font.status === 'loaded'),
    ),
  ).toBe(true);
  await page.screenshot({ path: 'runtime/screenshots/taskbar-home-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'ดูงานทั้งหมด', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'งานของฉัน', exact: true });
  await expect(drawer.getByText(/ลองทำต่อได้ประมาณ/)).toBeVisible();
  await page.screenshot({ path: 'runtime/screenshots/taskbar-drawer-desktop.png' });
  const retry = drawer.getByRole('button', { name: 'ทำต่อ', exact: true });
  await expect(retry).toBeEnabled();
  await retry.click();
  await expect(drawer.getByRole('alert')).toContainText('ยังรอโควตา');
  await expect(
    drawer.getByRole('heading', { name: 'สรุปคลิปที่บันทึกไว้', exact: true }),
  ).toBeVisible();
  expect(posts).toBe(1);
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 390, height: 900 });
  await page.getByRole('heading', { name: 'งานของฉัน', exact: true }).click();
  await page.screenshot({ path: 'runtime/screenshots/taskbar-home-mobile.png', fullPage: true });
});

test('a non-quota pause is never labeled as usage exhaustion', async ({ page }) => {
  await fixture(page);
  const job = {
    job_id: 'worker-pause',
    kind: 'artifact',
    state: 'paused',
    stage: 'paused',
    error_code: 'worker_unavailable',
    retryable: true,
    request: { type: 'quiz', topic: 'แบบฝึกหัดของฉัน' },
    sources: [],
  };
  await page.route('**/api/member/jobs?*', (route) =>
    route.fulfill({ json: { items: [job], total: 1, offset: 0, limit: 50 } }),
  );
  await page.route('**/api/worker-status', (route) => route.fulfill({ json: { ready: false } }));
  await page.goto(base);
  await page.getByRole('button', { name: 'ดูงานทั้งหมด', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'งานของฉัน', exact: true });
  await expect(drawer.getByText('ตัวประมวลผลยังไม่พร้อม', { exact: true })).toBeVisible();
  await expect(drawer.getByText('งบการใช้งานภายในเว็บเต็ม', { exact: true })).toHaveCount(0);
  await expect(drawer.getByRole('button', { name: 'ทำต่อ', exact: true })).toBeEnabled();
});

test('mobile quota details distinguish internal RPD, unknown provider limit and estimated time', async ({
  page,
}) => {
  await fixture(page);
  await page.setViewportSize({ width: 390, height: 900 });
  let reads = 0;
  await page.route('**/api/quota', (route) => {
    reads++;
    return route.fulfill({
      json: {
        accounting_source: 'local_ledger',
        provider_balance_verified: false,
        observed_at: '2026-11-01T07:00:00Z',
        scope: 'member',
        status: 'waiting',
        pools: [
          {
            bucket: 'chat',
            usage: { requests_24h: 2, requests_60s: 1, tokens_60s: 100 },
            blockers: [
              {
                reason: 'local_daily_limit',
                time_source: 'estimate',
                estimated_retry_at: '2099-01-01T00:00:00Z',
              },
              {
                reason: 'provider_rate_limited',
                time_source: 'provider',
                retry_at: '2099-01-02T00:00:00Z',
              },
            ],
          },
        ],
      },
    });
  });
  await page.goto(base);
  expect(reads).toBe(0);
  await page.getByRole('button', { name: 'ดูงานทั้งหมด', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'งานของฉัน', exact: true });
  await drawer.getByText('ตรวจยอดใช้งานภายในระบบ', { exact: true }).click();
  await expect(
    drawer.getByText('งบที่เว็บตั้งไว้: คำขอต่อวัน (RPD)', { exact: false }),
  ).toBeVisible();
  await expect(drawer.getByText(/Google จำกัดการใช้งาน ยังไม่มีหลักฐานว่าเป็น RPM/)).toBeVisible();
  await expect(drawer.getByText(/ไม่รับประกันว่าจะพร้อม/)).toBeVisible();
  await expect(drawer.getByText(/เวลาที่ผู้ให้บริการระบุให้ลองใหม่/)).toBeVisible();
  await expect(drawer.getByText(/ตรวจล่าสุด:/)).toBeVisible();
  await expect(drawer.getByText(/ยอดภายในเว็บ ไม่ใช่ยอดคงเหลือ Google/)).toBeVisible();
  expect(await drawer.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.keyboard.press('Escape');
  await expect(drawer).not.toBeVisible();
});

test('a failed quota refresh removes the old accounting snapshot', async ({ page }) => {
  await fixture(page);
  let reads = 0;
  await page.route('**/api/quota', (route) => {
    reads++;
    if (reads > 1) return route.fulfill({ status: 503, json: { error: { code: 'unavailable' } } });
    return route.fulfill({
      json: {
        accounting_source: 'local_ledger',
        provider_balance_verified: false,
        observed_at: '2026-11-01T07:00:00Z',
        scope: 'member',
        status: 'available',
        pools: [],
      },
    });
  });
  await page.goto(base);
  await page.getByRole('button', { name: 'ดูงานทั้งหมด', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'งานของฉัน', exact: true });
  await drawer.getByText('ตรวจยอดใช้งานภายในระบบ', { exact: true }).click();
  await expect(drawer.getByText(/ตรวจล่าสุด:/)).toBeVisible();
  await drawer.getByRole('button', { name: 'ตรวจยอดอีกครั้ง', exact: true }).click();
  await expect(drawer.getByText(/ยังตรวจยอดภายในไม่ได้/)).toBeVisible();
  await expect(drawer.getByText(/ตรวจล่าสุด:/)).toHaveCount(0);
});
