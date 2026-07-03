import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  // Shared backend store across parallel workers (see chat.spec.ts) — reset
  // so the seeded task list (with known predecessor chains) is stable.
  await page.request.post('http://127.0.0.1:8000/api/reset');
});

test('clicking a bar opens the modal with matching dates and predecessors', async ({ page }) => {
  await page.goto('/');

  const firstBar = page.locator('[data-testid="task-bar"]').first();
  const start = await firstBar.getAttribute('data-start');
  const end = await firstBar.getAttribute('data-end');

  await firstBar.click();

  const modal = page.getByTestId('task-modal');
  await expect(modal).toBeVisible();
  await expect(modal).toHaveAttribute('data-start', start ?? '');
  await expect(modal).toHaveAttribute('data-end', end ?? '');

  await page.keyboard.press('Escape');
  await expect(modal).toHaveCount(0);
});

test('modal shows predecessor chips for a dependent task', async ({ page }) => {
  await page.goto('/');

  // `ios-client` (Разработка iOS-клиента) is seeded with three
  // predecessors (api-auth, design-onboarding, design-profile) — a stable,
  // known-dependent task to assert chip rendering against, rather than
  // scanning bars at runtime.
  const bar = page.locator('[data-testid="task-bar"][data-id="ios-client"]');
  await bar.scrollIntoViewIfNeeded();
  await bar.click();

  const modal = page.getByTestId('task-modal');
  await expect(modal).toBeVisible();

  const chips = page.getByTestId('pred-chip');
  await expect(chips).toHaveCount(3);

  await page.keyboard.press('Escape');
  await expect(modal).toHaveCount(0);
});
