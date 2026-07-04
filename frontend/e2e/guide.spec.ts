import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  // Mirrors e2e/chat.spec.ts — the backend plan store is a shared singleton,
  // so reset first to stay deterministic regardless of run order.
  await page.request.post('http://127.0.0.1:8000/api/reset');
});

test('commands guide shows 8 cards and fills the chat input on click', async ({ page }) => {
  await page.goto('/');

  const guide = page.getByTestId('commands-guide');
  await expect(guide).toBeVisible();

  const cards = page.getByTestId('guide-cmd');
  await expect(cards).toHaveCount(8);

  const firstCardText = await cards.first().textContent();
  await cards.first().click();

  const input = page.getByTestId('chat-input');
  await expect(input).toBeFocused();
  const value = await input.inputValue();
  expect(firstCardText).toContain(value);
  expect(value).toBe('перенеси задачи Олега на неделю');
});
