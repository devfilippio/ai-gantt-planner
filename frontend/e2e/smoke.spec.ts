import { test, expect } from '@playwright/test';

test('app loads seeded gantt', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('ПЛАН ПРОЕКТА')).toBeVisible();
  // at least 7 task rows rendered
  const bars = page.locator('[data-testid="task-bar"]');
  await expect(async () => {
    expect(await bars.count()).toBeGreaterThanOrEqual(7);
  }).toPass();
});
