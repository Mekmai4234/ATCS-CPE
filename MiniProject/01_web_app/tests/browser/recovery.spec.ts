import { expect, test, type Page } from '@playwright/test';

const base = 'http://127.0.0.1:3003';
async function setup(page: Page) {
  const calls: { path: string; body: any }[] = [];
  await page.route('**/__test__/session', (route) =>
    route.fulfill({
      json: {
        member: {
          id: 'audit',
          name: 'ผู้ทดสอบ',
          email: 'audit@example.test',
          role: 'user',
          status: 'active',
        },
        sessionId: 'audit-session',
        csrfToken: 'audit-csrf',
        csrfHeader: 'X-Fixture-CSRF',
        adminSections: [],
      },
    }),
  );
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    calls.push({ path, body: route.request().postDataJSON() });
    if (path === '/api/videos')
      return route.fulfill({
        json: {
          mode: 'custom',
          total: 1,
          limit: 50,
          offset: 0,
          items: [
            {
              video_id: 'dQw4w9WgXcQ',
              title: 'บทเรียนตัวอย่าง',
              status: 'ready',
              channel_id: 'channel',
              channel_title: 'ช่องตัวอย่าง',
              published_at: '2026-10-01',
              generation: 1,
              indexed_version: 'v1',
              canonical_url: 'https://youtu.be/dQw4w9WgXcQ',
              thumbnail_url: null,
            },
          ],
        },
      });
    if (path === '/api/chat')
      return route.fulfill({
        status: 503,
        json: {
          error: {
            code: 'free_tier_unverified',
            message: 'internal diagnostic',
            retryable: false,
          },
        },
      });
    if (path === '/api/analysis' || path === '/api/learning-artifacts')
      return route.fulfill({ status: 202, json: { job_id: 'done', state: 'queued' } });
    if (path === '/api/jobs/done')
      return route.fulfill({
        json: {
          job_id: 'done',
          kind: 'analysis',
          state: 'completed',
          stage: 'completed',
          result: { answer: 'ผลการเรียนรู้', citations: [] },
        },
      });
    return route.fulfill({
      status: 404,
      json: { error: { code: 'not_found', message: 'missing', retryable: false } },
    });
  });
  await page.goto(`${base}/chat`);
  await page.getByRole('button', { name: 'เลือกหรือเปลี่ยนวิดีโอ', exact: true }).click();
  await page.getByRole('checkbox', { name: 'เลือก บทเรียนตัวอย่าง', exact: true }).check();
  return calls;
}

test('new conversation clears the previous error in full and floating chat', async ({ page }) => {
  await setup(page);
  await page.getByLabel('คำถามของคุณ', { exact: true }).fill('คำถามตัวอย่าง');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.locator('.chat-panel [role="alert"]')).toBeVisible();
  await page.getByRole('button', { name: 'เริ่มบทสนทนาใหม่', exact: true }).click();
  await expect(page.locator('.chat-panel [role="alert"]')).toHaveCount(0);
  await page.locator('.buddy-launcher').click();
  await expect(page.locator('.buddy-panel [role="alert"]')).toHaveCount(0);
  await expect(page.getByLabel('ข้อความถึง Buddy', { exact: true })).toHaveValue('');
});

