import { expect, test } from '@playwright/test';
import type { Page, Route } from '@playwright/test';

const first = 'dQw4w9WgXcQ';
const second = 'wD3NSzYtsMc';
const linkTo = (id: string) => `.turn a[href*="v=${id}&"]`;

async function sourceServer(page: Page) {
  let generation = 1;
  let version = 'v1';
  let present = true;
  let failDelete = false;
  let failJobRead = false;
  let answerGate: Promise<void> | null = null;
  const history = new Map<string, { generation: number; version: string; result: object }>();
  const json = (route: Route, data: unknown, status = 200) =>
    route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(data),
    });
  const video = (id: string) => ({
    video_id: id,
    title: id === first ? 'บทเรียนแรก' : 'บทเรียนที่สอง',
    status: 'ready',
    channel_id: 'c1',
    channel_title: 'Test',
    canonical_url: `https://youtu.be/${id}`,
    thumbnail_url: null,
    published_at: '2026-10-01',
    generation: id === first ? generation : 1,
    indexed_version: id === first ? version : 'v1',
  });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/videos') {
      const items = [present ? video(first) : null, video(second)].filter(Boolean);
      return json(route, { items, total: items.length, limit: 50, offset: 0, mode: 'custom' });
    }
    if (path === '/api/chat') {
      const job_id = `answer-${history.size + 1}`;
      const result = {
        job_id,
        conversation_id: 'conversation',
        status: 'answered',
        answer: `คำตอบ ${job_id}`,
        sources_available: true,
        citations: [first, second].map((id, i) => ({
          citation_id: `c${i}`,
          chunk_id: `chunk-${generation}-${id}`,
          video_id: id,
          title: video(id).title,
          start_seconds: 10,
          end_seconds: 20,
          url: '',
        })),
        coverage: {
          expected_videos: 2,
          processed_videos: 2,
          expected_chunks: 2,
          processed_chunks: 2,
          complete: true,
          notes: [],
        },
      };
      history.set(job_id, { generation, version, result });
      if (answerGate) {
        const gate = answerGate;
        answerGate = null;
        await gate;
      }
      return json(route, result);
    }
    if (path === `/api/videos/${first}`) {
      if (failDelete)
        return json(
          route,
          { error: { message: 'ลบไม่สำเร็จ', code: 'unavailable', retryable: true } },
          503,
        );
      present = false;
      return json(route, { job_id: 'delete', state: 'queued' }, 202);
    }
    if (path === '/api/videos/import') {
      present = true;
      generation++;
      version = `v${generation}`;
      return json(
        route,
        {
          jobs: [
            {
              input_index: 0,
              outcome: 'accepted',
              video_id: first,
              job_id: 'import',
              error_code: null,
            },
          ],
          mode: 'custom',
        },
        202,
      );
    }
    const id = path.split('/').pop()!;
    if (history.has(id)) {
      if (failJobRead)
        return json(
          route,
          { error: { code: 'unavailable', message: 'อ่านสถานะไม่ได้', retryable: true } },
          503,
        );
      const old = history.get(id)!;
      return json(route, {
        job_id: id,
        kind: 'chat',
        state: 'completed',
        stage: 'completed',
        result: old.result,
        sources_available: present && old.generation === generation && old.version === version,
      });
    }
    return json(route, {
      job_id: id,
      kind: id === 'delete' ? 'delete' : 'import',
      state: 'completed',
      stage: id === 'import' ? 'ready' : 'completed',
      result: null,
    });
  });
  await page.goto('http://127.0.0.1:3002');
  await page.getByRole('checkbox').nth(0).check();
  await page.getByRole('checkbox').nth(1).check();
  await page.getByRole('button', { name: 'ถาม Buddy จากวิดีโอที่เลือก' }).click();
  await page.getByLabel('คำถามของคุณ').fill('RAG คืออะไร');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.locator(linkTo(first))).toHaveCount(1);
  await page.getByRole('button', { name: 'เลือกหรือเปลี่ยนวิดีโอ', exact: true }).click();
  return {
    replaceExternally: () => {
      generation++;
    },
    reindexExternally: () => {
      version = 'v2';
    },
    deleteExternally: () => {
      present = false;
    },
    rejectDelete: () => {
      failDelete = true;
    },
    rejectJobReads: () => {
      failJobRead = true;
    },
    holdNextAnswer: () => {
      let release!: () => void;
      answerGate = new Promise<void>((resolve) => {
        release = resolve;
      });
      return release;
    },
  };
}

