import { test, expect, type Page } from '@playwright/test';
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
  await expect(page.getByText(/ตัวประมวลผลยังไม่พร้อม/)).toBeVisible();
  await page.reload();
  await expect(
    page
      .getByRole('region', { name: 'ติดตามงาน', exact: true })
      .getByRole('button', { name: 'ดูงาน', exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/ตัวประมวลผลยังไม่พร้อม/)).toBeVisible();
  finished = true;
  await page
    .getByRole('region', { name: 'ติดตามงาน', exact: true })
    .getByRole('button', { name: 'ดูงาน', exact: true })
    .click();
  await expect(page.getByText('ผลจากงานเดิม', { exact: true })).toBeVisible();
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
  await page.getByRole('button', { name: 'งานที่ผ่านมา', exact: true }).click();
  await page.getByRole('region', { name: 'งานของฉัน' }).locator('summary').click();
  await page.getByRole('button', { name: 'เปิดผลลัพธ์', exact: true }).click();
  await expect(page.getByText('1. คำถามที่กู้คืน', { exact: true })).toBeVisible();
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
      wait: { estimated_retry_at: '2026-11-01T13:10:58Z', reason: 'quota_wait' },
    },
  ];
  await page.route('**/api/member/jobs?*', (route) =>
    route.fulfill({ json: { items: jobs, total: 3, limit: 50, offset: 0 } }),
  );
  await page.goto(base);
  const strip = page.getByRole('region', { name: 'ติดตามงาน', exact: true });
  await expect(strip).toContainText('กำลังทำ 1 · รอคิว 1 · พักรอ 1');
  await expect(strip.getByText('ค้นคว้าที่กำลังทำ', { exact: false })).toBeVisible();
  await page.getByRole('region', { name: 'งานของฉัน', exact: true }).locator('summary').click();
  await expect(page.getByRole('region', { name: 'งานของฉัน', exact: true })).toContainText(
    'พร้อมประมาณ',
  );
  await expect(strip.getByRole('button', { name: 'ดูงาน', exact: true })).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await strip.screenshot({ path: 'runtime/screenshots/work-queue-20261101.png' });
});
