// Evidence capture, not a mock implementation of the requested UI.
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  mkdir,
  writeFile,
  appendFile,
  readdir,
  stat,
  readFile,
} from "node:fs/promises";
import { spawn, execFileSync } from "node:child_process";
import { gzipSync } from "node:zlib";
import os from "node:os";

const moduleRoot = fileURLToPath(new URL("..", import.meta.url));
const root = resolve(moduleRoot, "..");
const web = resolve(root, "01_web_app");
const { chromium } = createRequire(resolve(web, "package.json"))(
  "@playwright/test",
);
const output = resolve(moduleRoot, "runtime/ui-qa");
await mkdir(output, { recursive: true });
const origin = "http://127.0.0.1:3017";
try {
  await fetch(origin);
  throw new Error("Port 3017 is already in use");
} catch (error) {
  if (!error.cause) throw error;
}
const env = Object.fromEntries(
  Object.entries(process.env).filter(
    ([key]) =>
      !/^(VITE_|NEXT_PUBLIC_|GEMINI_|OPENAI_|GOOGLE_|AUTH_|SESSION_)/i.test(
        key,
      ),
  ),
);
const server = spawn(
  process.execPath,
  ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "3017"],
  {
    cwd: web,
    windowsHide: true,
    stdio: "pipe",
    env: { ...env, VITE_DEMO_MODE: "true" },
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
const evidence = {
  mode: "actual-checkout-fixture-capture",
  fixture: true,
  accepted: false,
  real_google_verified: false,
  performance_target_agreed: false,
  revision: execFileSync("git", ["-C", root, "rev-parse", "HEAD"], {
    encoding: "utf8",
  }).trim(),
  environment: {
    platform: process.platform,
    node: process.version,
    logical_cpus: os.cpus().length,
  },
  views: [],
  bundles: [],
  blockers: [],
};
try {
  let ready = false;
  for (let attempt = 0; attempt < 60; attempt++) {
    if (server.exitCode !== null) throw new Error("Owned Vite server exited");
    try {
      ready = (await fetch(origin)).ok;
    } catch {}
    if (ready) break;
    await new Promise((done) => setTimeout(done, 200));
  }
  if (!ready) throw new Error("Vite startup timeout");
  browser = await chromium.launch();
  evidence.environment.browser = browser.version();
  for (const width of [375, 768, 1024, 1440]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", (route) =>
      new URL(route.request().url()).origin === origin
        ? route.continue()
        : route.abort(),
    );
    await context.tracing.start({ screenshots: true, snapshots: true });
    const page = await context.newPage();
    await page.goto(origin);
    await page.locator("#root").waitFor();
    const demo = page.getByRole("button", {
      name: "ทดลองด้วยบัญชี A",
      exact: true,
    });
    if (await demo.count()) await demo.click();
    const launcher = page.getByRole("button", {
      name: /เปิด.*(?:Buddy|บัดดี้).*แชต|เปิดแชต.*(?:Buddy|บัดดี้)|open buddy chat/i,
    });
    const hasLauncher = (await launcher.count()) > 0;
    await page.screenshot({
      path: resolve(output, `home-${width}.png`),
      fullPage: true,
    });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth + 2,
    );
    if (hasLauncher) await launcher.first().click();
    else {
      const box = page.getByRole("checkbox").first();
      if (await box.count()) {
        await box.check();
        await page.getByRole("button", { name: "ถามจากคลิปที่เลือก" }).click();
      }
    }
    await page.screenshot({
      path: resolve(output, `chat-${width}.png`),
      fullPage: true,
    });
    await page.goto(`${origin}/login`);
    await page.screenshot({
      path: resolve(output, `login-${width}.png`),
      fullPage: true,
    });
    const googleLogin = await page
      .getByRole("button", { name: /Google/ })
      .count();
    evidence.views.push({
      width,
      launcher_present: hasLauncher,
      google_button_present: googleLogin > 0,
      home_horizontal_overflow: overflow,
      screenshot_only: true,
    });
    await context.tracing.stop({ path: resolve(output, `trace-${width}.zip`) });
    await context.close();
  }
  const assets = resolve(web, "dist/assets");
  for (const name of await readdir(assets)) {
    const path = resolve(assets, name);
    const item = { name, bytes: (await stat(path)).size };
    if (/\.(js|css)$/.test(name))
      item.gzip_bytes = gzipSync(await readFile(path)).length;
    evidence.bundles.push(item);
  }
  if (evidence.views.some((view) => !view.launcher_present))
    evidence.blockers.push(
      "floating_launcher_not_implemented_or_selector_not_bound",
    );
  if (evidence.views.some((view) => !view.google_button_present))
    evidence.blockers.push("login_entry_not_accepted_by_this_fixture_capture");
  evidence.blockers.push(
    "drag_motion_focus_ime_account_switch_require_strict_runtime_suite",
  );
} finally {
  await browser?.close();
  server.kill();
  await writeFile(resolve(output, "server.log"), logs);
  await writeFile(
    resolve(output, "evidence.json"),
    JSON.stringify(evidence, null, 2),
  );
}
console.log(resolve(output, "evidence.json"));
if (process.env.GITHUB_STEP_SUMMARY) {
  await appendFile(
    process.env.GITHUB_STEP_SUMMARY,
    "\nUI release acceptance: **BLOCKED / not granted by screenshot capture**.\n" +
      evidence.blockers.map((item) => `- ${item}\n`).join(""),
  );
}
if (process.argv.includes("--require-floating") && evidence.blockers.length)
  process.exitCode = 2;
