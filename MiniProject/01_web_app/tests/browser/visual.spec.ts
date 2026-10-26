import { expect, test, type Page } from '@playwright/test';
const base = 'http://127.0.0.1:3003';
const answer = {
  answer: 'คำตอบภาพยังอยู่',
  status: 'answered',
  conversation_id: 'visual-conversation',
  citations: [
    {
      citation_id: 'frame-ocr',
      chunk_id: 'fixture-frame',
      video_id: 'VisualDemo1',
      title: 'ภาพตัวอย่าง',
      start_seconds: 0,
      end_seconds: 1,
      url: 'https://example.invalid',
    },
  ],
  coverage: {
    expected_videos: 1,
    processed_videos: 1,
    expected_chunks: null,
    processed_chunks: 0,
    complete: true,
    notes: [],
  },
};
async function fixture(page: Page, assetStatus = 200, provider = '') {
  let posts = 0;
  let reads = 0;
  let assets = 0;
  let finish = false;
  const methods: string[] = [];
  await page.route('**/__test__/**', (route) =>
    route.fulfill({
      json: {
        member: {
          id: 'A',
          name: 'สมาชิก A',
          email: 'a@example.test',
          role: 'user',
          status: 'active',
        },
        sessionId: 'opaque-A',
        csrfToken: 'csrf-A',
        csrfHeader: 'X-Fixture-CSRF',
        adminSections: [],
      },
    }),
  );
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    methods.push(`${route.request().method()} ${path}`);
    if (path === '/api/videos')
      return route.fulfill({
        json: {
          items: [
            {
              video_id: 'VisualDemo1',
              title: 'คลิปภาพเท่านั้น',
              status: 'no_transcript',
              generation: 1,
              indexed_version: null,
              channel_id: 'c',
              channel_title: 'Fixture',
              canonical_url: 'https://youtu.be/VisualDemo1',
            },
            {
              video_id: 'wD3NSzYtsMc',
              title: 'บทถอดเสียงพร้อม',
              status: 'ready',
              generation: 1,
              indexed_version: 'v1',
            },
            {
              video_id: 'dQw4w9WgXcQ',
              title: 'ไม่มีหลักฐาน',
              status: 'no_transcript',
              generation: 1,
            },
          ],
          total: 3,
          limit: 50,
          offset: 0,
          mode: 'fixture',
        },
      });
    if (path === '/api/chat') {
      posts++;
      return route.fulfill(
        provider ? { status: 202, json: { job_id: 'waiting', state: 'queued' } } : { json: answer },
      );
    }
    if (path === '/api/jobs/waiting') {
      reads++;
      return route.fulfill({
        json: {
          job_id: 'waiting',
          kind: 'chat',
          state: finish ? 'completed' : 'queued',
          stage: 'queued',
          error_code: finish ? null : provider,
          retryable: true,
          attempt_count: 1,
          max_attempts: 3,
          result: finish ? answer : null,
        },
      });
    }
    if (path.startsWith('/api/test-only/frames/')) {
      assets++;
      return route.fulfill({
        status: assetStatus,
        contentType: 'image/png',
        body:
          assetStatus === 200
            ? Buffer.from(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
                'base64',
              )
            : '',
      });
    }
    return route.fulfill({ status: 404, json: { error: { message: 'missing' } } });
  });
  return {
    counts: () => ({ posts, reads, assets }),
    methods,
    finish: () => {
      finish = true;
    },
  };
}
async function send(page: Page) {
  await page.goto(`${base}/?visual=1`);
  await page.getByRole('button', { name: 'วิดีโอของฉัน', exact: true }).click();
  await expect(page.getByRole('checkbox').nth(2)).toBeDisabled();
  await page.getByRole('checkbox').first().check();
  await expect(page.getByText('ถามจากบทถอดเสียงได้แล้ว ส่วนข้อมูลภาพยังไม่ครบ')).toBeVisible();
  await page.getByRole('button', { name: 'ถามจากวิดีโอที่เลือก' }).click();
  await page.getByLabel('คำถามของคุณ').fill('ในภาพมีอะไร');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
}
test('authorized frame, escaped OCR, honest sample coverage and timestamp work in both chats', async ({
  page,
}) => {
  await fixture(page);
  await send(page);
  await expect(page.getByText('คำตอบภาพยังอยู่', { exact: true })).toBeVisible();
  const image = page.locator('.frame-evidence img');
  await expect(image).toHaveAttribute('src', /^blob:/);
  await expect
    .poll(() => image.evaluate((el: HTMLImageElement) => el.naturalWidth))
    .toBeGreaterThan(0);
  await expect(
    page.getByText('<img src=x onerror=alert(1)> ข้อความที่ OCR อ่านได้', { exact: true }),
  ).toBeVisible();
  await expect(page.locator('.evidence-text img')).toHaveCount(0);
  await expect(page.getByText('ตรวจภาพตัวอย่าง 12 ภาพ', { exact: true })).toBeVisible();
  await expect(page.locator('.citation a')).toHaveAttribute(
    'href',
    'https://www.youtube.com/watch?v=VisualDemo1&t=14s',
  );
  await page.locator('.buddy-launcher').click();
  const dialog = page.getByRole('dialog', { name: 'Buddy AI แชตจากคลิป' });
  await expect(dialog.locator('.frame-evidence img')).toHaveAttribute('src', /^blob:/);
  await expect(dialog.getByText('ข้อความที่ OCR อ่านได้', { exact: true })).toBeVisible();
  await expect(dialog.getByText('คำอธิบายภาพจาก AI', { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 375, height: 700 });
  expect(await dialog.evaluate((el) => el.getBoundingClientRect().right)).toBeLessThanOrEqual(375);
});
for (const code of [403, 404])
  test(`image ${code} preserves answer and only retries explicitly`, async ({ page }) => {
    const server = await fixture(page, code);
    await send(page);
    await expect(page.getByText('ไม่มีสิทธิ์ดูภาพ หรือภาพใช้ไม่ได้แล้ว')).toBeVisible();
    await expect(page.getByText('คำตอบภาพยังอยู่', { exact: true })).toBeVisible();
    expect(server.counts().assets).toBe(1);
    await page.getByRole('button', { name: 'ลองโหลดภาพอีกครั้ง' }).click();
    await expect.poll(() => server.counts().assets).toBe(2);
    expect(server.counts().posts).toBe(1);
  });
for (const provider of [
  'generation_rate_limited',
  'generation_provider_busy',
  'provider_rate_limited',
  'provider_unavailable',
  'quota_wait',
])
  test(`${provider} automatically follows existing job through recovery without resubmitting`, async ({
    page,
  }) => {
    const server = await fixture(page, 200, provider);
    await send(page);
    const waiting = page.getByRole('region', { name: 'งานที่พักติดตาม' });
    await expect(page.getByText('กำลังรอคิว ระบบจะติดตามผลให้อัตโนมัติ')).toBeVisible();
    await expect(waiting).toHaveCount(0);
    await expect(page.getByLabel('คำถามของคุณ')).toBeDisabled();
    await expect.poll(() => server.counts().reads).toBeGreaterThanOrEqual(2);
    expect(server.counts().posts).toBe(1);
    server.finish();
    await expect(page.getByText('คำตอบภาพยังอยู่', { exact: true })).toBeVisible();
    await expect(waiting).toHaveCount(0);
    await expect(page.getByLabel('คำถามของคุณ')).toBeEnabled();
    expect(server.counts().posts).toBe(1);
    expect(server.methods.some((value) => value.endsWith('/retry'))).toBe(false);
  });

for (const delivery of ['http', 'failed_job', 'paused_job'] as const) {
  test(`service configuration details stay private in ${delivery} and both chat views`, async ({
    page,
  }) => {
    await fixture(page);
    let posts = 0;
    const code =
      delivery === 'http'
        ? 'free_tier_unverified'
        : delivery === 'failed_job'
          ? 'free_model_unverified'
          : 'quota_pending';
    await page.route('**/api/chat', (route) => {
      posts++;
      return delivery === 'http'
        ? route.fulfill({
            status: 503,
            json: {
              error: {
                code,
                message: 'Gemini Free Tier: internal project/model verification details',
                request_id: 'private-request-id',
                retryable: false,
              },
            },
          })
        : route.fulfill({ status: 202, json: { job_id: 'private-config-job', state: 'queued' } });
    });
    await page.route('**/api/jobs/private-config-job', (route) =>
      route.fulfill({
        json: {
          job_id: 'private-config-job',
          kind: 'chat',
          state: delivery === 'paused_job' ? 'paused' : 'failed',
          stage: delivery === 'paused_job' ? 'paused' : 'failed',
          error_code: code,
          retryable: false,
          result: null,
        },
      }),
    );
    await send(page);
    await expect(page.getByText(/ขณะนี้ผู้ช่วย AI ยังไม่พร้อมให้บริการ/).first()).toBeVisible();
    const forbidden =
      /Gemini|Free Tier|free_tier_unverified|free_model_unverified|quota_pending|private-request-id|internal project/;
    expect(await page.locator('body').innerText()).not.toMatch(forbidden);
    await expect(page.getByRole('button', { name: 'ส่งคำถาม', exact: true })).toBeEnabled();
    await expect(page.locator('.turn')).toHaveCount(0);
    await page.locator('.buddy-launcher').click();
    const buddy = page.getByRole('dialog', { name: 'Buddy AI แชตจากคลิป' });
    await expect(buddy).toContainText('ขณะนี้ผู้ช่วย AI ยังไม่พร้อมให้บริการ');
    expect(await buddy.innerText()).not.toMatch(forbidden);
    expect(posts).toBe(1);
  });
}
