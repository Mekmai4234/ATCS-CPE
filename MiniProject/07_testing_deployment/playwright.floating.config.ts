import base from "./playwright.config";
import { resolve } from "node:path";

export default {
  ...base,
  testDir: "./tests/floating",
  use: { ...base.use, baseURL: "http://127.0.0.1:3005" },
  webServer: [
    {
      command:
        "node node_modules/vite/bin/vite.js --mode session-tests --host 127.0.0.1 --port 3005",
      cwd: resolve(__dirname, "../01_web_app"),
      url: "http://127.0.0.1:3005",
      reuseExistingServer: false,
      env: { VITE_DEMO_MODE: "false" },
    },
  ],
  outputDir: "./runtime/floating-results",
  reporter: [
    ["list"],
    ["html", { outputFolder: "./runtime/floating-report", open: "never" }],
  ],
};
