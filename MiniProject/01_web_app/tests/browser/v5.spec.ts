import { expect, test } from '@playwright/test';

for (const width of [390, 1600]) {
  test(
    'v5 artifact paging preserves drafts and limits evidence to the visible item at ' + width,
    async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      const video = {
        video_id: 'dQw4w9WgXcQ',
        title: 'บทเรียนทดสอบ',
        channel_id: 'c',
        status: 'ready',
        canonical_url: 'https://youtu.be/dQw4w9WgXcQ',
      };
      await page.route('**/api/videos?*', (route) =>
        route.fulfill({ json: { items: [video], total: 1, limit: 50, offset: 0, mode: 'custom' } }),
      );
      const requests: unknown[] = [];
      let result: unknown;
      await page.route('**/api/jobs/v5-paging', (route) =>
        route.fulfill({
          json: {
            job_id: 'v5-paging',
            kind: 'artifact',
            state: 'completed',
            stage: 'completed',
            result,
          },
        }),
      );
      await page.route('**/api/learning-artifacts', (route) => {
        const request = route.request().postDataJSON();
        requests.push(request);
        const citations = [1, 2].map((i) => ({
          citation_id: 'c' + i,
          video_id: video.video_id,
          chunk_id: 'chunk' + i,
          title: 'หลักฐาน ' + i,
          start_seconds: i * 12,
          end_seconds: i * 12 + 5,
          url: 'javascript:alert(1)',
        }));
        result = {
          artifacts: [
            {
              artifact_id: request.type,
              type: request.type,
              citations,
              content:
                request.type === 'quiz'
                  ? {
                      questions: [1, 2].map((i) => ({
                        question: 'คำถาม ' + i,
                        answer: 'คำตอบ ' + i,
                        explanation: 'คำอธิบาย ' + i,
                        citations: ['c' + i],
                      })),
                    }
                  : {
                      cards: [1, 2].map((i) => ({
                        front: 'ด้านหน้า ' + i,
                        back: 'ด้านหลัง ' + i,
                        citations: ['c' + i],
                      })),
                    },
            },
          ],
        };
        return route.fulfill({ status: 202, json: { job_id: 'v5-paging', state: 'queued' } });
      });
      await page.goto('http://127.0.0.1:3002');
      await page.getByRole('checkbox').check();
      const nav = page.getByRole('navigation', {
        name: width <= 900 ? 'เมนูมือถือ' : 'เมนูหลัก',
        exact: true,
      });
      await nav.getByRole('button', { name: 'สรุปและแบบฝึกหัด', exact: true }).click();
      await page.getByRole('button', { name: 'แบบทดสอบ', exact: true }).click();
      await page.getByRole('button', { name: 'เริ่มงาน', exact: true }).click();
      await page.getByLabel('คำตอบของคุณ', { exact: true }).fill('ร่างคำตอบแรก');
      const submissions: { answers: string[] }[] = [];
      const keys: string[] = [];
      await page.route('**/api/learning-artifacts/quiz/submit', (route) => {
        submissions.push(route.request().postDataJSON());
        keys.push(route.request().headers()['idempotency-key']);
        if (width === 1600 && submissions.length === 1) return route.abort('failed');
        return route.fulfill({ status: 202, json: { job_id: 'v5-grade', state: 'queued' } });
      });
      await page.route('**/api/jobs/v5-grade', (route) =>
        route.fulfill({
          json: {
            job_id: 'v5-grade',
            kind: 'quiz_grade',
            state: 'completed',
            stage: 'completed',
            result: {
              artifact_id: 'quiz',
              marks: [
                { correct: true, feedback: 'คำตอบถูกต้อง' },
                { correct: false, feedback: 'ควรทบทวนข้อสอง' },
              ],
              correct: 1,
              total: 2,
              answers: submissions[0].answers,
            },
          },
        }),
      );
      await expect(page.locator('.v5r-explanation')).toHaveCount(0);
      await page.getByRole('button', { name: /ข้อถัดไป/ }).click();
      await expect(page.getByLabel('คำตอบของคุณ', { exact: true })).toHaveValue('');
      await page.getByLabel('คำตอบของคุณ', { exact: true }).fill('ร่างคำตอบสุดท้าย');
      await page.getByRole('button', { name: /ข้อก่อนหน้า/ }).click();
      await expect(page.getByLabel('คำตอบของคุณ', { exact: true })).toHaveValue('ร่างคำตอบแรก');
      await page.getByRole('button', { name: /ข้อถัดไป/ }).click();
      await expect(page.getByLabel('คำตอบของคุณ', { exact: true })).toHaveValue('ร่างคำตอบสุดท้าย');
      await page.getByRole('button', { name: 'ส่งคำตอบ', exact: true }).click();
      if (width === 1600) {
        await expect(page.getByRole('alert')).toBeVisible();
        await expect(page.getByLabel('คำตอบของคุณ', { exact: true })).toBeDisabled();
        await page.getByRole('button', { name: 'ส่งคำตอบ', exact: true }).click();
        expect(keys[0]).toBe(keys[1]);
        expect(submissions[0]).toEqual(submissions[1]);
      }

      await expect(page.getByText('ถูก 1 ข้อ · ผิด 1 ข้อ', { exact: true })).toBeVisible();
      expect(submissions[0].answers).toEqual(['ร่างคำตอบแรก', 'ร่างคำตอบสุดท้าย']);
      await page.getByText('เฉลยข้อ 1', { exact: true }).click();
      await expect(page.getByRole('link', { name: /เปิดหลักฐาน หลักฐาน 1/ })).toHaveAttribute(
        'href',
        /youtube\.com\/watch\?v=dQw4w9WgXcQ&t=12s/,
      );
      await expect(page.getByText('คำตอบ 1', { exact: true })).toBeVisible();
      await page.getByText('เฉลยข้อ 2', { exact: true }).click();
      await expect(page.getByText('คำตอบ 2', { exact: true })).toBeVisible();
      await page.getByRole('button', { name: 'สร้างใหม่', exact: true }).click();
      await page.getByRole('button', { name: 'ทบทวนด้วยแฟลชการ์ด', exact: true }).click();
      await page.getByRole('button', { name: 'เริ่มงาน', exact: true }).click();
      await page.locator('.v5r-flash-card summary').click();
      await expect(page.getByText('ด้านหลัง 1', { exact: true })).toBeVisible();
      await page.getByRole('button', { name: /การ์ดถัดไป/ }).click();
      await expect(page.getByText('ด้านหน้า 2', { exact: true })).toBeVisible();
      await expect(page.getByText('ด้านหลัง 2', { exact: true })).not.toBeVisible();
      await expect(page.getByRole('button', { name: /การ์ดถัดไป/ })).toBeDisabled();
      expect(requests).toHaveLength(2);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    },
  );
}
