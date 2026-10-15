import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Layout, language and accessibility smoke tests. Authenticated checks need E2E_USER / E2E_PASSWORD
// (a synthetic account; accounts needing MFA are not supported here and are skipped).
const user = process.env.E2E_USER;
const password = process.env.E2E_PASSWORD;

for (const lang of ["en", "so"] as const) {
  test(`login page (${lang}): usable, labelled, no serious accessibility violations`, async ({ page }) => {
    await page.addInitScript((l) => localStorage.setItem("armyhq.lang", l), lang);
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("lang", /./);
    await expect(page.getByLabel(/./).first()).toBeVisible();
    const hasHorizontalScroll = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(hasHorizontalScroll, "page must not scroll sideways").toBe(false);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
}

test("primary controls are comfortably tappable", async ({ page }) => {
  await page.goto("/");
  for (const button of await page.getByRole("button").all()) {
    const box = await button.boundingBox();
    expect(box?.height ?? 0, "buttons should be at least 40px tall").toBeGreaterThanOrEqual(40);
  }
});

test("language can be switched and is remembered", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /soomaali|english/i }).click();
  const lang = await page.evaluate(() => localStorage.getItem("armyhq.lang"));
  expect(["en", "so"]).toContain(lang);
});

test("signed-in shell: scope strip, navigation and dashboard have no serious violations", async ({ page }) => {
  test.skip(!user || !password, "set E2E_USER and E2E_PASSWORD (non-MFA synthetic user)");
  await page.goto("/");
  await page.getByLabel(/username|magaca/i).fill(user!);
  await page.getByLabel(/^password|erayga sirta/i).first().fill(password!);
  await page.getByRole("button", { name: /sign in|gal/i }).click();
  await expect(page.getByRole("navigation")).toBeVisible();
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
});
