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

// ---- responsive sidebar (needs a signed-in synthetic user, same as the shell test above) ----
async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByLabel(/username|magaca/i).fill(user!);
  await page.getByLabel(/^password|erayga sirta/i).first().fill(password!);
  await page.getByRole("button", { name: /sign in|gal/i }).click();
  await expect(page.getByRole("navigation")).toBeAttached();
}
const noSideways = (page: import("@playwright/test").Page) =>
  page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);

for (const width of [1440, 1280]) {
  test(`sidebar @${width}: expanded by default, collapses to icons, expands again`, async ({ page }) => {
    test.skip(!user || !password, "set E2E_USER and E2E_PASSWORD");
    await page.setViewportSize({ width, height: 800 });
    await signIn(page);
    await expect(page.getByRole("button", { name: /open menu|fur liiska/i })).toBeHidden();
    const nav = page.locator("#app-sidebar");
    expect((await nav.boundingBox())?.width).toBeCloseTo(208, 0);
    await page.getByRole("button", { name: /collapse sidebar|yaree dhinaca/i }).click();
    expect((await nav.boundingBox())?.width).toBeCloseTo(64, 0);
    expect(await noSideways(page)).toBe(false);
    await page.getByRole("button", { name: /expand sidebar|balaadhi dhinaca/i }).click();
    expect((await nav.boundingBox())?.width).toBeCloseTo(208, 0);
  });
}

for (const width of [1024, 768]) {
  test(`sidebar @${width}: icon rail only (no hamburger, no collapse button), no sideways scroll`, async ({ page }) => {
    test.skip(!user || !password, "set E2E_USER and E2E_PASSWORD");
    await page.setViewportSize({ width, height: 800 });
    await signIn(page);
    const w = (await page.locator("#app-sidebar").boundingBox())?.width ?? 0;
    expect(w).toBeCloseTo(64, 0);
    await expect(page.getByRole("button", { name: /open menu|fur liiska/i })).toBeHidden();
    await expect(page.getByRole("button", { name: /collapse sidebar|expand sidebar|yaree dhinaca|balaadhi dhinaca/i })).toBeHidden();
    expect(await noSideways(page)).toBe(false);
  });
}

for (const width of [430, 390, 360, 320]) {
  test(`drawer @${width}: hidden at first, opens, closes via button / backdrop / Escape / link`, async ({ page }) => {
    test.skip(!user || !password, "set E2E_USER and E2E_PASSWORD");
    await page.setViewportSize({ width, height: 700 });
    await signIn(page);
    const menu = page.getByRole("button", { name: /open menu|fur liiska/i });
    const drawer = page.locator("#app-sidebar");
    await expect(drawer).toBeHidden();
    expect(await noSideways(page)).toBe(false);

    await menu.click();
    await expect(drawer).toBeVisible();
    await expect(page.getByRole("button", { name: /close menu|xir liiska/i })).toBeFocused();
    expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");

    await page.getByRole("button", { name: /close menu|xir liiska/i }).click();
    await expect(drawer).toBeHidden();
    await expect(menu).toBeFocused();

    await menu.click();
    await page.mouse.click(width - 5, 350); // backdrop (drawer is at most 85% wide)
    await expect(drawer).toBeHidden();

    await menu.click();
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();

    await menu.click();
    await drawer.getByRole("link").nth(1).click(); // second destination available to this user
    await expect(drawer).toBeHidden();
    await page.goBack();
    await expect(drawer).toBeHidden();
  });
}
