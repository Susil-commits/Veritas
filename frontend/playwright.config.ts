import { defineConfig } from '@playwright/test'
import path from 'node:path'

const ROOT_DIR = path.resolve(import.meta.dirname, '..')
const PYTHON_CMD = process.platform === 'win32'
  ? path.join(ROOT_DIR, '.venv', 'Scripts', 'python.exe')
  : 'python'

export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${PYTHON_CMD}" -m uvicorn main:app --host 127.0.0.1 --port 8000`,
      cwd: path.join(ROOT_DIR, 'backend'),
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: {
        VERITAS_TEST_MODE: 'true',
        VERITAS_MOCK_LLM: 'true',
        SESSION_SECRET_KEY: 'veritas_playwright_e2e_secret_min_32_bytes_ok!!',
      },
    },
    {
      command: 'npm run preview -- --host 127.0.0.1 --port 4173',
      url: 'http://127.0.0.1:4173',
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: {
        VITE_API_URL: 'http://127.0.0.1:8000',
      },
    },
  ],
})
