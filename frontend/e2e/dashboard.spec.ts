import { expect, test } from '@playwright/test';

const ready = (page: import('@playwright/test').Page) =>
  expect(page.getByTestId('interpretation')).toHaveAttribute('data-state', 'ok');

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await ready(page);
});

test('changing a filter updates the charts and the interpretation', async ({ page }) => {
  const summary = page.getByTestId('summary');
  const before = await summary.textContent();
  await expect(page.getByTestId('kpi-n')).toHaveText('3,000');
  await page.getByTestId('filter-region').selectOption('North');
  await expect(page.getByTestId('interpretation')).toHaveAttribute('data-state', 'loading');
  await ready(page);
  await expect(summary).not.toHaveText(before!);
  await expect(page.getByTestId('kpi-n')).not.toHaveText('3,000');
  expect((await page.getByTestId('kpi-n').textContent())!.replace(',', '')).toBe((await summary.textContent())!.match(/[\d,]+/)![0].replace(',', ''));
  await expect(page.getByTestId('verified')).toContainText('figures verified');
});

test('clicking a finding highlights the matching chart series', async ({ page }) => {
  const trend = page.locator('[data-chart=trend]');
  await expect(trend.locator('.highcharts-series.highcharts-line-series').first()).toBeVisible();
  await expect(trend.locator('.q-dim')).toHaveCount(0);

  await page.getByTestId('finding').first().click();
  await expect(trend).toHaveClass(/lit/);
  const series = await trend.getAttribute('data-lit-series');
  expect(series).toBeTruthy();
  await expect(trend.locator('.highcharts-series.q-lit')).toHaveCount(1);
  await expect(trend.locator('.highcharts-series.q-dim')).toHaveCount(5);
  await expect(page.getByTestId('evidence')).toBeVisible();

  await page.getByTestId('finding').first().click();
  await expect(trend).not.toHaveClass(/lit/);
  await expect(trend.locator('.highcharts-series.q-dim')).toHaveCount(0);
});

test('a tiny filter refuses to interpret and hides its figures', async ({ page }) => {
  await page.getByTestId('filter-period').selectOption('2026-Q1');
  await page.getByTestId('filter-department').selectOption('Finance');
  await page.getByTestId('filter-role').selectOption('Director');
  await expect(page.getByTestId('insufficient')).toContainText('Not enough data');
  await expect(page.getByTestId('kpi-n')).toHaveText('Fewer than 5');
  await expect(page.getByTestId('finding')).toHaveCount(0);
});

test('the language toggle changes the AI output', async ({ page }) => {
  await page.getByTestId('lang-de').click();
  await expect(page.getByTestId('summary')).toContainText('Antworten');
  await expect(page.getByTestId('summary')).toContainText('3.000');
});

test('the chat applies dashboard filters through a tool call', async ({ page }) => {
  await page.getByTestId('tab-chat').click();
  await page.getByTestId('chat-input').fill('show me only the north region in 2026');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('chat-answer').last()).toHaveAttribute('data-type', 'filters_applied');
  await expect(page.getByTestId('filter-region')).toHaveValue('North');
  await expect(page.getByTestId('filter-period')).toHaveValue('2026');
  await expect(page.getByTestId('kpi-n')).toHaveText('499');
});

test('the chat says when the data cannot answer', async ({ page }) => {
  await page.getByTestId('tab-chat').click();
  await page.getByRole('button', { name: 'What is the average salary?' }).click();
  const answer = page.getByTestId('chat-answer').last();
  await expect(answer).toHaveAttribute('data-type', 'cannot_answer');
  await expect(answer).toContainText("Can't answer from this data");
});

test('an API failure shows a recoverable error', async ({ page }) => {
  await page.route('**/api/interpret', (r) => r.fulfill({ status: 500, body: '{}' }));
  await page.getByTestId('filter-region').selectOption('South');
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
  await page.unroute('**/api/interpret');
  await page.getByRole('button', { name: 'Try again' }).click();
  await ready(page);
});

test('applications flag gaps and cite fields', async ({ page }) => {
  await page.goto('/applications');
  await expect(page.getByTestId('statements')).toBeVisible();
  await expect(page.getByTestId('flags')).toContainText('Target sample size was not provided');
  await page.getByTestId('app-item').nth(2).click();
  await expect(page.getByTestId('flags')).toContainText('Budget lines add up to EUR 125,000');
  await page.getByTestId('app-item').first().click();
  await expect(page.getByTestId('no-flags')).toBeVisible();
});

test('the footer credit links to DC Tech', async ({ page }) => {
  await expect(page.getByRole('link', { name: 'DC Tech' })).toHaveAttribute('href', 'https://dctechltd.com');
});

test('the data flow page lists what leaves the server', async ({ page }) => {
  await page.goto('/data-flow');
  await expect(page.getByRole('heading', { name: 'What leaves the server' })).toBeVisible();
});

test('the page has no sideways scroll on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto('/');
  await ready(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
