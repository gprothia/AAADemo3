// UI tests generated from specs/RSA-006-rate-my-rescue.md
import { test, expect } from '@playwright/test';
import { API, apiHeaders, apiToken, signIn } from './helpers';

async function createRequestInStatus(
  request: Parameters<typeof apiToken>[0],
  targetStatus: 'en_route' | 'completed',
  driverName = 'Marcus Vance',
): Promise<string> {
  const alice = await apiToken(request, 'alice');
  const created = await request.post(`${API}/v1/requests`, {
    data: { type: 'battery', location: 'Oak Ave & 12th', phone: '+1 555 010 7788' },
    headers: apiHeaders(alice),
  });
  expect(created.status()).toBe(201);
  const { id } = await created.json();

  const dana = await apiToken(request, 'dana');
  const steps = targetStatus === 'en_route' ? ['assigned', 'en_route'] : ['assigned', 'en_route', 'arrived', 'completed'];
  for (const status of steps) {
    const patch = await request.patch(`${API}/v1/requests/${id}`, {
      data:
        status === 'assigned'
          ? { status, driver_name: driverName, driver_truck: 'Flatbed #14', eta_minutes: 12 }
          : { status },
      headers: apiHeaders(dana),
    });
    expect(patch.status()).toBe(200);
  }
  return id as string;
}

test('rate completed rescue and block en-route rescues', { tag: '@RSA-006-AC10' }, async ({ page, request }) => {
  const completedId = await createRequestInStatus(request, 'completed');
  const enRouteId = await createRequestInStatus(request, 'en_route', 'Elena Rostova');

  await signIn(page, 'alice');
  await page.goto(`/rate?id=${completedId}`);

  await expect(page.getByRole('heading', { name: 'How did we do?' })).toBeVisible();
  await expect(page.getByRole('button', { name: '1 star' })).toBeVisible();
  await expect(page.getByRole('button', { name: '5 stars' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'On time' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Friendly driver' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Explained the fix' })).toBeVisible();
  await expect(page.getByLabel('Comments')).toBeVisible();

  await expect(page.getByTestId(`rescue-item-${enRouteId}`)).toContainText('Not yet completed');
});

test('submitting rating shows thank-you screen', { tag: '@RSA-006-AC11' }, async ({ page, request }) => {
  const completedId = await createRequestInStatus(request, 'completed');

  await signIn(page, 'alice');
  await page.goto(`/rate?id=${completedId}`);

  await page.getByRole('button', { name: '5 stars' }).click();
  await page.getByRole('button', { name: 'On time' }).click();
  await page.getByRole('button', { name: 'Explained the fix' }).click();
  await page.getByLabel('Comments').fill('Super quick and helpful!');
  await page.getByRole('button', { name: 'Submit Rating' }).click();

  await expect(page.getByRole('heading', { name: 'Thank you for your feedback!' })).toBeVisible();
  await expect(page.getByTestId('thanks-summary')).toContainText(completedId);
  await expect(page.getByTestId('thanks-summary')).toContainText('5 / 5');
  await expect(page.getByTestId('thanks-summary')).toContainText('On time');
  await expect(page.getByRole('link', { name: 'Rate Another Rescue' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Top Drivers This Month' })).toBeVisible();
});

test('public leaderboard shows top drivers this month', { tag: '@RSA-006-AC12' }, async ({ page }) => {
  await page.goto('/leaderboard');

  await expect(page.getByRole('heading', { name: 'Top drivers this month' })).toBeVisible();
  const list = page.getByTestId('leaderboard-list');
  await expect(list).toBeVisible();
  await expect(list.locator('.leader-row').first()).toBeVisible();
  await expect(list.locator('.leader-row img').first()).toBeVisible();
});
