import { test, expect } from '@playwright/test';

test('critical path bars are visually distinct', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('[data-testid="today-line"]')).toBeVisible();
  const critical = page.locator('[data-testid="task-bar"][data-critical="true"]');
  expect(await critical.count()).toBeGreaterThan(0);
});