test('deletion invalidates old citations, preserves other sources and never revives on reimport', async ({
  page,
}) => {
  await sourceServer(page);
  await page.getByRole('button', { name: 'ลบ บทเรียนแรก', exact: true }).click();
  await page.getByRole('button', { name: 'ยืนยันลบคลิป', exact: true }).click();
  await expect(page.locator(linkTo(first))).toHaveCount(0);
  await expect(page.locator(linkTo(second))).toHaveCount(1);
  await expect(
    page.locator('.turn').getByText('แหล่งข้อมูลเดิมถูกลบหรือเปลี่ยนแปลงแล้ว', { exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: /วิดีโอของฉัน/ }).click();
  await page.getByLabel('ลิงก์วิดีโอ YouTube').fill(`https://youtu.be/${first}`);
  await page.getByRole('button', { name: 'เพิ่มคลิป (เพิ่มวิดีโอ)', exact: true }).click();
  await expect(page.getByRole('checkbox')).toHaveCount(2);
  await page.getByRole('checkbox', { name: 'เลือก บทเรียนแรก', exact: true }).check();
  await page.getByRole('button', { name: 'ถาม Buddy จากวิดีโอที่เลือก' }).click();
  await expect(page.locator(linkTo(first))).toHaveCount(0);
  await page.getByLabel('คำถามของคุณ').fill('คำถามจากเวอร์ชันใหม่');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.locator('.turn')).toHaveCount(2);
  await expect(page.locator('.turn').first().locator(`a[href*="v=${first}&"]`)).toHaveCount(0);
  await expect(page.locator('.turn').last().locator(`a[href*="v=${first}&"]`)).toHaveCount(1);
});

for (const change of ['replaceExternally', 'reindexExternally', 'deleteExternally'] as const) {
  test(`refresh revalidates historical source identity after ${change}`, async ({ page }) => {
    const server = await sourceServer(page);
    server[change]();
    await page.getByRole('button', { name: /รีเฟรชคลัง/ }).click();
    await expect(page.locator(linkTo(first))).toHaveCount(0);
    await expect(page.locator(linkTo(second))).toHaveCount(1);
  });
}

test('rejected deletion does not invalidate usable citations', async ({ page }) => {
  const server = await sourceServer(page);
  server.rejectDelete();
  await page.getByRole('button', { name: 'ลบ บทเรียนแรก', exact: true }).click();
  await page.getByRole('button', { name: 'ยืนยันลบคลิป', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'ลบไม่สำเร็จ' })).toBeVisible();
  await expect(page.locator(linkTo(first))).toHaveCount(1);
});

test('failed history revalidation is visible without discarding old answers', async ({ page }) => {
  const server = await sourceServer(page);
  server.rejectJobReads();
  await page.getByRole('button', { name: /รีเฟรชคลัง/ }).click();
  await expect(
    page.getByText('ตรวจสอบสถานะแหล่งข้อมูลของผลเก่าไม่ครบ กรุณารีเฟรชอีกครั้ง', { exact: true }),
  ).toBeVisible();
  await expect(page.getByText('คำตอบ answer-1', { exact: true })).toBeVisible();
});

test('a late answer cannot publish live links to a source deleted while it was pending', async ({
  page,
}) => {
  const server = await sourceServer(page);
  const release = server.holdNextAnswer();
  await page.getByLabel('คำถามของคุณ').fill('คำถามที่ยังรอคำตอบ');
  const submitted = page.waitForRequest('**/api/chat');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await submitted;
  await page.getByRole('button', { name: 'เลือกหรือเปลี่ยนวิดีโอ', exact: true }).click();
  await page.getByRole('button', { name: 'ลบ บทเรียนแรก', exact: true }).click();
  await page.getByRole('button', { name: 'ยืนยันลบคลิป', exact: true }).click();
  await expect(page.getByRole('checkbox')).toHaveCount(1);
  release();
  await expect(page.locator('.turn')).toHaveCount(2);
  await expect(page.locator(linkTo(first))).toHaveCount(0);
  await expect(page.locator(linkTo(second))).toHaveCount(2);
});
