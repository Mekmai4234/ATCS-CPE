// Keep module 01's real-adapter scenarios and add 07's research/worker acceptance.
import "../../../01_web_app/tests/browser/identity.spec";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const { test, expect } = createRequire(
  resolve(__dirname, "../../../01_web_app/package.json"),
)("@playwright/test");

test("real HTTP research job produces events/citations and logout clears the workspace", async ({
  page,
}) => {
  test.setTimeout(90000);
  await page.route("https://accounts.google.com/gsi/client", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: `window.google={accounts:{id:{initialize(o){window.gis=o},renderButton(el){const b=document.createElement('button');b.textContent='Google fixture sign-in';b.onclick=()=>window.gis.callback({credential:JSON.stringify({sub:'fixture-07-research',nonce:window.gis.nonce})});el.appendChild(b)},disableAutoSelect(){}}}};`,
    }),
  );
  await page.goto("http://127.0.0.1:3004");
  await page.getByRole("button", { name: "Google fixture sign-in" }).click();
  await expect(page.getByRole("heading", { name: /รู้ให้/ })).toBeVisible();
  await page
    .getByLabel("ลิงก์ YouTube", { exact: true })
    .fill("https://youtu.be/dQw4w9WgXcQ");
  await page
    .getByRole("button", { name: "เพิ่มคลิป (เพิ่มวิดีโอ)", exact: true })
    .click();
  await expect
    .poll(async () => page.locator('input[type="checkbox"]:enabled').count())
    .toBe(1);
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "สรุปและแบบฝึกหัด", exact: true })
    .click();
  await page
    .getByRole("button", { name: "ค้นคว้าหลายขั้นตอน", exact: true })
    .click();
  await expect(page.getByLabel("เป้าหมายค้นคว้า")).toBeVisible();
  await page.getByLabel("เป้าหมายค้นคว้า").fill("Explain evidence for RAG");
  const submitted = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/api/research"),
  );
  await page.getByRole("button", { name: "เริ่มงาน", exact: true }).click();
  const submission = await submitted;
  expect(submission.status()).toBe(202);
  expect(submission.request().postDataJSON()).toMatchObject({
    goal: "Explain evidence for RAG",
    scope: { video_ids: ["dQw4w9WgXcQ"] },
  });
  const accepted = await submission.json();
  expect(accepted.run_id).toBeTruthy();
  await expect(page.locator(".turn")).toHaveCount(1);
  await expect(page.locator(".turn .result-content")).toBeVisible();
  await expect(
    page.getByRole("link", { name: /^เปิดหลักฐาน/ }).first(),
  ).toHaveAttribute("href", /youtube\.com\/watch\?v=dQw4w9WgXcQ&t=\d+s/);
  const response = await page.request.get(
    `${process.env.WEB_IDENTITY_API_URL}/api/research/${accepted.run_id}`,
  );
  expect(response.status()).toBe(200);
  const completed = await response.json();
  expect(completed.state).toBe("completed");
  expect(completed.events.length).toBeGreaterThan(0);
  expect(completed.result.citations.length).toBeGreaterThan(0);
  expect(
    completed.result.citations.every(
      (citation) => citation.video_id === "dQw4w9WgXcQ",
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "ออกจากระบบ", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Google fixture sign-in" }),
  ).toBeVisible();
  expect(
    (
      await page.request.get(`${process.env.WEB_IDENTITY_API_URL}/api/videos`)
    ).status(),
  ).toBe(401);
  expect(
    (
      await page.request.get(
        `${process.env.WEB_IDENTITY_API_URL}/api/research/${accepted.run_id}`,
      )
    ).status(),
  ).toBe(401);
  await page.goBack();
  await expect(
    page.getByRole("button", { name: "Google fixture sign-in" }),
  ).toBeVisible();
  await expect(page.locator(".turn")).toHaveCount(0);
  await expect(page.locator(".video-card")).toHaveCount(0);
});
