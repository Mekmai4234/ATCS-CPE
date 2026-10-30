// Execute module 01's reviewed browser tests using downloaded Chromium in CI.
import base from "../01_web_app/playwright.config";
import { resolve } from "node:path";

export default {
  ...base,
  testDir: "../01_web_app/tests/browser",
  outputDir: "./runtime/browser-results",
  reporter: [
    ["list"],
    ["html", { outputFolder: "./runtime/browser-report", open: "never" }],
  ],
  use: { ...base.use, channel: undefined },
  webServer: (Array.isArray(base.webServer)
    ? base.webServer
    : [base.webServer]
  ).map((server) => ({
    ...server,
    cwd: resolve(__dirname, "../01_web_app"),
  })),
};
