import { defineConfig } from '@playwright/test';

const python = process.env['PYTHON'] ?? '.venv/bin/python';

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: process.env['CI'] ? 'github' : 'list',
  use: { baseURL: 'http://127.0.0.1:4300', channel: process.env['PW_CHANNEL'], trace: 'retain-on-failure', viewport: { width: 1440, height: 900 } },
  webServer: {
    command: `${python} -m scripts.serve_built`,
    cwd: '..',
    url: 'http://127.0.0.1:4300/api/health',
    env: { LLM_MODE: 'mock', RATE_LIMIT_PER_HOUR: '100000', DAILY_LLM_CAP: '100000' },
    reuseExistingServer: !process.env['CI'],
  },
});
