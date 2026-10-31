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

test("feedback API persists across UI history reload, isolates accounts and audits admin review", async ({
  page,
}) => {
  test.setTimeout(90000);
  const api = process.env.WEB_IDENTITY_API_URL;
  const web = "http://127.0.0.1:3004";
  async function login(sub) {
    await page.unroute("https://accounts.google.com/gsi/client");
    await page.route("https://accounts.google.com/gsi/client", (route) =>
      route.fulfill({
        contentType: "application/javascript",
        body: `window.google={accounts:{id:{initialize(o){window.gis=o},renderButton(el){const b=document.createElement('button');b.textContent='Google fixture sign-in';b.onclick=()=>window.gis.callback({credential:JSON.stringify({sub:${JSON.stringify(sub)},nonce:window.gis.nonce})});el.appendChild(b)},disableAutoSelect(){}}}};`,
      }),
    );
    await page.goto(web);
    await page.getByRole("button", { name: "Google fixture sign-in" }).click();
    await expect(page.getByRole("heading", { name: /รู้ให้/ })).toBeVisible();
  }
  // Actual cross-origin browser fetch: exercises credentialed CORS for PUT/DELETE/PATCH.
  async function request(path, method = "GET", data = undefined) {
    const me = await (await page.request.get(`${api}/api/auth/me`)).json();
    return page.evaluate(
      async ({ url, method, data, csrf }) => {
        const response = await fetch(url, {
          method,
          credentials: "include",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
          body: data === undefined ? undefined : JSON.stringify(data),
        });
        return { status: response.status, data: await response.json() };
      },
      { url: `${api}${path}`, method, data, csrf: me.csrf_token },
    );
  }
  async function logout() {
    await page.getByRole("button", { name: "ออกจากระบบ", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Google fixture sign-in" }),
    ).toBeVisible();
  }
  await login("fixture-feedback-07");
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
    .getByRole("button", { name: "ถาม Buddy จากวิดีโอที่เลือก", exact: true })
    .click();
  await page
    .getByLabel("คำถามของคุณ", { exact: true })
    .fill("Feedback API evidence");
  const posted = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/api/chat"),
  );
  await page.getByRole("button", { name: "ส่งคำถาม", exact: true }).click();
  const submission = await posted;
  const accepted = await submission.json();
  let completed = accepted;
  await expect
    .poll(async () => {
      const response = await request(`/api/jobs/${accepted.job_id}`);
      completed = response.data.result;
      return response.data.state;
    })
    .toBe("completed");
  const mid = completed.assistant_message_id;
  expect(mid).toBeTruthy();
  const path = `/api/messages/${mid}/feedback`;
  const feedback = {
    rating: "dislike",
    reason: "citation_mismatch",
    comment: "<script>fixture only</script>",
  };
  const first = await request(path, "PUT", feedback);
  expect(first.status).toBe(200);
  expect((await request(path, "PUT", feedback)).data).toEqual(first.data);
  expect((await request("/api/admin/chat-reviews")).status).toBe(403);
  await page.getByRole("button", { name: "ประวัติแชท", exact: true }).click();
  await page
    .getByRole("button", {
      name: "เปิดบทสนทนา Feedback API evidence",
      exact: true,
    })
    .click();
  await page.reload();
  await expect(page.locator(".turn")).toHaveCount(1);
  const history = await request(
    `/api/conversations/${completed.conversation_id}`,
  );
  expect(history.data.messages.at(-1).feedback).toEqual(first.data.feedback);
  await logout();
  expect((await page.request.get(`${api}${path}`)).status()).toBe(401);
  await login("fixture-feedback-other-07");
  expect((await request(path, "PUT", { rating: "like" })).status).toBe(404);
  expect(
    (await request(`/api/conversations/${completed.conversation_id}`)).status,
  ).toBe(404);
  await logout();
  await login("fixture-admin");
  const listing = await request(
    "/api/admin/chat-reviews?rating=dislike&q=Feedback&limit=1",
  );
  expect(listing.status).toBe(200);
  expect(listing.data.total).toBe(1);
  const casePath = `/api/admin/chat-reviews/${listing.data.items[0].case_id}`;
  const review = await request(casePath);
  expect(review.data.question.job_id).toBe(accepted.job_id);
  expect(review.data.answer.message_id).toBe(mid);
  expect(review.data.scope[0].video_id).toBe("dQw4w9WgXcQ");
  expect(review.data.feedback).toEqual(first.data.feedback);
  expect(
    (await request(casePath, "PATCH", { status: "in_review" })).status,
  ).toBe(200);
  expect(
    (
      await request(casePath, "PATCH", {
        status: "reviewed",
        outcome: "inconclusive",
      })
    ).status,
  ).toBe(200);
  await logout();
  await login("fixture-feedback-07");
  expect(
    (await request(path, "PUT", { rating: "like" })).data.feedback.rating,
  ).toBe("like");
  expect((await request(path, "DELETE")).data.feedback).toBeNull();
  expect(
    (await request(`/api/conversations/${completed.conversation_id}`, "DELETE"))
      .status,
  ).toBe(200);
  expect((await request(path)).status).toBe(404);
  // This tests the browser/API contract, not unimplemented 01 feedback controls.
});
