import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  // The backend plan store is a shared singleton across the whole Playwright
  // run (fullyParallel workers all hit the same in-memory store), so tests
  // that mutate the plan reset it first to stay deterministic regardless of
  // execution order — mirrors the pattern in e2e/drag.spec.ts.
  await page.request.post('http://127.0.0.1:8000/api/reset');
});

test('agent bulk-shift updates chart and shows a tool chip', async ({ page }) => {
  await page.goto('/');
  const oleg = page.locator('[data-testid="task-bar"][data-assignee="Олег"]').first();
  const before = await oleg.getAttribute('data-end');
  await page.getByTestId('chat-input').fill('перенеси задачи Олега на неделю');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('tool-chip')).toContainText('shift_tasks');
  await expect.poll(async () => oleg.getAttribute('data-end')).not.toBe(before);
});

test('undo restores the plan', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('chat-input').fill('перенеси задачи Олега на неделю');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('tool-chip')).toBeVisible();
  await page.getByTestId('undo-btn').click();
  await expect(page.getByTestId('tool-chip')).toHaveCount(0);
});
