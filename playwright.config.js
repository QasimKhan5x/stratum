// @ts-check
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  reporter: "list",
  use: {
    baseURL: process.env.STRATUM_FRONTEND_URL || "http://localhost:8090",
    screenshot: "only-on-failure",
  },
});
