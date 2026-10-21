// Explicit demo screenshots only. The output must never count as real Google evidence.
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { mkdir, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";

if (!process.argv.includes("--allow-demo"))
  throw new Error("Pass --allow-demo for fixture UI evidence");
const moduleRoot = fileURLToPath(new URL("..", import.meta.url));
const web = resolve(moduleRoot, "../01_web_app");
const require = createRequire(resolve(web, "package.json"));
const { chromium } = require("@playwright/test");
const output = resolve(moduleRoot, "runtime/ui-demo");
await mkdir(output, { recursive: true });
const port = 3017;
const origin = `http://127.0.0.1:${port}`;
const server = spawn(
  process.execPath,
  [
    "node_modules/vite/bin/vite.js",
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
  ],
  {
    cwd: web,
    windowsHide: true,
    stdio: "pipe",
    env: { ...process.env, VITE_DEMO_MODE: "true" },
  },
);
let logs = "";
server.stdout.on("data", (data) => {
  logs += data;
});
server.stderr.on("data", (data) => {
  logs += data;
});
let browser;
try {
  let ready = false;
  for (let attempt = 0; attempt < 50; attempt++) {
    if (server.exitCode !== null)
      throw new Error("Owned Vite server exited; inspect server.log");
    try {
      ready = (await fetch(origin)).ok;
    } catch {}
    if (ready) break;
    await new Promise((done) => setTimeout(done, 200));
  }
  if (!ready) throw new Error("Vite startup timeout");
  browser = await chromium.launch();
  for (const width of [375, 768, 1440]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
    });
    // No Google, captions or model calls are permitted during this visual drill.
    await context.route("**/*", (route) =>
      route.request().url().startsWith(origin)
        ? route.continue()
        : route.abort(),
    );
    const page = await context.newPage();
    await page.goto(origin);
    await page
      .getByRole("button", { name: "ทดลองบัญชีผู้ดูแล", exact: true })
      .waitFor();
    await page.screenshot({
      path: resolve(output, `login-${width}.png`),
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "ทดลองบัญชีผู้ดูแล", exact: true })
      .click();
    await page.goto(`${origin}/admin`);
    await page.getByRole("button", { name: "สมาชิก", exact: true }).waitFor();
    await page.screenshot({
      path: resolve(output, `admin-${width}.png`),
      fullPage: true,
    });
    await context.close();
  }
  await writeFile(
    resolve(output, "evidence.json"),
    JSON.stringify(
      {
        mode: "explicit-demo",
        google_verified: false,
        backend_identity_verified: false,
        widths: [375, 768, 1440],
      },
      null,
      2,
    ),
  );
} finally {
  await browser?.close();
  server.kill();
  await writeFile(resolve(output, "server.log"), logs);
}
