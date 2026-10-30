// Delivered UI interactions; identity/provider integration is verified separately.
import { createRequire } from "node:module";
import { resolve } from "node:path";
const { test, expect } = createRequire(
  resolve(__dirname, "../../../01_web_app/package.json"),
)("@playwright/test");

const opener = (page) => page.locator(".buddy-launcher");
const panel = (page) => page.getByRole("dialog", { name: /Buddy|บัดดี้|แชต/i });
const minimize = (page) =>
  page.getByRole("button", { name: "ย่อหน้าต่างแชต", exact: true });
async function enter(page) {
  await page.goto("/?demo=1");
  const demo = page.getByRole("button", {
    name: "ทดลองด้วยบัญชี A",
    exact: true,
  });
  await demo.click();
  await expect(
    opener(page),
    "BLOCKED: no floating Buddy launcher in this source (or bind reviewed ARIA names)",
  ).toBeVisible({ timeout: 3000 });
}
async function contained(page) {
  const box = await opener(page).boundingBox();
  const viewport = page.viewportSize();
  expect(box.width).toBeGreaterThanOrEqual(44);
  expect(box.height).toBeGreaterThanOrEqual(44);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 1);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 1);
}
async function drag(page, x, y) {
  const box = await opener(page).boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(x, y, { steps: 10 });
  await page.mouse.up();
}

test("open/minimize restores focus; moving 24px suppresses click", async ({
  page,
}) => {
  await enter(page);
  await opener(page).click();
  await expect(panel(page)).toBeVisible();
  await minimize(page).click();
  await expect(opener(page)).toBeFocused();
  const b = await opener(page).boundingBox();
  await drag(page, b.x - 24, b.y - 24);
  await expect(panel(page)).toBeHidden();
  await contained(page);
  await opener(page).focus();
  await page.keyboard.press("Enter");
  await expect(panel(page)).toBeVisible();
});

test("corners, resize and pointercancel never strand the launcher", async ({
  page,
}) => {
  await enter(page);
  for (const [x, y] of [
    [-50, -50],
    [1600, -50],
    [1600, 1000],
    [-50, 1000],
  ]) {
    await drag(page, x, y);
    await contained(page);
  }
  await page.setViewportSize({ width: 375, height: 812 });
  await contained(page);
  await opener(page).dispatchEvent("pointercancel", {
    pointerId: 1,
    pointerType: "mouse",
  });
  await opener(page).click();
  await expect(panel(page)).toBeVisible();
  await page.setViewportSize({ width: 812, height: 375 });
  await expect(panel(page).getByRole("textbox")).toBeVisible();
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 375, height: 812 },
]) {
  test(`unavailable localStorage retains keyboard opening and Home reset (${viewport.width})`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.addInitScript(() =>
      Object.defineProperty(window, "localStorage", {
        get() {
          throw new DOMException("Storage unavailable", "SecurityError");
        },
      }),
    );
    await enter(page);
    await opener(page).focus();
    await page.keyboard.press("Enter");
    await expect(panel(page)).toBeVisible();
    await minimize(page).click();
    const home = await opener(page).boundingBox();
    const nav = await page.locator(".v5-mobile-nav").boundingBox();
    const bottom = nav?.height
      ? Math.min(viewport.height, nav.y)
      : viewport.height - (viewport.width <= 900 ? 80 : 0);
    const expectedX = Math.max(16, viewport.width - home.width - 16);
    const expectedY = Math.max(16, bottom - home.height - 16);
    await drag(page, 100, 120);
    await expect(panel(page)).toBeHidden();
    await expect
      .poll(async () =>
        Math.hypot(
          (await opener(page).boundingBox()).x - expectedX,
          (await opener(page).boundingBox()).y - expectedY,
        ),
      )
      .toBeGreaterThan(20);
    await opener(page).focus();
    await page.keyboard.press("Home");
    await expect
      .poll(async () =>
        Math.abs((await opener(page).boundingBox()).x - expectedX),
      )
      .toBeLessThanOrEqual(1);
    await expect
      .poll(async () =>
        Math.abs((await opener(page).boundingBox()).y - expectedY),
      )
      .toBeLessThanOrEqual(1);
    await contained(page);
    await expect(panel(page)).toBeHidden();
    await page.keyboard.press("Enter");
    await expect(panel(page)).toBeVisible();
  });
}

test("synthetic composition and Shift+Enter preserve the composer across minimize", async ({
  page,
}) => {
  await enter(page);
  let posts = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/api/chat")) posts++;
  });
  await opener(page).click();
  const input = panel(page).getByRole("textbox");
  await input.fill("ทดสอบภาษาไทย");
  await input.dispatchEvent("compositionstart");
  await input.dispatchEvent("keydown", {
    key: "Enter",
    code: "Enter",
    isComposing: true,
  });
  await input.dispatchEvent("compositionend", { data: "ไทย" });
  await input.press("Shift+Enter");
  await expect(input).toHaveValue(/ทดสอบภาษาไทย/);
  expect(posts).toBe(0);
  await minimize(page).click();
  await opener(page).click();
  expect(posts).toBe(0);
});
