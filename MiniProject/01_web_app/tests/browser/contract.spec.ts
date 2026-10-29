import { test, expect } from '@playwright/test';
import type { Page, Route } from '@playwright/test';

const liveWeb = 'http://127.0.0.1:3002';
const video = {
  video_id: 'dQw4w9WgXcQ',
  title: 'บทเรียน RAG',
  channel_id: 'c1',
  channel_title: 'Test Channel',
  status: 'ready',
  canonical_url: 'https://youtu.be/dQw4w9WgXcQ',
  thumbnail_url: null,
  published_at: '2026-10-01',
};
const final = {
  status: 'answered',
  answer: 'คำตอบจาก API',
  conversation_id: 'conversation-1',
  sources_available: true,
  citations: [
    {
      citation_id: 'c1',
      video_id: video.video_id,
      chunk_id: 'chunk1',
      title: video.title,
      start_seconds: 12.7,
      end_seconds: 20,
      url: 'javascript:alert(1)',
    },
  ],
  coverage: {
    expected_videos: 1,
    processed_videos: 1,
    expected_chunks: 1,
    processed_chunks: 1,
    complete: true,
    notes: [],
  },
};
const fulfill = (route: Route, data: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: 'application/json',
    headers: { 'X-Adapter-Mode': 'custom' },
    body: JSON.stringify(data),
  });
