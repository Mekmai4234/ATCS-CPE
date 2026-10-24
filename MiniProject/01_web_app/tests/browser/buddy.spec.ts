import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const base = 'http://127.0.0.1:3003';
const dialog = (page: Page) => page.getByRole('dialog', { name: 'Buddy AI แชตจากคลิป' });
const launcher = (page: Page) => page.locator('.buddy-launcher');
async function login(page: Page) {
  await page.goto(`${base}/login?demo=1`);
  await page.getByRole('button', { name: 'ทดลองด้วยบัญชี A' }).click();
  await expect(page.getByRole('heading', { name: /เปลี่ยนคลิป/ })).toBeVisible();
}
async function open(page: Page) {
  await launcher(page).click();
  await expect(dialog(page)).toBeVisible();
}
async function choose(page: Page, index = 0) {
  await dialog(page).getByText('คลิปที่เลือก', { exact: false }).first().click();
  await dialog(page).getByRole('checkbox').nth(index).check();
}
test('login is private and policy/help links have real readable destinations', async ({ page }) => {
  await page.goto(`${base}/login?demo=1`);
  await expect(launcher(page)).toHaveCount(0);
  expect(await page.locator('.forest-backdrop img').count()).toBe(0);
  await page.getByRole('link', { name: 'ความเป็นส่วนตัว', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'ความเป็นส่วนตัว', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'ช่วยเหลือ', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'ช่วยเหลือ RAG Buddy' })).toBeVisible();
});
test('drag is clamped, does not click, persists only coordinates and survives resize', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await login(page);
  const box = (await launcher(page).boundingBox())!;
  await page.mouse.move(box.x + 36, box.y + 36);
  await page.mouse.down();
  await page.mouse.move(20, 24, { steps: 10 });
  await page.mouse.up();
  await expect(dialog(page)).toHaveCount(0);
  const moved = (await launcher(page).boundingBox())!;
  expect(moved.x).toBeGreaterThanOrEqual(16);
  expect(moved.y).toBeGreaterThanOrEqual(16);
  expect(
    await page.evaluate(() =>
      Object.keys(JSON.parse(localStorage.getItem('ragbuddy.launcher.v1')!)).sort(),
    ),
  ).toEqual(['v', 'x', 'y']);
  await page.goto(`${base}/?demo=1`);
  const restored = (await launcher(page).boundingBox())!;
  expect(Math.abs(restored.x - moved.x)).toBeLessThan(2);
  await page.setViewportSize({ width: 375, height: 500 });
  await expect
    .poll(async () => {
      const rect = (await launcher(page).boundingBox())!;
      return rect.x + rect.width <= 359 && rect.y + rect.height <= 484;
    })
    .toBe(true);
});
test('pointercancel restores the origin and presets/reset/hide work with keyboard', async ({
  page,
}) => {
  await login(page);
  const origin = (await launcher(page).boundingBox())!;
  await page.mouse.move(origin.x + 30, origin.y + 30);
  await page.mouse.down();
  await page.mouse.move(30, 30, { steps: 5 });
  await launcher(page).dispatchEvent('pointercancel', { pointerId: 1, clientX: 30, clientY: 30 });
  await page.mouse.up();
  expect((await launcher(page).boundingBox())!.x).toBeCloseTo(origin.x, 0);
  await page.getByRole('button', { name: 'ตำแหน่งและการแสดงแชต' }).click();
  await page.getByRole('button', { name: 'มุมบนซ้าย', exact: true }).focus();
  await page.keyboard.press('Enter');
  expect((await launcher(page).boundingBox())!.x).toBe(16);
  await page.getByRole('button', { name: 'ตำแหน่งและการแสดงแชต' }).click();
  await page.getByRole('button', { name: 'คืนตำแหน่ง', exact: true }).click();
  await launcher(page).focus();
  await page.keyboard.press('Enter');
  await expect(dialog(page)).toBeVisible();
  await dialog(page).getByRole('button', { name: 'ซ่อนแชตและปุ่ม Buddy' }).click();
  await expect(launcher(page)).toHaveCount(0);
  await page.getByRole('button', { name: 'เปิดแชต Buddy', exact: true }).click();
  await expect(dialog(page)).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(launcher(page)).toBeFocused();
});
test('floating and full chat share scope, conversation, messages and 202 status', async ({
  page,
}) => {
  await login(page);
  await open(page);
  await expect(dialog(page).getByRole('button', { name: 'ส่งข้อความถึง Buddy' })).toBeDisabled();
  await choose(page);
  await dialog(page).getByLabel('ข้อความถึง Buddy', { exact: true }).fill('รอผล แล้วอธิบาย RAG');
  await dialog(page).getByLabel('ข้อความถึง Buddy', { exact: true }).press('Enter');
  await expect(
    dialog(page)
      .getByText(/กำลังทำงาน/)
      .first(),
  ).toBeVisible();
  await page.screenshot({ path: 'runtime/screenshots/mint-chat-loading.png', fullPage: true });
  await expect(dialog(page).locator('.buddy-message')).toHaveCount(1);
  await expect(
    dialog(page)
      .getByRole('link', { name: /^เปิดหลักฐาน/ })
      .first(),
  ).toHaveAttribute('href', /youtube\.com\/watch/);
  await dialog(page).getByRole('button', { name: 'ย่อหน้าต่างแชต' }).click();
  await open(page);
  await expect(dialog(page).locator('.buddy-message')).toHaveCount(1);
  await dialog(page).getByRole('button', { name: 'โหลดประวัติบทสนทนานี้' }).click();
  await expect(dialog(page).getByText(/โหลดประวัติแล้ว/)).toBeVisible();
  await expect(dialog(page).locator('.buddy-message')).toHaveCount(1);
  await dialog(page)
    .getByRole('button', { name: /ไปหน้าแชตเต็ม/ })
    .click();
  await expect(page.locator('.turn')).toHaveCount(1);
  await expect(page.getByRole('checkbox').first()).toBeChecked();
  await page.getByLabel('คำถามของคุณ').fill('คำถามต่อเนื่อง');
  await page.getByRole('button', { name: 'ส่งคำถาม', exact: true }).click();
  await expect(page.locator('.turn')).toHaveCount(2);
  await open(page);
  await expect(dialog(page).locator('.buddy-message')).toHaveCount(2);
});
test('scope changes start a new conversation and suggestions never submit automatically', async ({
  page,
}) => {
  await login(page);
  await open(page);
  await choose(page);
  await dialog(page).getByRole('button', { name: 'สรุปประเด็นสำคัญจากคลิป' }).click();
  await expect(dialog(page).locator('.buddy-message')).toHaveCount(0);
  await dialog(page).getByLabel('ข้อความถึง Buddy', { exact: true }).press('Enter');
  await expect(dialog(page).locator('.buddy-message')).toHaveCount(1);
  await dialog(page).getByRole('checkbox').nth(1).check();
  await dialog(page).getByLabel('ข้อความถึง Buddy', { exact: true }).fill('ถามด้วยชุดใหม่');
  await dialog(page).getByLabel('ข้อความถึง Buddy', { exact: true }).press('Enter');
  await expect(
    dialog(page).getByText('ชุดคลิปเปลี่ยนแล้ว คำถามนี้เริ่มบทสนทนาใหม่', { exact: true }),
  ).toBeVisible();
});
test('IME and Shift+Enter do not submit; cancellation is available for a pending job', async ({
  page,
}) => {
  await login(page);
  await open(page);
  await choose(page);
  const input = dialog(page).getByLabel('ข้อความถึง Buddy', { exact: true });
  await input.fill('ภาษาไทย รอผล');
  await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true, keyCode: 229 });
  await input.press('Shift+Enter');
  await expect(dialog(page).locator('.buddy-message')).toHaveCount(0);
  await input.press('Enter');
  await expect(dialog(page).getByRole('button', { name: 'ขอยกเลิกงานแชต' })).toBeVisible();
  await dialog(page).getByRole('button', { name: 'ขอยกเลิกงานแชต' }).click();
  await expect(dialog(page).getByRole('button', { name: 'ส่งข้อความถึง Buddy' })).toBeEnabled();
  await page.screenshot({ path: 'runtime/screenshots/mint-chat-cancelled.png', fullPage: true });
});
test('mascot head/pupils are bounded and reduced motion remains static', async ({ page }) => {
  await login(page);
  const rig = page.locator('.home-mascot .buddy-rig');
  const box = (await rig.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.85, box.y + box.height * 0.3);
  await expect
    .poll(() =>
      rig.evaluate((node) => parseFloat((node as HTMLElement).style.getPropertyValue('--eye-x'))),
    )
    .toBeGreaterThan(0);
  expect(
    Math.abs(
      await rig.evaluate((node) =>
        parseFloat((node as HTMLElement).style.getPropertyValue('--eye-x')),
      ),
    ),
  ).toBeLessThanOrEqual(6);
  await page.mouse.move(2, 2);
  await expect
    .poll(() => rig.evaluate((node) => (node as HTMLElement).style.getPropertyValue('--eye-x')))
    .toBe('0px');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.mouse.move(box.x + box.width * 0.9, box.y + box.height * 0.4);
  expect(
    await rig.locator('.buddy-head').evaluate((node) => getComputedStyle(node).transform),
  ).toBe('none');
});
test('missing rig layer falls back to the existing still image', async ({ page }) => {
  await page.route('**/buddy-rig/body.webp', (route) => route.abort());
  await login(page);
  await expect(page.locator('.home-mascot .buddy-static')).toBeVisible();
});

