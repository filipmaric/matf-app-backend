/* Copyright (c) 2026 Filip Marić. See LICENCE. */
import { expect, test } from '@playwright/test';

test.describe('room reservations', () => {
  test('allows selecting a canceled class interval for a reservation', async ({ page }) => {
    const target = await page.request
      .get('/__e2e__/reservation-target')
      .then(response => response.json());

    await page.goto(`/` + `?date=${target.date}`);
    await page.locator('#username').fill('e2e-teacher');
    await page.locator('#password').fill('local-test-password');
    const refreshedOccupancy = page.waitForResponse(
      response => response.url().includes('/occupancy?date=') && response.request().method() === 'GET',
    );
    await page.getByRole('button', { name: 'Пријава' }).click();
    await expect(page.locator('#login-info')).toHaveText('e2e-teacher');
    await refreshedOccupancy;

    const firstSensor = page.locator(
      `.drag-sensor.empty-slot[data-room_id="${target.room_id}"][data-hour="${target.start_slot}"]`,
    );
    const secondSensor = page.locator(
      `.drag-sensor.empty-slot[data-room_id="${target.room_id}"][data-hour="${target.start_slot + 1}"]`,
    );
    await expect(firstSensor).toBeVisible();
    await expect(secondSensor).toBeVisible();

    page.once('dialog', dialog => dialog.accept('E2E reservation'));
    const reserveResponse = page.waitForResponse(
      response => response.url().endsWith('/reserve') && response.request().method() === 'POST',
    );

    await firstSensor.dispatchEvent('mousedown', { button: 0 });
    await secondSensor.dispatchEvent('mouseover');
    await page.evaluate(() => document.dispatchEvent(new MouseEvent('mouseup')));

    expect((await reserveResponse).status()).toBe(201);
    await expect(page.locator('.res-desc')).toContainText('E2E reservation');
    await expect(page.locator('.res-cancel-btn')).toBeVisible();
  });
});
