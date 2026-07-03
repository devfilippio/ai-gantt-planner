import { test, expect } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// `dirname` isn't available here — the project sets `"type": "module"` in
// package.json, so Playwright transforms spec files as ESM, where CJS
// dirname globals are undefined. Derive it from `import.meta.url` instead.
const dirname = path.dirname(fileURLToPath(import.meta.url));

test.beforeEach(async ({ page }) => {
  // Shared backend store across parallel workers (see chat.spec.ts) — reset
  // before each run so the golden path is deterministic regardless of what
  // other spec files did to the singleton store beforehand.
  await page.request.post('http://127.0.0.1:8000/api/reset');
});

test('golden path: import excel -> edit via chat -> export', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('toolbar-reset').click();

  // 1. Import the sample plan (>= 20 tasks).
  await page.getByTestId('toolbar-import').setInputFiles(
    path.resolve(dirname, '../../sample-data/plan.xlsx'),
  );
  const bars = page.locator('[data-testid="task-bar"]');
  await expect.poll(async () => bars.count()).toBeGreaterThanOrEqual(20);

  // 2. Edit the plan in bulk via the chat agent (deterministic MockLLM).
  await page.getByTestId('chat-input').fill('перенеси задачи Олега на неделю');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('tool-chip')).toContainText('shift_tasks');

  // 3. Export the (now agent-edited) plan back to Excel.
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByTestId('toolbar-export').click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.xlsx$/);
});