async function setup(page: Page, chat: (route: Route) => Promise<void>) {
  await page.route('**/api/videos?*', (route) =>
    fulfill(route, { items: [video], total: 1, limit: 50, offset: 0, mode: 'custom' }),
  );
  await page.route('**/api/chat', chat);
  await page.goto(liveWeb);
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'ถาม Buddy จากวิดีโอที่เลือก' }).click();
  await page.getByLabel('คำถามของคุณ').fill('RAG คืออะไร');
}
test('real mode sends selected scope, carries conversation and renders text safely', async ({
  page,
}) => {
  const bodies: Record<string, unknown>[] = [];
  await setup(page, async (route) => {
    bodies.push(route.request().postDataJSON());
    await fulfill(route, { ...final, answer: '<img src=x onerror=alert(1)>' });
  });
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByText('<img src=x onerror=alert(1)>', { exact: true })).toBeVisible();
  expect(bodies[0].scope).toEqual({
    video_ids: [video.video_id],
    channel_ids: [],
    date_from: null,
    date_to: null,
  });
  await expect(page.locator('.answer-text img')).toHaveCount(0);
  await expect(page.getByRole('link', { name: /^เปิดหลักฐาน/ })).toHaveAttribute(
    'href',
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=12s',
  );
  await page.getByLabel('คำถามของคุณ').fill('เพิ่มเติม');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect.poll(() => bodies.length).toBe(2);
  expect(bodies[1].conversation_id).toBe('conversation-1');
  await expect(page.getByText('DEMO · ข้อมูลจำลอง', { exact: true })).toHaveCount(0);
});
test('transport retry preserves both idempotency key and exact frozen input', async ({ page }) => {
  const attempts: { key?: string; body: string | null }[] = [];
  await setup(page, async (route) => {
    attempts.push({
      key: route.request().headers()['idempotency-key'],
      body: route.request().postData(),
    });
    if (attempts.length === 1)
      await fulfill(
        route,
        {
          error: {
            code: 'dependency_unavailable',
            message: 'ชั่วคราว',
            retryable: true,
            request_id: 'r1',
          },
        },
        503,
      );
    else await fulfill(route, final);
  });
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByLabel('คำถามของคุณ')).toHaveValue('RAG คืออะไร');
  await page.getByRole('button', { name: 'ส่งคำขอเดิมซ้ำ', exact: true }).click();
  await expect(page.getByText('คำตอบจาก API', { exact: true })).toBeVisible();
  expect(attempts).toHaveLength(2);
  expect(attempts[0]).toEqual(attempts[1]);
  expect(attempts[0].key).toBeTruthy();
});
for (const state of ['completed', 'partial', 'failed', 'cancelled']) {
  test(`202 polling stops at ${state} and reports its real outcome`, async ({ page }) => {
    let reads = 0;
    await setup(page, (route) => fulfill(route, { job_id: 'j1', state: 'queued' }, 202));
    await page.route('**/api/jobs/j1', (route) => {
      reads++;
      return fulfill(route, {
        job_id: 'j1',
        kind: 'chat',
        state,
        stage: state,
        attempt_count: 1,
        max_attempts: 3,
        result: state === 'completed' || state === 'partial' ? final : null,
        error_code: state === 'failed' ? 'task_timeout' : null,
        retryable: false,
      });
    });
    await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
    if (state === 'completed')
      await expect(page.getByText('คำตอบจาก API', { exact: true })).toBeVisible();
    if (state === 'partial')
      await expect(
        page.getByText('ได้ผลบางส่วน — งานนี้ยังไม่สำเร็จครบถ้วน', { exact: true }),
      ).toBeVisible();
    if (state === 'failed')
      await expect(page.getByRole('alert').filter({ hasText: 'ทำรายการไม่สำเร็จ' })).toBeVisible();
    if (state === 'cancelled')
      await expect(page.getByRole('alert').filter({ hasText: 'งานถูกยกเลิกแล้ว' })).toBeVisible();
    await page.waitForTimeout(1700);
    expect(reads).toBe(1);
    if (state === 'failed' || state === 'cancelled')
      await expect(page.getByText('คำตอบจาก API', { exact: true })).toHaveCount(0);
  });
}
test('library connection failure stays an error without synthetic data', async ({ page }) => {
  await page.route('**/api/videos?*', (route) => route.abort('failed'));
  await page.goto(liveWeb);
  await expect(page.getByRole('alert').filter({ hasText: 'เชื่อมต่อระบบไม่ได้' })).toBeVisible();
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  await expect(page.getByText('DEMO · ข้อมูลจำลอง', { exact: true })).toHaveCount(0);
});
test('deleted historical sources disable citation links', async ({ page }) => {
  await setup(page, (route) => fulfill(route, { ...final, sources_available: false }));
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(
    page.getByText('แหล่งข้อมูลเดิมถูกลบหรือเปลี่ยนแปลงแล้ว', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('link', { name: /^เปิดหลักฐาน/ })).toHaveCount(0);
});
test('pagination exposes videos after first 50 rather than silently dropping them', async ({
  page,
}) => {
  await page.route('**/api/videos?*', (route) => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
    const items = Array.from({ length: offset ? 1 : 50 }, (_, i) => ({
      ...video,
      video_id: `${String(offset + i).padStart(11, '0')}`,
      title: `คลิป ${offset + i}`,
    }));
    return fulfill(route, { items, total: 51, offset, limit: 50, mode: 'custom' });
  });
  await page.goto(liveWeb);
  await expect(page.getByRole('checkbox')).toHaveCount(50);
  await page.getByRole('button', { name: /โหลดคลิปเพิ่มเติม/ }).click();
  await expect(page.getByRole('checkbox')).toHaveCount(51);
});
test('date filters cannot silently widen a selected scope', async ({ page }) => {
  let calls = 0;
  await setup(page, (route) => {
    calls++;
    return fulfill(route, final);
  });
  await page.getByRole('button', { name: 'เลือกหรือเปลี่ยนวิดีโอ', exact: true }).click();
  await page.locator('.v5-filter-disclosure > summary').click();
  await page.getByLabel('ตั้งแต่วันที่').fill('2026-10-02');
  await expect(page.getByRole('button', { name: 'ส่งคำถาม', exact: true })).toBeDisabled();
  await expect(
    page.getByRole('status').filter({ hasText: 'คลิปที่เลือกไม่ตรงตัวกรอง' }),
  ).toBeVisible();
  expect(calls).toBe(0);
});
test('comparison blocks a single selected video before creating work', async ({ page }) => {
  let calls = 0;
  await setup(page, (route) => fulfill(route, final));
  await page.route('**/api/analysis', (route) => {
    calls++;
    return fulfill(route, { job_id: 'j1', state: 'queued' }, 202);
  });
  await page.getByRole('button', { name: 'สรุปและแบบฝึกหัด', exact: true }).click();
  await learningSettings(page);
  await page.getByLabel('ประเภทงาน').selectOption('compare');
  await expect(page.getByRole('button', { name: 'เริ่มงาน', exact: true })).toBeDisabled();
  await expect(page.getByRole('status').filter({ hasText: 'อย่างน้อย 2 คลิป' })).toBeVisible();
  expect(calls).toBe(0);
});
test('cancelled pending task observes cancellation and unlocks the form', async ({ page }) => {
  let cancelled = false;
  await setup(page, (route) => fulfill(route, { job_id: 'j1', state: 'queued' }, 202));
  const job = () => ({
    job_id: 'j1',
    kind: 'chat',
    state: cancelled ? 'cancelled' : 'running',
    stage: cancelled ? 'cancelled' : 'running',
    attempt_count: 1,
    max_attempts: 3,
    result: null,
    error_code: null,
    retryable: false,
  });
  await page.route('**/api/jobs/j1', (route) => fulfill(route, job()));
  await page.route('**/api/jobs/j1/cancel', (route) => {
    cancelled = true;
    return fulfill(route, job());
  });
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await page.getByRole('button', { name: 'ขอยกเลิกงาน', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'งานถูกยกเลิกแล้ว' })).toBeVisible();
  await expect(page.getByLabel('คำถามของคุณ')).toBeEnabled();
  expect(cancelled).toBe(true);
});
test('retryable import follows replacement job and refreshes readiness', async ({ page }) => {
  let retried = false;
  await page.route('**/api/videos?*', (route) =>
    fulfill(route, {
      items: [{ ...video, status: retried ? 'ready' : 'failed' }],
      total: 1,
      limit: 50,
      offset: 0,
      mode: 'custom',
    }),
  );
  await page.route('**/api/videos/import', (route) =>
    fulfill(
      route,
      {
        jobs: [
          {
            input_index: 0,
            outcome: 'existing',
            video_id: video.video_id,
            job_id: 'old',
            error_code: null,
          },
        ],
        mode: 'custom',
      },
      202,
    ),
  );
  await page.route('**/api/jobs/old', (route) =>
    fulfill(route, {
      job_id: 'old',
      kind: 'import',
      state: 'failed',
      stage: 'failed',
      result: null,
      error_code: 'provider_timeout',
      retryable: true,
    }),
  );
  await page.route('**/api/jobs/old/retry', (route) => {
    retried = true;
    return fulfill(route, { job_id: 'new', state: 'queued' }, 202);
  });
  await page.route('**/api/jobs/new', (route) =>
    fulfill(route, {
      job_id: 'new',
      kind: 'import',
      state: 'completed',
      stage: 'ready',
      result: null,
      error_code: null,
      retryable: false,
    }),
  );
  await page.goto(liveWeb);
  await page.getByLabel('ลิงก์วิดีโอ YouTube').fill(video.canonical_url);
  await page.getByRole('button', { name: 'เพิ่มคลิป (เพิ่มวิดีโอ)', exact: true }).click();
  await page.getByRole('button', { name: 'ลองนำเข้าใหม่' }).click();
  await expect(page.getByRole('checkbox')).toBeEnabled();
  await expect(
    page
      .getByRole('region', { name: 'ผลนำเข้ารายลิงก์' })
      .getByText('พร้อมใช้งาน', { exact: true }),
  ).toBeVisible();
});
test('chat error with a completed durable job resolves by GET without resubmitting', async ({
  page,
}) => {
  let submissions = 0;
  let reads = 0;
  await setup(page, (route) => {
    submissions++;
    return fulfill(
      route,
      {
        error: {
          code: 'dependency_error',
          message: 'ติดตามงานเดิม',
          retryable: true,
          request_id: 'r1',
          job_id: 'saved-job',
        },
      },
      502,
    );
  });
  await page.route('**/api/jobs/saved-job', (route) => {
    reads++;
    return fulfill(route, {
      job_id: 'saved-job',
      kind: 'chat',
      state: 'completed',
      stage: 'completed',
      result: final,
    });
  });
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByText('คำตอบจาก API', { exact: true })).toBeVisible();
  expect(submissions).toBe(1);
  expect(reads).toBe(1);
});

