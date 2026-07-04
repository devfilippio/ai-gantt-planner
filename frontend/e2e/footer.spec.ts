import { test, expect } from '@playwright/test';

test('footer link to filipp.io is present and points to the site', async ({ page }) => {
  await page.goto('/');
  const link = page.locator('[data-testid="site-footer"] a');
  await expect(link).toHaveAttribute('href', 'https://filipp.io/');
  await expect(link).toContainText('filipp.io');
  await expect(page.getByText('Автор — Филипп')).toBeVisible();
  // full-page screenshot for review
  await page.screenshot({ path: '../docs/shots/with-footer-1440.png', fullPage: true });
});
