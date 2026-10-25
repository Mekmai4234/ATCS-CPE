import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

async function openMemberHome(page: Page) {
  // Exercise the production layout without the demo banner that concealed this bug.
  // Only identity and inventory responses are fixtures; no provider calls are made.
  await page.route('**/__test__/session', (route) =>
    route.fulfill({
      json: {
        member: {
          id: 'navigation-test',
          name: 'Navigation test',
          email: 'nav@example.test',
          role: 'user',
          status: 'active',
        },
        sessionId: 'navigation-session',
        csrfToken: 'navigation-csrf',
        csrfHeader: 'X-Test-CSRF',
        adminSections: [],
      },
    }),
  );
  await page.route('**/api/videos?*', (route) =>
    route.fulfill({
      json: {
        items: [],
        total: 0,
        limit: 50,
        offset: 0,
        mode: 'custom',
      },
    }),
  );
  await page.goto('http://127.0.0.1:3003/');
  await expect(page.getByRole('heading', { name: /ดูน้อยลง/ })).toBeVisible();
  await expect(page.locator('.demo-banner')).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
}

for (const [width, height] of [
  [375, 812],
  [768, 1024],
  [1024, 768],
  [1280, 720],
  [1440, 900],
  [1536, 864],
  [1920, 1080],
  [2560, 1440],
]) {
  test(`home artwork cannot cover navigation at ${width}x${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await openMemberHome(page);
    const nav = page.getByRole('navigation', { name: 'เมนูพื้นที่เรียนรู้' });
    for (const [label, url, title] of [
      ['คลังวิดีโอ', '/library', 'คลังวิดีโอของคุณ'],
      ['ถามจากคลิป', '/chat', 'ความรู้ เริ่มจากคำถาม'],
      ['วิเคราะห์และเรียนรู้', '/learning', 'ต่อยอดทุกการเรียนรู้'],
    ]) {
      const button = nav.getByRole('button', { name: label, exact: true });
      const hit = await button.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const target = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return { receivesClick: !!target && el.contains(target), covering: target?.className };
      });
      expect(hit, `The ${label} menu must receive pointer events`).toMatchObject({
        receivesClick: true,
      });
      await button.click({ timeout: 3000 });
      await expect(page).toHaveURL(new RegExp(url + '$'));
      await expect(page.getByRole('heading', { level: 1 })).toContainText(title);
      await nav.getByRole('button', { name: 'หน้าแรก', exact: true }).click();
      await expect(page.getByRole('heading', { level: 1 })).toContainText('ดูน้อยลง');
    }
    const logoutHit = await page
      .getByRole('button', { name: 'ออกจากระบบ', exact: true })
      .evaluate((el) => {
        const r = el.getBoundingClientRect();
        return el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
      });
    expect(logoutHit, 'The profile/logout control must not be covered').toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}

test('keyboard navigation and browser history preserve the chat draft and form access', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await openMemberHome(page);
  await page.getByLabel('วางลิงก์ YouTube', { exact: true }).fill('https://youtu.be/dQw4w9WgXcQ');
  await expect(page.getByRole('button', { name: 'เพิ่มวิดีโอ', exact: true })).toBeEnabled();
  const nav = page.getByRole('navigation', { name: 'เมนูพื้นที่เรียนรู้' });
  const chat = nav.getByRole('button', { name: 'ถามจากคลิป', exact: true });
  await chat.focus();
  await page.keyboard.press('Enter');
  await page.getByLabel('คำถามของคุณ', { exact: true }).fill('คำถามที่ยังไม่ได้ส่ง');
  await nav.getByRole('button', { name: 'วิเคราะห์และเรียนรู้', exact: true }).click();
  await page.getByLabel('ประเภทงาน').selectOption('quiz');
  await nav.getByRole('button', { name: 'หน้าแรก', exact: true }).click();
  await page.goBack();
  await expect(page).toHaveURL(/\/learning$/);
  await expect(page.getByLabel('ประเภทงาน')).toHaveValue('quiz');
  await page.goBack();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByLabel('คำถามของคุณ', { exact: true })).toHaveValue('คำถามที่ยังไม่ได้ส่ง');
  await page.goForward();
  await expect(page).toHaveURL(/\/learning$/);
});
