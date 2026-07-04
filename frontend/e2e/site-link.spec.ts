import { test, expect } from '@playwright/test';

test('header shows the filipp.io link pointing to the site', async ({ page }) => {
  await page.goto('/');
  const link = page.locator('[data-testid="site-link"]');
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute('href', 'https://filipp.io/');
  await expect(link).toContainText('filipp.io');
  await page.screenshot({ path: '../docs/shots/header-link-1440.png' });
});
