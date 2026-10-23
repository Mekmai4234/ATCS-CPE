import base from "./playwright.config";

export default {
  ...base,
  testDir: "./tests/floating",
  outputDir: "./runtime/floating-results",
  reporter: [
    ["list"],
    ["html", { outputFolder: "./runtime/floating-report", open: "never" }],
  ],
};
