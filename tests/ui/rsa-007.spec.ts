// UI tests generated from specs/RSA-007-sample-seed-data.md
import { test, expect } from '@playwright/test';
import { signIn } from './helpers';

test('alice sees her seeded requests across statuses', { tag: '@RSA-007-AC5' }, async ({ page }) => {
  await signIn(page, 'alice');
  await page.getByRole('link', { name: 'My requests' }).click();
  const table = page.getByRole('table', { name: 'Requests' });
  await expect(page.getByRole('heading', { name: 'My requests' })).toBeVisible();

  for (const id of ['RSA-1002', 'RSA-1003', 'RSA-1005']) {
    await expect(table.getByRole('link', { name: id })).toHaveCount(1);
  }
  for (const id of ['RSA-1001', 'RSA-1004', 'RSA-1006', 'RSA-1007']) {
    await expect(table.getByRole('link', { name: id })).toHaveCount(0);
  }
});

test('dana sees seeded requests for all members and statuses', { tag: '@RSA-007-AC6' }, async ({ page }) => {
  await signIn(page, 'dana');
  await page.getByRole('link', { name: 'All requests' }).click();
  const table = page.getByRole('table', { name: 'Requests' });
  await expect(page.getByRole('heading', { name: 'All requests' })).toBeVisible();

  for (const id of ['RSA-1001', 'RSA-1002', 'RSA-1003', 'RSA-1004', 'RSA-1005', 'RSA-1006', 'RSA-1007']) {
    await expect(table.getByRole('link', { name: id })).toHaveCount(1);
  }
});
