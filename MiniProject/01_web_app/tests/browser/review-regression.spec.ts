import { test, expect } from '@playwright/test';

for (const mode of ['คิวตรวจ', 'แชทที่บันทึกทั้งหมด']) {
  test(`clicking the active ${mode} tab preserves loaded rows and detail`, async ({ page }) => {
    await page.goto('/tests/review-regression.html?admin=1');
    const tab = page.getByRole('button', { name: mode, exact: true });
    if (mode !== 'คิวตรวจ') await tab.click();
    const open = page.getByRole('button', { name: 'เปิดดู', exact: true });
    await expect(open).toHaveCount(1);
    await open.click();
    const question = page
      .getByText(mode === 'คิวตรวจ' ? 'question' : 'normal question', { exact: true })
      .last();
    await expect(question).toBeVisible();
    await tab.click();
    await expect(open).toHaveCount(1);
    await expect(question).toBeVisible();
    await expect(tab).toHaveAttribute('aria-pressed', 'true');
  });
}
test('notes survive reopen and outcome updates; signal metadata is not a withheld draft', async ({
  page,
}) => {
  await page.goto('/tests/review-regression.html?admin=1');
  await page.getByRole('button', { name: 'เปิดดู', exact: true }).click();
  await expect(page.getByLabel('หมายเหตุ')).toHaveValue('existing review note');
  await expect(page.getByText('PRIVATE_SIGNAL_METADATA')).toHaveCount(0);
  await expect(
    page.getByText('สัญญาณระบบเพื่อรอตรวจ — ไม่ใช่ร่างที่ถูกระงับหรือคำตัดสินยืนยัน'),
  ).toBeVisible();
  await page.getByRole('button', { name: 'เริ่มตรวจ', exact: true }).click();
  await page.getByRole('button', { name: 'เปิดดู', exact: true }).click();
  await expect(page.getByLabel('หมายเหตุ')).toHaveValue('existing review note');
  await page.getByRole('button', { name: 'ยังสรุปไม่ได้', exact: true }).click();
  await page.getByLabel('สถานะ', { exact: true }).selectOption('reviewed');
  await page.getByRole('button', { name: 'เปิดดู', exact: true }).click();
  await expect(page.getByLabel('หมายเหตุ')).toHaveValue('existing review note');
  await page.getByRole('button', { name: 'แชทที่บันทึกทั้งหมด' }).click();
  await expect(page.getByText('คำตอบที่บันทึกไว้ — ไม่ได้ระบุว่าเป็นปัญหา')).toBeVisible();
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
  await expect(deferred.getByRole('button', { name: 'ให้งานที่พักทำต่อ' })).toBeVisible();
  await page.locator('.buddy-launcher').click();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('dialog').getByRole('button', { name: 'ให้งานที่พักทำต่อ' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-resume-count', '2');
  await expect(page.getByText('RESUMED ANSWER', { exact: true }).first()).toBeVisible();
  await expect(deferred).toHaveCount(0);
});

test('authorized blocked input is visible as escaped original text, distinct from withheld output', async ({
  page,
}) => {
  await page.goto('/tests/review-regression.html?admin=1&blocked=1');
  await page.getByRole('button', { name: 'เปิดดู', exact: true }).click();
  const original = page.getByRole('region', { name: 'ต้นฉบับข้อความที่ถูกบล็อก' });
  await expect(original).toContainText('ORIGINAL BLOCKED QUESTION <script>alert(1)</script>');
  await expect(original.locator('script')).toHaveCount(0);
  await expect(page.getByText('ร่างที่ถูกระงับ — ผู้ใช้ไม่เห็น')).toHaveCount(0);
});

test('distinct cases sharing one message keep separate rows and details', async ({ page }) => {
  const duplicateKeys: string[] = [];
  page.on('console', (m) => {
    if (/same key|unique.*key/i.test(m.text())) duplicateKeys.push(m.text());
  });
  await page.goto('/tests/review-regression.html?admin=1&shared=1');
  await expect(page.getByRole('button', { name: 'เปิดดู', exact: true })).toHaveCount(2);
  await page.getByRole('button', { name: 'เปิดดู', exact: true }).nth(1).click();
  await expect(page.getByText('second case question', { exact: true })).toBeVisible();
  await expect(page.getByLabel('หมายเหตุ', { exact: true })).toHaveValue('second notes');
  expect(duplicateKeys).toEqual([]);
});

test('liked answers have a dedicated admin view', async ({ page }) => {
  await page.goto('/tests/review-regression.html?admin=1');
  await page.getByRole('button', { name: 'คำตอบที่ถูกใจ', exact: true }).click();
  await expect(page.getByText('ผู้ใช้กดถูกใจ', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'คำตอบที่ถูกใจ', exact: true }).click();
  await expect(page.getByRole('button', { name: 'เปิดดู', exact: true })).toHaveCount(1);
  await page.getByRole('button', { name: 'คิวตรวจ', exact: true }).click();
  await page.getByLabel('คะแนน', { exact: true }).selectOption('like');
  await expect(page.getByText('ผู้ใช้กดถูกใจ', { exact: true })).toBeVisible();
});
