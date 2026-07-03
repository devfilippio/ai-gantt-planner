import { test, expect } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// `dirname` isn't available here — the project sets `"type": "module"` in
// package.json, so Playwright transforms spec files as ESM, where CJS
// dirname globals are undefined. Derive it from `import.meta.url` instead.
const dirname = path.dirname(fileURLToPath(import.meta.url));

test.beforeEach(async ({ page }) => {
  // Shared backend store across parallel workers (see chat.spec.ts) — reset
  // before each import/export test so results don't depend on run order.
  await page.request.post('http://127.0.0.1:8000/api/reset');
});

test('import sample plan renders at least 20 bars', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('toolbar-import').setInputFiles(
    path.resolve(dirname, '../../sample-data/plan.xlsx'),
  );
  const bars = page.locator('[data-testid="task-bar"]');
  await expect.poll(async () => bars.count()).toBeGreaterThanOrEqual(20);
});

test('export triggers an xlsx download', async ({ page }) => {
  await page.goto('/');
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByTestId('toolbar-export').click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.xlsx$/);
});

test('importing a broken file surfaces a row-level toast', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('toolbar-import').setInputFiles(
    path.resolve(dirname, 'fixtures/broken.xlsx'),
  );
  await expect(page.getByTestId('toast')).toContainText('строка');
});
