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

test("two anonymous browsers can join the same persistent draft", async ({ browser }) => {
  test.skip(
    !process.env.NEXT_PUBLIC_SUPABASE_URL
      || !process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
    "Requires the local Supabase integration environment.",
  );
  const hostContext = await browser.newContext();
  const guestContext = await browser.newContext();
  const host = await hostContext.newPage();
  const guest = await guestContext.newPage();

  await host.goto("/mock-drafts/new");
  await host.getByLabel("Draft name").fill("Playwright Multiplayer Draft");
  await host.getByRole("button", { name: "Create draft room" }).click();
  await host.waitForURL(/\/mock-drafts\/[0-9a-f-]+$/);
  await expect(host.getByRole("heading", { name: "Lobby" })).toBeVisible();

  await guest.goto(host.url());
  await expect(guest.getByRole("heading", { name: "Lobby" })).toBeVisible();
  await guest.getByRole("button", { name: "Claim" }).first().click();
  await expect(guest.getByRole("button", { name: "Leave slot" })).toBeVisible();

  await host.getByRole("button", { name: "Start draft" }).click();
  await expect(host.getByText("On the clock")).toBeVisible();
  await host.reload();
  await expect(host.getByText("On the clock")).toBeVisible();

  await hostContext.close();
  await guestContext.close();
});
