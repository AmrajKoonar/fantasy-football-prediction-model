import { expect, test } from "@playwright/test";

test("homepage and rankings critical path", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Fantasy Analytics" })).toBeVisible();
  await Promise.all([
    page.waitForURL("**/rankings"),
    page.getByRole("link", { name: "View rankings" }).click(),
  ]);
  await expect(page.getByRole("heading", { name: "Rankings" })).toBeVisible();
  await page.getByLabel("Position", { exact: true }).selectOption("RB");
  await page.getByLabel("Scoring", { exact: true }).selectOption("half_ppr");
  await expect(page.getByRole("table")).toBeVisible();
});

test("mock draft landing is discoverable", async ({ page }) => {
  await page.goto("/mock-drafts");
  await expect(page.getByRole("heading", { name: /mock draft with people/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /create a mock draft/i })).toBeVisible();
});

test("mock drafts are linked from primary navigation", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Mock Drafts" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /start a mock draft/i })).toBeVisible();
});
