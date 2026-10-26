import { test, expect } from '@playwright/test';

test('real module 02 HTTP + worker: import, chat, compare, research and saved artifacts', async ({
  page,
}) => {
  test.skip(
    process.env.WEB_BACKEND_TEST !== 'true',
    'Requires isolated module 02 fixture API/worker; see README.',
  );
  test.setTimeout(120000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('http://127.0.0.1:3002');
  await page
    .getByLabel('ลิงก์วิดีโอ YouTube')
    .fill(
      'https://youtu.be/dQw4w9WgXcQ\nhttps://youtu.be/wD3NSzYtsMc\nhttps://youtu.be/NoCaption01\nbad-url',
    );
  await page.getByRole('button', { name: 'เพิ่มวิดีโอ', exact: true }).click();
  await expect(page.getByRole('checkbox')).toHaveCount(3);
  await expect(page.getByRole('checkbox', { name: /NoCaption01/ })).toBeDisabled();
  await expect
    .poll(async () =>
      page
        .getByRole('checkbox')
        .evaluateAll((boxes) => boxes.filter((box) => !(box as HTMLInputElement).disabled).length),
    )
    .toBe(2);
  await page.locator('input[type="checkbox"]:enabled').nth(0).check();
  await page.locator('input[type="checkbox"]:enabled').nth(1).check();
  await page.getByRole('button', { name: 'ถามจากวิดีโอที่เลือก' }).click();
  await page.getByLabel('คำถามของคุณ').fill('Explain RAG');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.locator('.turn')).toHaveCount(1);
  await expect(page.getByRole('link', { name: /^เปิดหลักฐาน/ }).first()).toHaveAttribute(
    'href',
    /youtube\.com\/watch\?v=.+&t=\d+s/,
  );
  await page.getByRole('button', { name: 'สรุปและแบบฝึกหัด', exact: true }).click();
  await page.getByLabel('ประเภทงาน').selectOption('compare');
  await page.getByRole('button', { name: 'เริ่มงาน', exact: true }).click();
  await expect(page.locator('.turn')).toHaveCount(2);
  for (const [type, count] of [
    ['quiz', 3],
    ['flashcards', 4],
    ['study_plan', 5],
  ] as const) {
    await page.getByLabel('ประเภทงาน').selectOption(type);
    if (type === 'study_plan') await page.getByLabel('จำนวนวัน').fill('2');
    await page.getByRole('button', { name: 'เริ่มงาน', exact: true }).click();
    await expect(page.locator('.turn')).toHaveCount(count);
    await expect(page.locator('.turn').last().locator('.artifact')).toHaveCount(1);
  }
  await page.getByLabel('ประเภทงาน').selectOption('research');
  await page.getByLabel('เป้าหมายค้นคว้า').fill('Learn RAG');
  await page.getByRole('button', { name: 'เริ่มงาน', exact: true }).click();
  await expect(page.locator('.turn')).toHaveCount(6);
  await expect(page.getByText('DEMO · ข้อมูลจำลอง', { exact: true })).toBeVisible();
  await page.screenshot({ path: 'runtime/screenshots/backend-integration.png', fullPage: true });
  const original = page.locator('.turn').first();
  const firstLink = await original
    .getByRole('link', { name: /^เปิดหลักฐาน/ })
    .first()
    .getAttribute('href');
  const deletedId = new URL(firstLink!).searchParams.get('v')!;
  const remainingId = deletedId === 'dQw4w9WgXcQ' ? 'wD3NSzYtsMc' : 'dQw4w9WgXcQ';
  await page
    .locator('.video-card')
    .filter({ has: page.locator(`a[href*="v=${deletedId}"]`) })
    .getByRole('button', { name: /^ลบ / })
    .click();
  await page.getByRole('button', { name: 'ยืนยันลบคลิป', exact: true }).click();
  await expect(page.locator('.turn').locator(`a[href*="v=${deletedId}&"]`)).toHaveCount(0);
  await expect(original.locator(`a[href*="v=${remainingId}&"]`).first()).toBeVisible();
  await page.getByRole('button', { name: /วิดีโอของฉัน/ }).click();
  await page.getByLabel('ลิงก์วิดีโอ YouTube').fill(`https://youtu.be/${deletedId}`);
  // Cleanup is durable; wait until the deletion job has actually completed.
  await expect(page.getByText('การลบคลิป: เสร็จแล้ว', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'เพิ่มวิดีโอ', exact: true }).click();
  await expect.poll(async () => page.locator('input[type="checkbox"]:enabled').count()).toBe(2);
  const newSource = page
    .locator('.video-card')
    .filter({ has: page.locator(`a[href*="v=${deletedId}"]`) });
  await newSource.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'ถามจากวิดีโอที่เลือก' }).click();
  await page.getByLabel('คำถามของคุณ').fill('Explain RAG again');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.locator('.turn')).toHaveCount(7);
  await expect(original.locator(`a[href*="v=${deletedId}&"]`)).toHaveCount(0);
  await expect(
    page.locator('.turn').last().locator(`a[href*="v=${deletedId}&"]`).first(),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
