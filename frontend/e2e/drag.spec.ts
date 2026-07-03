import { test, expect } from '@playwright/test';

// Pointer-drag-to-resize is a precision desktop interaction (mouse hover on a
// thin edge handle). At narrow/mobile viewports the chart's SVG pane is
// horizontally scrollable and much of it sits outside the viewport, so
// synthetic mouse coordinates land unreliably — this spec is desktop-only by
// design; touch drag-resize is tracked as a follow-up, not required here.
test.skip(({ viewport }) => !!viewport && viewport.width < 1280, 'desktop-only interaction');

test('dragging a bar right edge resizes duration and shifts downstream tasks', async ({ page }) => {
  await page.goto('/');
  await page.request.post('http://127.0.0.1:8000/api/reset');
  await page.reload();

  const sourceBar = page.locator('[data-testid="task-bar"][data-id="research-market"]');
  const downstreamBar = page.locator('[data-testid="task-bar"][data-id="design-concept"]');

  await expect(sourceBar).toBeVisible();
  await expect(downstreamBar).toBeVisible();
  await sourceBar.scrollIntoViewIfNeeded();

  const beforeEnd = await sourceBar.getAttribute('data-end');
  const beforeDownstreamStart = await downstreamBar.getAttribute('data-start');

  const box = await sourceBar.boundingBox();
  if (!box) throw new Error('source bar has no bounding box');

  const dayWidth = 34; // matches GanttChart's day-zoom dayWidth
  const startX = box.x + box.width - 3;
  const startY = box.y + box.height / 2;

  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX + dayWidth, startY, { steps: 8 });
  await page.mouse.up();

  await expect.poll(() => sourceBar.getAttribute('data-end')).not.toBe(beforeEnd);
  await expect.poll(() => downstreamBar.getAttribute('data-start')).not.toBe(beforeDownstreamStart);
});
