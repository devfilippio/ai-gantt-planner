import { test, expect } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// `dirname` isn't available here — the project sets `"type": "module"` in
// package.json, so Playwright transforms spec files as ESM, where CJS
// dirname globals are undefined. Derive it from `import.meta.url` instead.
const dirname = path.dirname(fileURLToPath(import.meta.url));

// This spec is not a correctness check — it's a scripted screencast of the
// core scenario (import -> chat edit -> export), run only under the
// `demo-recording` Playwright project (see playwright.config.ts), which
// turns video recording on. Steps pause deliberately so the resulting
// video/gif is readable by a human, not just fast enough to pass CI.
const beat = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

test('demo: import excel -> edit via chat -> export', async ({ page }) => {
  await page.request.post('http://127.0.0.1:8000/api/reset');

  await page.goto('/');
  await beat(1200); // let the seeded chart render and settle on screen

  // 1. Import the sample plan.
  await page.getByTestId('toolbar-import').setInputFiles(
    path.resolve(dirname, '../../sample-data/plan.xlsx'),
  );
  const bars = page.locator('[data-testid="task-bar"]');
  await expect.poll(async () => bars.count()).toBeGreaterThanOrEqual(20);
  await beat(1500); // hold on the imported Gantt chart

  // 2. Edit the plan in bulk via the chat agent.
  const chatInput = page.getByTestId('chat-input');
  await chatInput.click();
  await chatInput.fill('перенеси задачи Олега на неделю');
  await beat(600); // let the typed message be visible before sending
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('tool-chip')).toContainText('shift_tasks');
  await beat(2000); // hold on the live bar animation + tool chip

  // 3. Export the agent-edited plan back to Excel.
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByTestId('toolbar-export').click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.xlsx$/);
  await beat(1000); // hold on the final state before the recording stops
});
