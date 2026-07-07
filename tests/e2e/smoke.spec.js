// Minimal smoke test for the Stratum frontend: page loads, the core
// controls exist, and there are no console errors on a cold load. Kept
// intentionally loose on visual specifics (no text/color/layout assertions)
// since the frontend's design is actively evolving — this should keep
// passing across redesigns as long as the app still works.
const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

test("page loads with core controls and no console errors", async ({ page }) => {
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await page.goto("/");
  await expect(page).toHaveTitle(/Stratum/i);

  // Stable functional anchors from backend/main.py's contract, not visual ones.
  await expect(page.locator("#premise-form")).toBeAttached();
  await expect(page.locator("#premise-input")).toBeAttached();
  await expect(page.locator("#constraint-form")).toBeAttached();
  await expect(page.locator("#export-twee")).toBeAttached();
  await expect(page.locator("#export-html")).toBeAttached();
  await expect(page.locator("#hex-map")).toBeAttached();
  await expect(page.locator("#hex-tooltip")).toBeAttached();
  await expect(page.locator("#debate-log")).toBeAttached();
  await expect(page.locator("#gate-banner")).toBeAttached();
  await expect(page.locator("#scene-indicator")).toBeAttached();
  await expect(page.locator("#agent-timeline")).toBeAttached();
  await expect(page.locator("#canon-ledger")).toBeAttached();
  await expect(page.locator("#jump-gate-catch")).toBeAttached();
  await expect(page.locator("#judge-scorecard")).toBeAttached();
  await expect(page.locator("#scorecard-list")).toBeAttached();
  await expect(page.locator("#scorecard-export-twee")).toBeAttached();
  await expect(page.locator("#roster-list .roster-chip")).toHaveCount(7);

  expect(consoleErrors, `Unexpected console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});

test("accessibility: no critical or serious axe violations on cold load", async ({ page }) => {
  await page.goto("/");
  const results = await new AxeBuilder({ page }).analyze();
  const severe = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
  if (severe.length) {
    console.log(
      "Accessibility violations found:\n" +
        severe.map((v) => `- [${v.impact}] ${v.id}: ${v.description} (${v.nodes.length} node(s))`).join("\n")
    );
  }
  expect(severe, "Critical/serious accessibility violations found (see log above)").toEqual([]);
});
