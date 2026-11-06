import { expect, test } from '@playwright/test';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const path = resolve(__dirname, '../../eval/results.json');

test('the eval page renders the committed results, not typed numbers', async ({ page }) => {
  test.skip(!existsSync(path), 'no committed results yet');
  const results = JSON.parse(readFileSync(path, 'utf8'));
  const { baseline, grounded } = results.summary;
  await page.goto('/eval');
  await expect(page.getByTestId('base-numeric')).toHaveText(`${baseline.numeric_correct} / ${baseline.numeric_total}`);
  await expect(page.getByTestId('ground-numeric')).toHaveText(`${grounded.numeric_correct} / ${grounded.numeric_total}`);
  await expect(page.getByTestId('base-halluc')).toHaveText(String(baseline.answers_with_unsupported_figures));
  await expect(page.getByTestId('ground-halluc')).toHaveText(String(grounded.answers_with_unsupported_figures));
  await expect(page.getByTestId('eval-table').locator('tbody tr')).toHaveCount(results.questions.length);
  expect(results.mode).toBe('real');
});
