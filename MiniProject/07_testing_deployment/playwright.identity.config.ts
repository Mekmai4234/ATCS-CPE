import base from "./playwright.config";

export default {
  ...base,
  testDir: "./tests/browser",
  outputDir: "./runtime/browser-identity-results",
  reporter: [
    ["list"],
    [
      "html",
      { outputFolder: "./runtime/browser-identity-report", open: "never" },
    ],
  ],
};