test('blocked local storage does not prevent opening or repositioning Buddy', async ({ page }) => {
  await page.addInitScript(() =>
    Object.defineProperty(window, 'localStorage', {
      get() {
        throw new DOMException('blocked');
      },
    }),
  );
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await login(page);
  await page.getByRole('button', { name: 'ตำแหน่งและการแสดงแชต' }).click();
  await page.getByRole('button', { name: 'มุมบนซ้าย', exact: true }).click();
  await open(page);
  await expect(dialog(page)).toBeVisible();
  expect(errors).toEqual([]);
});
test('new answers do not pull the reader away from older messages', async ({ page }) => {
  test.setTimeout(60000);
  await login(page);
  await open(page);
  await choose(page);
  for (let index = 1; index <= 4; index++) {
    await dialog(page).getByLabel('ข้อความถึง Buddy', { exact: true }).fill(`คำถาม ${index}`);
    await dialog(page).getByLabel('ข้อความถึง Buddy', { exact: true }).press('Enter');
    await expect(dialog(page).locator('.buddy-message')).toHaveCount(index);
  }
  const scroll = dialog(page).locator('.buddy-messages');
  await scroll.evaluate((node) => {
    node.scrollTop = 0;
    node.dispatchEvent(new Event('scroll'));
  });
  await dialog(page)
    .getByLabel('ข้อความถึง Buddy', { exact: true })
    .fill('คำถามใหม่ขณะอ่านของเก่า');
  await expect(dialog(page).getByRole('button', { name: 'มีข้อความใหม่ ↓' })).toHaveCount(0);
  await dialog(page).getByLabel('ข้อความถึง Buddy', { exact: true }).press('Enter');
  await expect(dialog(page).locator('.buddy-message')).toHaveCount(5);
  await expect(dialog(page).getByRole('button', { name: 'มีข้อความใหม่ ↓' })).toBeVisible();
  expect(await scroll.evaluate((node) => node.scrollTop)).toBe(0);
  await dialog(page).getByRole('button', { name: 'มีข้อความใหม่ ↓' }).click();
  expect(await scroll.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
});
test('real touch drag/cancel/tap and keyboard-sized viewport remain usable', async ({
  browser,
}) => {
  const context = await browser.newContext({
    hasTouch: true,
    isMobile: true,
    viewport: { width: 375, height: 700 },
  });
  const page = await context.newPage();
  try {
    await login(page);
    const cdp = await context.newCDPSession(page);
    let box = (await launcher(page).boundingBox())!;
    await cdp.send('Input.dispatchTouchEvent', {
      type: 'touchStart',
      touchPoints: [{ x: box.x + 36, y: box.y + 36 }],
    });
    await cdp.send('Input.dispatchTouchEvent', {
      type: 'touchMove',
      touchPoints: [{ x: 60, y: 110 }],
    });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await expect(dialog(page)).toHaveCount(0);
    box = (await launcher(page).boundingBox())!;
    await cdp.send('Input.dispatchTouchEvent', {
      type: 'touchStart',
      touchPoints: [{ x: box.x + 36, y: box.y + 36 }],
    });
    await cdp.send('Input.dispatchTouchEvent', {
      type: 'touchMove',
      touchPoints: [{ x: 260, y: 400 }],
    });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchCancel', touchPoints: [] });
    await expect
      .poll(async () => Math.round((await launcher(page).boundingBox())!.x))
      .toBe(Math.round(box.x));
    await page.touchscreen.tap(box.x + 36, box.y + 36);
    await expect(dialog(page)).toBeVisible();
    await page.setViewportSize({ width: 375, height: 330 });
    const rect = (await dialog(page).boundingBox())!;
    expect(rect.y + rect.height).toBeLessThanOrEqual(330);
    await expect(dialog(page).getByLabel('ข้อความถึง Buddy', { exact: true })).toBeInViewport();
  } finally {
    await context.close();
  }
});
test('200-percent-equivalent viewport keeps layout and panel within bounds', async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 720, height: 500 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();
  try {
    await login(page);
    await open(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    const rect = (await dialog(page).boundingBox())!;
    expect(rect.x + rect.width).toBeLessThanOrEqual(720);
    expect(rect.y + rect.height).toBeLessThanOrEqual(500);
  } finally {
    await context.close();
  }
});
test('mobile dialog traps focus, desktop does not make the workspace inert, and contrast passes', async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await login(page);
  await open(page);
  await expect(dialog(page)).toHaveAttribute('aria-modal', 'true');
  expect(await page.locator('.app-shell').evaluate((node) => (node as HTMLElement).inert)).toBe(
    true,
  );
  await dialog(page).getByRole('button', { name: 'ย่อหน้าต่างแชต' }).focus();
  await page.keyboard.press('Shift+Tab');
  await expect(
    dialog(page).getByRole('button', { name: 'ซ่อนแชตและปุ่ม Buddy' }),
  ).not.toBeFocused();
  await page.keyboard.press('Escape');
  await expect(launcher(page)).toBeFocused();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await open(page);
  expect(await page.locator('.app-shell').evaluate((node) => (node as HTMLElement).inert)).toBe(
    false,
  );
  const results = await new AxeBuilder({ page })
    .include('#floating-buddy-chat')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(
    results.violations.map((item) => ({
      id: item.id,
      targets: item.nodes.map((node) => node.target),
    })),
  ).toEqual([]);
});
for (const width of [375, 768, 1024, 1440])
  test(`mint login/home/chat snapshots fit ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`${base}/login?demo=1`);
    await expect(page.getByRole('button', { name: 'ทดลองด้วยบัญชี A' })).toBeVisible();
    await page.screenshot({ path: `runtime/screenshots/mint-login-${width}.png`, fullPage: true });
    await page.getByRole('button', { name: 'ทดลองด้วยบัญชี A' }).click();
    await expect(launcher(page)).toBeVisible();
    await page.screenshot({ path: `runtime/screenshots/mint-home-${width}.png`, fullPage: true });
    await open(page);
    await page.screenshot({ path: `runtime/screenshots/mint-chat-${width}.png`, fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    const rect = (await dialog(page).boundingBox())!;
    expect(rect.x).toBeGreaterThanOrEqual(0);
    expect(rect.x + rect.width).toBeLessThanOrEqual(width);
  });
