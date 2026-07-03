import { test, expect } from '@playwright/test';

test('app loads seeded gantt', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('ПЛАН ПРОЕКТА')).toBeVisible();
  // at least 20 task rows rendered
  const bars = page.locator('[data-testid="task-bar"]');
  await expect(bars).toHaveCount(await bars.count());
  expect(await bars.count()).toBeGreaterThanOrEqual(20);
});
