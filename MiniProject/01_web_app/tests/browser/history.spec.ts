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

test('history search, pagination and reloadable detail preserve scope on explicit continuation', async ({
  page,
}) => {
  const posts = await fixture(page);
  await page.goto(`${base}/history`);
  await expect(page.getByRole('heading', { name: 'บทสนทนาที่ผ่านมา', exact: true })).toBeVisible();
  await expect(page.locator('.history-list article')).toHaveCount(20);
  await page.getByRole('button', { name: 'หน้าถัดไป', exact: true }).click();
  await expect(page.locator('.history-list article')).toHaveCount(1);
  await page.getByLabel('ค้นหาจากชื่อบทสนทนา', { exact: true }).fill('คำถามที่ 3');
  await page.getByRole('button', { name: 'ค้นหาประวัติ', exact: true }).click();
  await expect(page.locator('.history-list article')).toHaveCount(1);
  await page.getByRole('button', { name: 'เปิดบทสนทนา คำถามที่ 3', exact: true }).click();
  await expect(page).toHaveURL(/\/chat\/chat-3$/);
  await expect(page.locator('.turn').getByText('คำตอบที่บันทึกไว้', { exact: true })).toBeVisible();
  await expect(page.getByLabel('คำถามของคุณ', { exact: true })).toBeHidden();
  expect(posts).toHaveLength(0);
  await page.reload();
  await expect(page.locator('.turn').getByText('คำตอบที่บันทึกไว้', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'ถามต่อในบทสนทนานี้', exact: true }).click();
  await page.getByLabel('คำถามของคุณ', { exact: true }).fill('ขอรายละเอียดเพิ่มเติม');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByText('คำตอบต่อเนื่องจากประวัติ', { exact: true })).toBeVisible();
  expect(posts).toHaveLength(1);
  expect(posts[0].conversation_id).toBe('chat-3');
  expect(posts[0].scope).toEqual(scope);
  await page.getByRole('button', { name: 'เริ่มบทสนทนาใหม่', exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.locator('.turn')).toHaveCount(0);
});

test('foreign history is denied and other learning tools remain visible after reading history', async ({
  page,
}) => {
  const posts = await fixture(page);
  await page.goto(`${base}/chat/foreign`);
  await expect(page.getByRole('alert')).toContainText('ไม่พบบทสนทนานี้');
  await expect(page.locator('.turn')).toHaveCount(0);
  expect(posts).toHaveLength(0);
  await page.goto(`${base}/chat/chat-1`);
  await expect(page.getByText('คำตอบที่บันทึกไว้', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'สรุปและแบบฝึกหัด', exact: true }).click();
  await expect(page.getByLabel('หัวข้อหรือคำแนะนำเพิ่มเติม', { exact: true })).toBeVisible();
});

test('question submission reveals pending answer and completed answer without manual scrolling', async ({
  page,
}) => {
  await fixture(page);
  let finished = false;
  await page.route('**/api/chat', (route) =>
    route.fulfill({ status: 202, json: { job_id: 'waiting', state: 'queued' } }),
  );
  await page.route('**/api/jobs/waiting', (route) =>
    route.fulfill({
      json: {
        job_id: 'waiting',
        kind: 'chat',
        state: finished ? 'completed' : 'running',
        stage: 'running',
        result: finished
          ? { answer: 'คำตอบล่าสุดที่มองเห็นได้', conversation_id: 'latest', citations: [] }
          : null,
      },
    }),
  );
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(`${base}/chat`);
  await page.getByRole('checkbox', { name: 'เลือก บทเรียนส่วนตัว', exact: true }).check();
  await page.getByLabel('คำถามของคุณ', { exact: true }).fill('ช่วยอธิบายบทเรียน');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByText('Buddy กำลังหาคำตอบ…', { exact: true })).toBeInViewport();
  await expect(
    page.getByRole('button', { name: 'เลือกหรือเปลี่ยนวิดีโอ', exact: true }),
  ).toHaveAttribute('aria-expanded', 'false');
  finished = true;
  await expect(page.getByText('คำตอบล่าสุดที่มองเห็นได้', { exact: true })).toBeInViewport();
});

test('Video Buddy branding is consistent across public and member routes', async ({ page }) => {
  await fixture(page);
  for (const path of ['/', '/history', '/help', '/terms', '/privacy']) {
    await page.goto(`${base}${path}`);
    await expect(page.locator('.buddy-logo')).toContainText('Video Buddy');
    await expect(page.locator('body')).not.toContainText('RAG Buddy');
  }
});

test('reading an older full-page answer is not interrupted when a new answer arrives', async ({
  page,
}) => {
  await fixture(page);
  let posts = 0,
    finished = false;
  await page.route('**/api/chat', (route) =>
    ++posts === 1
      ? route.fulfill({
          json: { answer: 'คำตอบเก่า\n'.repeat(160), conversation_id: 'reading', citations: [] },
        })
      : route.fulfill({ status: 202, json: { job_id: 'reading-job', state: 'queued' } }),
  );
  await page.route('**/api/jobs/reading-job', (route) =>
    route.fulfill({
      json: {
        job_id: 'reading-job',
        kind: 'chat',
        state: finished ? 'completed' : 'running',
        stage: 'running',
        result: finished
          ? { answer: 'คำตอบใหม่ขณะอ่าน', conversation_id: 'reading', citations: [] }
          : null,
      },
    }),
  );
  await page.goto(`${base}/chat`);
  await page.getByRole('checkbox').check();
  await page.getByLabel('คำถามของคุณ', { exact: true }).fill('คำถามแรก');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.locator('.turn')).toHaveCount(1);
  await page.getByLabel('คำถามของคุณ', { exact: true }).fill('คำถามที่สอง');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByText('Buddy กำลังหาคำตอบ…', { exact: true })).toBeVisible();
  await page.locator('.turn').first().scrollIntoViewIfNeeded();
  await page.keyboard.press('PageUp');
  // Wait for the browser's native keyboard scroll to settle before comparing.
  let previousY = -1;
  await expect
    .poll(async () => {
      const y = await page.evaluate(() => scrollY);
      const stable = Math.abs(y - previousY) < 1;
      previousY = y;
      return stable;
    })
    .toBe(true);
  const before = await page.evaluate(() => scrollY);
  finished = true;
  await expect(page.locator('.turn')).toHaveCount(2);
  await expect(page.getByRole('button', { name: 'ไปคำตอบล่าสุด ↓', exact: true })).toBeVisible();
  expect(Math.abs((await page.evaluate(() => scrollY)) - before)).toBeLessThan(100);
  await page.getByRole('button', { name: 'ไปคำตอบล่าสุด ↓', exact: true }).click();
  await expect(page.getByText('คำตอบใหม่ขณะอ่าน', { exact: true })).toBeInViewport();
});
