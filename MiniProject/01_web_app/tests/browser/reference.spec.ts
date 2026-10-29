import { test, expect } from '@playwright/test';

test('reference art loads, launcher starts bottom right and screenshots preserve position', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('http://127.0.0.1:3003/login?demo=1');
  await page.getByRole('button', { name: 'ทดลองด้วยบัญชี A' }).click();
  const launcher = page.locator('.buddy-launcher');
  await expect(launcher).toBeVisible();
  await expect
    .poll(() =>
      page
        .locator('.v5-home-art .buddy-art')
        .evaluate((img) => (img as HTMLImageElement).naturalWidth),
    )
    .toBeGreaterThan(0);
  await page.evaluate(() => document.fonts.ready);
  const original = (await launcher.boundingBox())!;
  expect(original.x).toBe(1440 - 72 - 16);
  expect(original.y).toBe(1000 - 72 - 16);
  await page.mouse.move(1, 1);
  await page.screenshot({ path: 'runtime/screenshots/reference-home.png', fullPage: true });
  await expect.poll(async () => (await launcher.boundingBox())!.x).toBe(original.x);
  await expect.poll(async () => (await launcher.boundingBox())!.y).toBe(original.y);
  await launcher.click();
  const panel = page.getByRole('dialog', { name: 'Buddy AI แชตจากคลิป' });
  await expect(panel).toBeVisible();
  expect((await panel.boundingBox())!.x).toBeGreaterThan(1440 / 2);
  await panel.getByText('คลิปที่เลือก', { exact: false }).first().click();
  await panel.getByRole('checkbox').first().check();
  await panel.getByText('คลิปที่เลือก', { exact: false }).first().click();
  await panel.getByLabel('ข้อความถึง Buddy', { exact: true }).fill('RAG คืออะไร');
  await panel.getByRole('button', { name: 'ส่งข้อความถึง Buddy' }).click();
  await expect(panel.locator('.buddy-message')).toHaveCount(1);
  await page.mouse.move(1, 1);
  await page.screenshot({ path: 'runtime/screenshots/reference-chat.png', fullPage: true });
});
