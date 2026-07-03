import { defineConfig, devices } from '@playwright/test';

const FRONTEND_URL = 'http://127.0.0.1:4173';
const BACKEND_URL = 'http://127.0.0.1:8000';

export default defineConfig({
  testDir: './e2e',
  // The backend plan store is a single process-wide singleton (see
  // api/store.py) with no per-test isolation, so specs that mutate the
  // plan (chat edits, excel import, drag-resize, reset) race each other
  // under fullyParallel workers and produce flaky cross-file failures.
  // Run test *files* serially (one worker) until the backend supports
  // per-test state; within a file, tests still run in source order.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: 'list',

  use: {
    baseURL: FRONTEND_URL,
    trace: 'on-first-retry',
  },

  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'mobile',
      use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 } },
    },
    {
      // Dedicated project for recording the demo scenario (see e2e/demo.spec.ts).
      // Only this project records video — desktop/mobile stay fast and
      // artifact-free for normal CI/local runs. Run with:
      //   npx playwright test demo --project=demo-recording
      name: 'demo-recording',
      testMatch: /demo\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        video: { mode: 'on', size: { width: 1440, height: 900 } },
      },
    },
  ],

  webServer: [
    {
      command: '.venv\\Scripts\\python.exe -m uvicorn api.index:app --port 8000',
      cwd: '..',
      env: {
        ENV: 'test',
        MOCK_LLM: '1',
      },
      url: `${BACKEND_URL}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: 'npm run build && npm run preview -- --port 4173 --host 127.0.0.1',
      url: FRONTEND_URL,
      env: {
        VITE_API_BASE: BACKEND_URL,
      },
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
