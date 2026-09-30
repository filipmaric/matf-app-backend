/* Copyright (c) 2026 Filip Marić. See LICENCE. */
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 15_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: 'http://127.0.0.1:5173',
    browserName: 'chromium',
    headless: true,
  },
  webServer: {
    command: 'APP_ENV=development REVIEW_MODE=1 DATABASE=/tmp/matf-app-attendance-e2e.db .venv/bin/python3 e2e/server.py',
    cwd: '..',
    url: 'http://127.0.0.1:5173/healthz',
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
