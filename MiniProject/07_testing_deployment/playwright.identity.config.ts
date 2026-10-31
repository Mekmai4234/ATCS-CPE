import base from "./playwright.config";

const artifacts = process.env.WEB_IDENTITY_PROJECT || "all";

export default {
  ...base,
  testDir: "./tests/browser",
  projects: [
    {
      name: "web-identity",
      testDir: "../01_web_app/tests/browser",
      testMatch: "identity.spec.ts",
    },
    {
      name: "deployment-identity",
      testDir: "./tests/browser",
      testMatch: "identity.spec.ts",
    },
  ],
  outputDir: `./runtime/browser-identity-results/${artifacts}`,
  reporter: [
    ["list"],
    [
      "html",
      {
        outputFolder: `./runtime/browser-identity-report/${artifacts}`,
        open: "never",
      },
    ],
  ],
};