test('a failed durable chat job unlocks the form and allows a new question', async ({ page }) => {
  let submissions = 0;
  await setup(page, (route) => {
    submissions++;
    return submissions === 1
      ? fulfill(
          route,
          {
            error: {
              code: 'incomplete_index',
              message: 'Chat failed',
              retryable: false,
              job_id: 'failed-chat',
            },
          },
          502,
        )
      : fulfill(route, final);
  });
  await page.route('**/api/jobs/failed-chat', (route) =>
    fulfill(route, {
      job_id: 'failed-chat',
      kind: 'chat',
      state: 'failed',
      stage: 'failed',
      error_code: 'incomplete_index',
      retryable: false,
    }),
  );
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'ข้อมูลคลิปยังไม่พร้อม' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'ส่งคำถาม', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'เริ่มบทสนทนาใหม่', exact: true })).toBeEnabled();
  await page.getByLabel('คำถามของคุณ').fill('คำถามใหม่');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByText('คำตอบจาก API', { exact: true })).toBeVisible();
  expect(submissions).toBe(2);
});

test('provider downtime explains the failure and allows an explicit new submission', async ({
  page,
}) => {
  let submissions = 0;
  await setup(page, (route) => {
    submissions++;
    return submissions === 1
      ? fulfill(
          route,
          {
            error: {
              code: 'generation_provider_busy',
              message: 'Provider unavailable',
              retryable: true,
              job_id: 'busy-chat',
            },
          },
          503,
        )
      : fulfill(route, final);
  });
  await page.route('**/api/jobs/busy-chat', (route) =>
    fulfill(route, {
      job_id: 'busy-chat',
      kind: 'chat',
      state: 'failed',
      stage: 'failed',
      error_code: 'generation_provider_busy',
      retryable: true,
    }),
  );
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(
    page.getByRole('alert').filter({ hasText: 'ไม่พร้อมให้บริการชั่วคราว' }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'ส่งคำถาม', exact: true })).toBeEnabled();
  expect(submissions).toBe(1);
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByText('คำตอบจาก API', { exact: true })).toBeVisible();
  expect(submissions).toBe(2);
});

async function learningSettings(page: Page) {
  const create = page.getByRole('button', { name: 'สร้างใหม่', exact: true });
  if (await create.isVisible()) await create.click();
  const settings = page.locator('.v5-learning-settings');
  if ((await settings.getAttribute('open')) === null) await settings.locator('summary').click();
}
