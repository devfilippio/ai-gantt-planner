import { test, expect } from '@playwright/test';

// Regression: owner added a task via chat («анна купит молоко 13 июля до 15»)
// — the confirmation showed but the task didn't appear on the chart. Root
// cause was an out-of-sync final state; ChatPanel now reconciles with the
// server (syncPlan) when the turn ends, so a dropped mid-stream patch can't
// leave the Gantt behind.
test('adding a task via chat makes an 8th bar appear and stay', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('toolbar-reset').click();
  await expect(page.locator('[data-testid="task-bar"]')).toHaveCount(7, { timeout: 10000 });

  await page.getByTestId('chat-input').fill('перенеси задачи Олега на неделю');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('tool-chip').first()).toBeVisible();

  await page.getByTestId('chat-input').fill('пусть анна купит молоко 13 июля до 15 июля');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('tool-chip').filter({ hasText: 'add_task' })).toBeVisible();

  await expect(page.locator('[data-testid="task-bar"]')).toHaveCount(8, { timeout: 10000 });
  await page.waitForTimeout(2000);
  await expect(page.locator('[data-testid="task-bar"]')).toHaveCount(8);
  // the new task's NAME row is present in the left column (scoped so it can't
  // ambiguously match the chat chip/message)
  await expect(page.locator('.gantt__row-name', { hasText: 'Купить молоко' })).toHaveCount(1);
});