test('a hidden invalid study duration cannot block summary or quiz', async ({ page }) => {
  const calls = await setup(page);
  await page.getByRole('button', { name: 'สรุปและแบบฝึกหัด', exact: true }).click();
  await learningSettings(page);
  await page.getByRole('combobox', { name: 'ประเภทงาน', exact: true }).selectOption('study_plan');
  await page.getByLabel('จำนวนวัน', { exact: true }).fill('0');
  await learningSettings(page);
  await page.getByRole('combobox', { name: 'ประเภทงาน', exact: true }).selectOption('summary');
  await page.getByRole('button', { name: 'เริ่มงาน', exact: true }).click();
  await expect.poll(() => calls.filter((c) => c.path === '/api/analysis').length).toBe(1);
  await expect(page.getByRole('button', { name: 'สร้างใหม่', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'สร้างใหม่', exact: true }).click();
  await learningSettings(page);
  await page.getByRole('combobox', { name: 'ประเภทงาน', exact: true }).selectOption('quiz');
  await page.getByRole('button', { name: 'เริ่มงาน', exact: true }).click();
  await expect.poll(() => calls.filter((c) => c.path === '/api/learning-artifacts').length).toBe(1);
  const quiz = calls.find((c) => c.path === '/api/learning-artifacts')!.body;
  expect(quiz.days === undefined || (quiz.days >= 1 && quiz.days <= 90)).toBe(true);
});

test('confirmed cancellation unlocks a task whose status polling failed', async ({ page }) => {
  await setup(page);
  let cancellationConfirmed = false;
  let cancellations = 0;
  await page.route('**/api/chat', (route) =>
    route.fulfill({ status: 202, json: { job_id: 'pending', state: 'queued' } }),
  );
  await page.route('**/api/jobs/pending', (route) =>
    route.fulfill({
      status: 502,
      json: { error: { code: 'status_unavailable', message: 'unavailable', retryable: false } },
    }),
  );
  await page.route('**/api/jobs/pending/cancel', (route) => {
    cancellations++;
    return route.fulfill({
      json: {
        job_id: 'pending',
        kind: 'chat',
        state: cancellationConfirmed ? 'cancelled' : 'running',
        stage: cancellationConfirmed ? 'cancelled' : 'running',
        result: null,
      },
    });
  });
  await page.getByLabel('คำถามของคุณ', { exact: true }).fill('คำถามค้าง');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByRole('button', { name: 'ติดตามผลอีกครั้ง', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'ขอยกเลิกงาน', exact: true }).click();
  await expect.poll(() => cancellations).toBe(1);
  await expect(page.getByLabel('คำถามของคุณ', { exact: true })).toBeDisabled();
  cancellationConfirmed = true;
  await page.getByRole('button', { name: 'ขอยกเลิกงาน', exact: true }).click();
  await expect(page.getByLabel('คำถามของคุณ', { exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'ติดตามผลอีกครั้ง', exact: true })).toHaveCount(0);
});

test('active filters remain visible on home and unusable selection is explained in both chats', async ({
  page,
}) => {
  await setup(page);
  await page.locator('.v5-filter-disclosure > summary').click();
  await page.getByLabel('ตั้งแต่วันที่', { exact: true }).fill('2026-10-02');
  await expect(page.locator('.video-card')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'ส่งคำถาม', exact: true })).toBeDisabled();
  await expect(
    page.getByText('คลิปที่เลือกไม่ตรงตัวกรอง กรุณาล้างตัวกรองหรือเลือกคลิปใหม่', { exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'หน้าแรก', exact: true }).click();
  await expect(page.getByRole('button', { name: 'ล้างตัวกรอง', exact: true })).toBeVisible();
  await page.locator('.buddy-launcher').click();
  await expect(
    page
      .locator('.buddy-panel')
      .getByText('คลิปที่เลือกไม่ตรงตัวกรอง กรุณาล้างตัวกรองหรือเลือกคลิปใหม่', { exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'ปิดหน้าต่างแชต', exact: true }).click();
  await page.getByRole('button', { name: 'ล้างตัวกรอง', exact: true }).click();
  await expect(page.locator('.video-card')).toHaveCount(1);
  await expect(
    page.getByRole('checkbox', { name: 'เลือก บทเรียนตัวอย่าง', exact: true }),
  ).toBeChecked();
});

test('import rejection explains the correction instead of rendering internal codes', async ({
  page,
}) => {
  await setup(page);
  await page.route('**/api/videos/import', (route) =>
    route.fulfill({
      json: {
        jobs: [
          { input_index: 0, outcome: 'rejected', error_code: 'invalid_youtube_url', job_id: null },
        ],
        mode: 'custom',
      },
    }),
  );
  await page.getByRole('button', { name: 'วิดีโอของฉัน', exact: true }).click();
  await page.getByLabel('ลิงก์วิดีโอ YouTube', { exact: true }).fill('https://example.test/video');
  await page.getByRole('button', { name: 'เพิ่มคลิป (เพิ่มวิดีโอ)', exact: true }).click();
  await expect(page.getByLabel('ผลนำเข้ารายลิงก์')).toContainText('กรุณาใช้ลิงก์วิดีโอ YouTube');
  await expect(page.getByLabel('ผลนำเข้ารายลิงก์')).not.toContainText('invalid_youtube_url');
});

async function learningSettings(page: Page) {
  const create = page.getByRole('button', { name: 'สร้างใหม่', exact: true });
  if (await create.isVisible()) await create.click();
  const settings = page.locator('.v5-learning-settings');
  if ((await settings.getAttribute('open')) === null) await settings.locator('summary').click();
}
