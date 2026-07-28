import { expect, test } from "@playwright/test";

test("homepage and rankings critical path", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Field Forecast" })).toBeVisible();
  await page.getByRole("link", { name: "View rankings" }).click();
  await expect(page.getByRole("heading", { name: "Rankings" })).toBeVisible();
  await page.getByLabel("Position").selectOption("RB");
  await page.getByLabel("Scoring").selectOption("half_ppr");
  await expect(page.getByRole("table")).toBeVisible();
});
