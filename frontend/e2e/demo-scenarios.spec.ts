import { test, expect } from '@playwright/test';

// Three additional scripted screencasts, run only under the `demo-recording`
// Playwright project (see playwright.config.ts and e2e/demo.spec.ts for the
// original golden-path recording). Each test tells one focused story at a
// deliberate, human-watchable pace rather than racing to pass. Matched by the
// demo-recording project's broadened testMatch (see playwright.config.ts).
const beat = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

test.beforeEach(async ({ page }) => {
  // Same shared-store reset pattern as chat.spec.ts / modal.spec.ts — start
  // every recording from the known 7-task seed plan.
  await page.request.post('http://127.0.0.1:8000/api/reset');
});

test('demo: chat bulk-shift then undo', async ({ page }) => {
  await page.goto('/');
  await beat(1000); // let the seeded chart settle on screen

  const oleg = page.locator('[data-testid="task-bar"][data-assignee="Олег"]').first();
  const beforeEnd = await oleg.getAttribute('data-end');

  // 1. Bulk-edit via chat: move all of Oleg's tasks a week out.
  const chatInput = page.getByTestId('chat-input');
  await chatInput.click();
  await chatInput.fill('перенеси задачи Олега на неделю');
  await beat(700); // let the typed message be visible before sending
  await page.getByTestId('chat-send').click();

  await expect(page.getByTestId('tool-chip')).toContainText('shift_tasks');
  await expect.poll(async () => oleg.getAttribute('data-end')).not.toBe(beforeEnd);
  await beat(1800); // hold on the bars animating to their new dates

  // 2. Undo in plain language: the plan snaps back to where it was.
  await chatInput.click();
  await chatInput.fill('отмени последнее изменение');
  await beat(700);
  await page.getByTestId('chat-send').click();

  await expect.poll(async () => oleg.getAttribute('data-end')).toBe(beforeEnd);
  await beat(1500); // hold on the restored chart before the recording stops
});

test('demo: task modal — inspect, resize, jump to successor', async ({ page }) => {
  await page.goto('/');
  await beat(1000); // let the seeded chart settle on screen

  // 1. Open the modal for a mid-plan task with known predecessors/successors.
  const frontendBar = page.locator('[data-testid="task-bar"][data-id="frontend"]');
  await frontendBar.scrollIntoViewIfNeeded();
  await frontendBar.click();

  const modal = page.getByTestId('task-modal');
  await expect(modal).toBeVisible();
  await expect(page.getByTestId('task-mini-timeline')).toBeVisible();
  await beat(1000); // hold on the opened modal (mini-timeline, dates, badge)

  // 2. Grow the task's duration twice — bars behind the modal shift live.
  const beforeEnd = await modal.getAttribute('data-end');
  await page.getByTestId('duration-inc').click();
  await beat(700);
  await page.getByTestId('duration-inc').click();
  await expect.poll(() => modal.getAttribute('data-end')).not.toBe(beforeEnd);
  await beat(1200); // hold so the shifted bars behind the modal are visible

  // 3. Jump to the successor task via its chip.
  const succChip = page.getByTestId('succ-chip').first();
  await expect(succChip).toContainText('QA');
  await succChip.click();
  await expect(modal).toHaveAttribute('aria-label', /QA/);
  await beat(1200); // hold on the successor task's own details

  await page.keyboard.press('Escape');
  await expect(modal).toHaveCount(0);
  await beat(600);
});

test('demo: add a task via chat', async ({ page }) => {
  await page.goto('/');
  await beat(1000); // let the seeded chart settle on screen

  const barsBefore = page.locator('[data-testid="task-bar"]');
  const idsBefore = await barsBefore.evaluateAll((els) =>
    els.map((el) => el.getAttribute('data-id')),
  );

  // 1. Add a new task via chat, linked to an existing task by name.
  const chatInput = page.getByTestId('chat-input');
  await chatInput.click();
  await chatInput.fill('добавь задачу настройка аналитики, исполнитель Иван, 3 дня, после вёрстки');
  await beat(700); // let the typed message be visible before sending
  await page.getByTestId('chat-send').click();

  await expect(page.getByTestId('tool-chip')).toContainText('add_task');
  await expect.poll(async () => barsBefore.count()).toBe(idsBefore.length + 1);
  await beat(1800); // hold on the new bar appearing with its change highlight

  // 2. Click the new bar and confirm it's linked to "Вёрстка и интеграция".
  // Chain one `:not([data-id="..."])` per pre-existing id — a single
  // `:not(a, b, c)` (or `hasNot` on a descendant locator) does not work as
  // "exclude any of these", so each id needs its own `:not(...)`.
  const excludeSelector = idsBefore.map((id) => `:not([data-id="${id}"])`).join('');
  const newBar = page.locator(`[data-testid="task-bar"]${excludeSelector}`);
  await expect(newBar).toHaveCount(1);
  await newBar.scrollIntoViewIfNeeded();
  await newBar.click();

  const modal = page.getByTestId('task-modal');
  await expect(modal).toBeVisible();
  const predChip = page.getByTestId('pred-chip');
  await expect(predChip).toHaveCount(1);
  await expect(predChip.first()).toContainText('Вёрстка');
  await beat(1500); // hold on the new task's modal with its predecessor chip

  await page.keyboard.press('Escape');
  await expect(modal).toHaveCount(0);
  await beat(600);
});
