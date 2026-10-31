import { test, expect } from '@playwright/test';
test('notes survive reopen and outcome updates; signal metadata is not a withheld draft', async ({
  page,
}) => {
  await page.goto('/tests/review-regression.html?admin=1');
  await page.getByRole('button', { name: 'เปิดดู', exact: true }).click();
  await expect(page.getByLabel('หมายเหตุ')).toHaveValue('existing review note');
  await expect(page.getByText('PRIVATE_SIGNAL_METADATA')).toHaveCount(0);
  await page.getByRole('button', { name: 'เริ่มตรวจ', exact: true }).click();
  await page.getByRole('button', { name: 'เปิดดู', exact: true }).click();
  await expect(page.getByLabel('หมายเหตุ')).toHaveValue('existing review note');
  await page.getByRole('button', { name: 'ยังสรุปไม่ได้', exact: true }).click();
  await page.getByRole('button', { name: 'เปิดดู', exact: true }).click();
  await expect(page.getByLabel('หมายเหตุ')).toHaveValue('existing review note');
  await page.getByRole('button', { name: 'แชทที่บันทึกทั้งหมด' }).click();
  await page.getByRole('button', { name: 'เปิดดู', exact: true }).click();
  await expect(page.getByText('normal question', { exact: true })).toBeVisible();
  await expect(page.getByText('normal answer', { exact: true })).toBeVisible();
});
test('deferred paused chat exposes resume and follows the replacement', async ({ page }) => {
  await page.goto('/tests/review-regression.html');
  await page.getByRole('checkbox').first().check();
  await page.getByRole('button', { name: 'ถาม Buddy จากวิดีโอที่เลือก', exact: true }).click();
  await page.getByLabel('คำถามของคุณ', { exact: true }).fill('Explain RAG');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  const deferred = page.getByRole('region', { name: 'งานที่พักติดตาม' });
  await expect(deferred).toBeVisible();
  await deferred.getByRole('button', { name: 'ให้งานที่พักทำต่อ' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-resume-count', '1');
  await expect(page.getByText('RESUMED ANSWER', { exact: true })).toBeVisible();
  await expect(deferred).toHaveCount(0);
});
