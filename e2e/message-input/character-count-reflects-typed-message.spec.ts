// spec: specs/plan.md
// seed: e2e/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('Message input character count', () => {
  test('should update the character count to reflect the typed message length', async ({ page }) => {
    const messageTextbox = page.getByRole('textbox', { name: /^Tell us what needs planning,/ });
    const counter = page.getByText(/^\d+\/5000$/);

    // 1. Navigate to the app root and wait for the initial `Loading...` indicator to disappear,
    //    then wait for the `Loading team configuration...` progressbar to disappear.
    await page.goto('/');
    await page.getByText('Loading...').first().waitFor({ state: 'hidden' });
    await page.getByText('Loading team configuration').first().waitFor({ state: 'hidden' });
    await expect(page).toHaveTitle('Multi-Agent - Custom Automation Engine');
    await expect(page.getByText('How can I help?')).toBeVisible();
    await expect(messageTextbox).toBeVisible();
    await expect(messageTextbox).toBeEnabled();

    // 2. Locate the character counter element and verify its initial state.
    await expect(counter).toBeVisible();
    await expect(counter).toHaveText('0/5000');

    // 3. Click the message textbox to focus it, then type `Hello world` (11 characters).
    await messageTextbox.click();
    await messageTextbox.pressSequentially('Hello world');
    await expect(messageTextbox).toHaveValue('Hello world');
    await expect(counter).toHaveText('11/5000');

    // 4. Append ` from Playwright` so the full contents become `Hello world from Playwright`.
    await messageTextbox.pressSequentially(' from Playwright');
    await expect(messageTextbox).toHaveValue('Hello world from Playwright');
    await expect(counter).toHaveText('27/5000');

    // 5. Clear the textbox by selecting all (ControlOrMeta+A) and pressing Backspace.
    await messageTextbox.press('ControlOrMeta+A');
    await messageTextbox.press('Backspace');
    await expect(messageTextbox).toHaveValue('');
    await expect(counter).toHaveText('0/5000');
  });
});
