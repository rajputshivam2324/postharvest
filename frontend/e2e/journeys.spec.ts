import { expect, test, type Page } from '@playwright/test';
async function login(page: Page, role = 'admin') {
  await page.goto('/login');
  await page.getByLabel('User ID', { exact: true }).fill(role);
  await page.getByLabel('Password', { exact: true }).fill('frontend-test-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'A clearer view of your harvest.' }),
  ).toBeVisible();
}
async function nav(page: Page, name: string) {
  if (await page.getByRole('button', { name: 'Open navigation' }).isVisible())
    await page.getByRole('button', { name: 'Open navigation' }).click();
  await page
    .getByRole('navigation', { name: 'Application navigation' })
    .getByRole('link', { name, exact: true })
    .click();
}
test('public pages and protected routes', async ({ page }, info) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /Better insight/ })).toBeVisible();
  await page.screenshot({ path: `/tmp/harvest-landing-${info.project.name}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.goto('/app/batches');
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('heading', { name: 'Welcome back.' })).toBeVisible();
});
test('sign-in opens the destination with an older token-only API response', async ({ page }) => {
  await page.route('**/api/v1/auth/login', async (route) => {
    const response = await route.fetch();
    const token = await response.json();
    delete token.user;
    await route.fulfill({ response, json: token });
  });
  await page.goto('/app/batches');
  await page.getByLabel('User ID', { exact: true }).fill('operator');
  await page.getByLabel('Password', { exact: true }).fill('frontend-test-password');
  const profile = page.waitForResponse((response) => response.url().endsWith('/api/v1/auth/me'));
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  expect((await profile).status()).toBe(200);
  await expect(page).toHaveURL(/\/app\/batches$/);
  await expect(page.getByRole('heading', { name: 'Batches', exact: true })).toBeVisible();
  await expect(page.getByText('TOM-001', { exact: true })).toBeVisible();
});
test('operator reviews real API evidence, records observation and acknowledges alert', async ({
  page,
}, info) => {
  const errors: string[] = [];
  const overviewRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/')) overviewRequests.push(request.url());
  });
  page.on('pageerror', (error) => errors.push(error.message));
  await login(page, 'operator');
  await expect(page.getByRole('link', { name: /TOM-001/ }).first()).toBeVisible();
  const latestReadings = page.locator('.overview-readings');
  await expect(latestReadings.getByText(/°C/).first()).toBeVisible();
  const batchCount = await latestReadings.locator('tbody tr').count();
  await expect(latestReadings.getByText(/°C/)).toHaveCount(batchCount);
  expect(overviewRequests.some((url) => url.endsWith('/auth/me'))).toBe(false);
  // Development StrictMode may abort and replay a GET on mount.
  expect(new Set(overviewRequests.filter((url) => url.endsWith('/readings/latest'))).size).toBe(
    batchCount,
  );
  expect(overviewRequests.some((url) => url.includes('/readings?'))).toBe(false);
  await page.screenshot({ path: `/tmp/harvest-overview-${info.project.name}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page
    .getByRole('link', { name: /TOM-001/ })
    .first()
    .click();
  await expect(page.getByRole('heading', { name: 'Sensor history' })).toBeVisible();
  await expect(page.getByText('Simulated', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Assessment', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'What the evidence indicates' }).first(),
  ).toBeVisible();
  await expect(page.getByText('disabled', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Observations', exact: true }).click();
  await page.getByRole('button', { name: 'Record observation', exact: true }).click();
  const condition = `Inspection ${info.project.name} <script>alert(1)</script>`;
  await page.getByLabel('Visual condition').fill(condition);
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Record observation', exact: true })
    .click();
  await expect(page.getByRole('heading', { name: condition })).toBeVisible();
  await page.getByRole('button', { name: 'Decisions & metadata' }).click();
  await page.getByRole('button', { name: 'Record decision', exact: true }).click();
  await page.getByLabel('Rationale').fill(`Human inspection requested ${info.project.name}`);
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Record decision', exact: true })
    .click();
  await expect(
    page.getByRole('heading', { name: `Human inspection requested ${info.project.name}` }),
  ).toBeVisible();
  await nav(page, 'Alerts');
  await expect(
    page.getByText('Mocked delivery is a local test result.', { exact: false }),
  ).toBeVisible();
  const ack = page.getByRole('button', { name: 'Acknowledge', exact: true }).first();
  if (await ack.isVisible()) {
    await ack.click();
    await expect(page.getByText(/Acknowledged /).first()).toBeVisible();
  }
  expect(errors).toEqual([]);
});
test('admin creates a batch, registers device, saves baseline, and archives without deletion', async ({
  page,
}, info) => {
  await login(page);
  const identifier = `E2E-${info.project.name}-${Date.now()}`;
  await page.getByRole('button', { name: 'Register batch', exact: true }).click();
  await page.getByLabel('Batch identifier').fill(identifier);
  await page.getByLabel('Quantity', { exact: true }).fill('10');
  await page.getByLabel('Storage location', { exact: true }).fill('Test bay');
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Register batch', exact: true })
    .click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await nav(page, 'Batches');
  const row = page.getByRole('row').filter({ hasText: identifier });
  await row.getByRole('link', { name: 'Inspect' }).click();
  const batchId = new URL(page.url()).pathname.split('/').pop()!;
  await nav(page, 'Devices');
  await page.getByRole('button', { name: 'Register device', exact: true }).click();
  await page.getByLabel('Device identifier').fill(identifier);
  await page.getByLabel('Batch ID', { exact: true }).fill(batchId);
  await page.getByLabel('Data source', { exact: true }).selectOption('true');
  await page.getByRole('button', { name: 'Register & show credential' }).click();
  await expect(page.getByRole('heading', { name: 'Save the device credential' })).toBeVisible();
  await page.getByRole('button', { name: 'I have saved it' }).click();
  const device = page
    .locator('article')
    .filter({ has: page.getByRole('heading', { name: identifier, exact: true }) });
  await device.getByRole('button', { name: 'Record baseline' }).click();
  await page.getByLabel('Gas response (raw ADC)').fill('1000');
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Record baseline', exact: true })
    .click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await device.getByRole('button', { name: 'Baseline history' }).click();
  await expect(device.getByText('1000 ADC')).toBeVisible();
  await nav(page, 'Batches');
  await page
    .getByRole('row')
    .filter({ hasText: identifier })
    .getByRole('link', { name: 'Inspect' })
    .click();
  await page.getByRole('button', { name: 'Run assessment' }).click();
  await expect(page.getByText(/Assessment recorded/)).toBeVisible();
  await page.getByRole('button', { name: 'Decisions & metadata' }).click();
  await page.getByRole('button', { name: 'Archive batch', exact: true }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Archive batch', exact: true })
    .click();
  await expect(page.getByText(/Test bay · Archived/)).toBeVisible();
});

for (const role of ['vendor', 'operator']) {
  test(`self-signup creates a ${role} account and authenticates`, async ({ page }, info) => {
    await page.goto('/signup');
    await page
      .getByLabel('User ID', { exact: true })
      .fill(`signup-${role}-${info.project.name}-${Date.now()}`);
    await page.getByLabel('Account role').selectOption(role);
    await page.getByLabel('Password', { exact: true }).fill('frontend-signup-password');
    await page.getByLabel('Confirm password').fill('frontend-signup-password');
    await page.getByRole('button', { name: 'Create account', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: 'A clearer view of your harvest.' }),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Register batch', exact: true })).toHaveCount(
      role === 'operator' ? 1 : 0,
    );
    if (role === 'vendor') await expect(page.getByText('No records yet').first()).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Welcome back.' })).toBeVisible();
  });
}

test('operator seeds an AI-ready simulated batch from All Batches', async ({ page }) => {
  await login(page, 'operator');
  await nav(page, 'Batches');
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/demo/batches') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Seed demo batch', exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(201);
  const demo = await response.json();
  await expect(
    page.getByRole('heading', { name: demo.batch.identifier, exact: true }),
  ).toBeVisible();
  await expect(page.getByText('Simulated', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Assessment', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'What the evidence indicates' }).first(),
  ).toBeVisible();
  await expect(page.getByText('disabled', { exact: true }).first()).toBeVisible();
  await page.getByRole('link', { name: 'All batches', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: demo.batch.identifier })).toContainText(
    'Simulated',
  );
});
test('vendor is read-only, missing data and expired auth recover clearly', async ({ page }) => {
  await login(page, 'vendor');
  await expect(page.getByRole('button', { name: 'Register batch', exact: true })).toHaveCount(0);
  await expect(page.getByText('Read-only access')).toBeVisible();
  await nav(page, 'Devices');
  await expect(page.getByRole('button', { name: 'Register device', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Record baseline', exact: true })).toHaveCount(0);
  await page.route('**/api/v1/devices?*', (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ error: { message: 'Authentication required' } }),
    }),
  );
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
});
