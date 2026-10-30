import { test, expect, type Page } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});
test('library → selected scope → chat → safe timestamp citation', async ({ page }) => {
  await expect(page.getByText('DEMO · ข้อมูลจำลอง', { exact: true })).toBeVisible();
  await page.getByRole('checkbox').first().check();
  await page.getByRole('button', { name: 'ถาม Buddy จากวิดีโอที่เลือก' }).click();
  await page.getByLabel('คำถามของคุณ').fill('RAG คืออะไร');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByText('[คำตอบจำลอง] RAG', { exact: false })).toBeVisible();
  await expect(page.getByRole('link', { name: /^เปิดหลักฐาน/ })).toHaveAttribute(
    'href',
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=14s',
  );
});
test('import independently reports accepted/existing/rejected and no captions', async ({
  page,
}) => {
  await page
    .getByLabel('ลิงก์วิดีโอ YouTube')
    .fill('https://youtu.be/NoCaption01\nhttps://youtu.be/dQw4w9WgXcQ\ninvalid');
  await page.getByRole('button', { name: 'เพิ่มคลิป (เพิ่มวิดีโอ)', exact: true }).click();
  const results = page.getByRole('region', { name: 'ผลนำเข้ารายลิงก์' });
  await expect(results.getByText('รับเข้าคิวแล้ว', { exact: true })).toBeVisible();
  await expect(results.getByText('มีอยู่แล้ว', { exact: true })).toBeVisible();
  await expect(results.getByText('ปฏิเสธ', { exact: true })).toBeVisible();
  await expect(results.getByText('ไม่มีบทถอดเสียง', { exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: /NoCaption01/ })).toBeDisabled();
});
test('pending 202 chat resolves and insufficient evidence is explicit', async ({ page }) => {
  await page.getByRole('checkbox').first().check();
  await page.getByRole('button', { name: 'ถาม Buddy จากวิดีโอที่เลือก' }).click();
  await page.getByLabel('คำถามของคุณ').fill('รอผล RAG');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByText(/Job ID:/)).toBeVisible();
  await expect(page.getByText('[คำตอบจำลอง] RAG', { exact: false })).toBeVisible();
  await page.getByLabel('คำถามของคุณ').fill('ไม่มีข้อมูล');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'หลักฐานไม่เพียงพอ', exact: true })).toBeVisible();
});
test('analysis and every learning artifact render after polling', async ({ page }) => {
  await page.getByRole('checkbox').first().check();
  await page.getByRole('button', { name: 'สรุปและแบบฝึกหัด', exact: true }).click();
  await page.getByRole('button', { name: 'เริ่มงาน', exact: true }).click();
  await expect(page.getByText('[คำตอบจำลอง] RAG', { exact: false })).toBeVisible();
  for (const type of ['quiz', 'flashcards', 'study_plan']) {
    await learningSettings(page);
    await page.getByLabel('ประเภทงาน').selectOption(type);
    if (type === 'study_plan') await page.getByLabel('จำนวนวัน').fill('2');
    await page.getByRole('button', { name: 'เริ่มงาน', exact: true }).click();
    if (type === 'quiz')
      await expect(page.getByText('1. RAG ช่วยอะไร?', { exact: true })).toBeVisible();
    if (type === 'flashcards')
      await expect(page.getByText('RAG คืออะไร?', { exact: true })).toBeVisible();
    if (type === 'study_plan')
      await expect(page.getByText('วันที่ 2', { exact: true })).toBeVisible();
  }
});
test('research shows events and partial result honestly', async ({ page }) => {
  await page.getByRole('checkbox').first().check();
  await page.getByRole('button', { name: 'สรุปและแบบฝึกหัด', exact: true }).click();
  await learningSettings(page);
  await page.getByLabel('ประเภทงาน').selectOption('research');
  await page.getByLabel('เป้าหมายค้นคว้า').fill('เรียน RAG');
  await page.getByRole('button', { name: 'เริ่มงาน', exact: true }).click();
  await expect(
    page.getByText('ได้ผลบางส่วน — งานนี้ยังไม่สำเร็จครบถ้วน', { exact: true }),
  ).toBeVisible();
  await expect(page.getByText('ค้นหลักฐานในชุดข้อมูลจำลอง', { exact: false })).toBeVisible();
});
test('deletion confirmation supports keyboard cancellation and removal', async ({ page }) => {
  const boxes = page.getByRole('checkbox');
  await expect(boxes).toHaveCount(2);
  await page.getByRole('button', { name: /^ลบ / }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(boxes).toHaveCount(2);
  await page.getByRole('button', { name: /^ลบ / }).first().click();
  await page.getByRole('button', { name: 'ยืนยันลบคลิป' }).click();
  await expect(boxes).toHaveCount(1);
});
test('mobile layout fits viewport and basic flow remains usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole('checkbox').first().check();
  await page.getByRole('button', { name: 'ถาม Buddy จากวิดีโอที่เลือก' }).click();
  await expect(page.getByLabel('คำถามของคุณ')).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: 'runtime/screenshots/mobile.png', fullPage: true });
});
test('desktop visual and no browser exceptions', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.reload();
  await expect(page.getByRole('checkbox')).toHaveCount(2);
  await page.screenshot({ path: 'runtime/screenshots/desktop.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('deleting a source updates already displayed learning artifact citations', async ({
  page,
}) => {
  await page.getByRole('checkbox').nth(0).check();
  await page.getByRole('checkbox').nth(1).check();
  await page.getByRole('button', { name: 'สรุปและแบบฝึกหัด', exact: true }).click();
  await learningSettings(page);
  await page.getByLabel('ประเภทงาน').selectOption('flashcards');
  await page.getByRole('button', { name: 'เริ่มงาน', exact: true }).click();
  await page.getByText('RAG คืออะไร?', { exact: true }).click();
  await expect(page.locator('.artifact a')).toHaveCount(2);
  await page.getByRole('button', { name: 'กลับไปเรียนรู้', exact: true }).click();
  await page.locator('.v5-source-select button').click();
  await page.getByRole('button', { name: /^ลบ .*เริ่มต้นเข้าใจ/ }).click();
  await page.getByRole('button', { name: 'ยืนยันลบคลิป', exact: true }).click();
  await expect(page.locator('.artifact a')).toHaveCount(1);
  await expect(
    page.locator('.artifact').getByText('แหล่งข้อมูลใช้ไม่ได้', { exact: true }),
  ).toBeVisible();
});

async function learningSettings(page: Page) {
  const create = page.getByRole('button', { name: 'สร้างใหม่', exact: true });
  if (await create.isVisible()) await create.click();
  const settings = page.locator('.v5-learning-settings');
  if ((await settings.getAttribute('open')) === null) await settings.locator('summary').click();
}
