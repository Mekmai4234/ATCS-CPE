import { test, expect } from '@playwright/test';
test.beforeEach(async ({ page }) => {
  await page.goto('/tests/feedback.html');
});
test('rating is confirmed once, toggles off and edits optional dislike details', async ({
  page,
}) => {
  await page.goto('/tests/feedback.html?hold=1');
  const like = page.getByRole('button', { name: 'ถูกใจ', exact: true });
  await like.click();
  await expect(like).toBeDisabled();
  await page.evaluate(() => window.dispatchEvent(new Event('release-feedback')));
  await expect(like).toHaveAttribute('aria-pressed', 'true');
  await like.click();
  await expect(like).toHaveAttribute('aria-pressed', 'false');
  await page.getByRole('button', { name: 'ไม่ถูกใจ', exact: true }).click();
  await expect(page.locator('.answer-feedback [role="status"]')).toHaveText('รับความคิดเห็นแล้ว');
  await page.getByRole('textbox').fill('<script>untrusted</script>');
  await page.getByRole('button', { name: 'บันทึก', exact: true }).click();
  await expect(page.locator('.answer-feedback [role="status"]')).toHaveText('รับความคิดเห็นแล้ว');
  await expect(page.getByRole('textbox')).toHaveValue('<script>untrusted</script>');
  await expect(page.locator('output')).toHaveText('4');
  await page.screenshot({ path: 'runtime/feedback-preview.png', fullPage: true });
});
test('failure preserves server state and explicit retry uses the same change', async ({ page }) => {
  await page.getByRole('button', { name: 'Toggle failure' }).click();
  const like = page.getByRole('button', { name: 'ถูกใจ', exact: true });
  await like.click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(like).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('.answer-feedback [role="status"]')).not.toHaveText(
    'รับความคิดเห็นแล้ว',
  );
  await page.getByRole('button', { name: 'Toggle failure' }).click();
  await page.getByRole('button', { name: 'ลองใหม่', exact: true }).click();
  await expect(like).toHaveAttribute('aria-pressed', 'true');
});
