/* Copyright (c) 2026 Filip Marić. See LICENCE. */
import { expect, test } from '@playwright/test';

test.describe('teacher attendance page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/attendance/review-demo');
  });

  test('renders a local QR code for the review session', async ({ page }) => {
    await expect(page.locator('#attendance-root')).toBeVisible();

    await expect(page.locator('.attendance-qr-box img')).toHaveAttribute(
      'src',
      /^data:image\/svg\+xml/,
    );
    await expect(page.locator('.attendance-code')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Заустави пријављивање' })).toBeVisible();
  });

  test('does not use an external QR image service', async ({ page }) => {
    const externalQrRequests = [];
    page.on('request', request => {
      if (request.url().includes('api.qrserver.com')) {
        externalQrRequests.push(request.url());
      }
    });

    await expect(page.locator('.attendance-qr-box img')).toBeVisible();

    expect(externalQrRequests).toEqual([]);
  });

  test('logs in as a teacher and starts and stops attendance', async ({ page }) => {
    await page.goto('/');
    await page.locator('#username').fill('e2e-teacher');
    await page.locator('#password').fill('local-test-password');
    await page.getByRole('button', { name: 'Пријава' }).click();
    await expect(page.locator('#login-info')).toHaveText('e2e-teacher');

    const target = await page.request.get('/__e2e__/attendance-target').then(response => response.json());
    await page.goto(`/attendance/weekly/${target.event_id}/${target.event_date}`);

    const startButton = page.getByRole('button', { name: 'Започни пријављивање' });
    await expect(startButton).toBeVisible();
    await startButton.click();
    await expect(page.getByRole('button', { name: 'Заустави пријављивање' })).toBeVisible();
    await expect(page.locator('.attendance-qr-box img')).toHaveAttribute('src', /^data:image\/svg\+xml/);

    await page.getByRole('button', { name: 'Заустави пријављивање' }).click();
    await expect(page.getByRole('button', { name: 'Започни пријављивање' })).toBeVisible();
  });
});
