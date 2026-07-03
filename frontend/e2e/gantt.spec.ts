import { test, expect } from '@playwright/test';

test('critical path bars are visually distinct', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('[data-testid="today-line"]')).toBeVisible();
  // Task bars render only once the plan/schedule has loaded from the API
  // (today-line's position is computed independently of that fetch, so its
  // visibility alone doesn't guarantee bars are on screen yet) — poll
  // instead of a one-shot count to avoid a load-timing race.
  const critical = page.locator('[data-testid="task-bar"][data-critical="true"]');
  await expect(async () => {
    expect(await critical.count()).toBeGreaterThan(0);
  }).toPass();
});
