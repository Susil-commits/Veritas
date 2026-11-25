import { test, expect } from '@playwright/test'

test.describe('Veritas Critical User Flows', () => {
  test('demo student enters TutorSession, streams Socratic reply, and generates Parent Pairing Code', async ({ page }) => {
    await page.goto('/#demo')

    // 1. Click 1-click Demo Student pill from Landing
    const demoStudentBtn = page.getByRole('button', { name: /Demo as Student/i }).first()
    await expect(demoStudentBtn).toBeVisible({ timeout: 15_000 })
    await demoStudentBtn.click()

    await page.waitForURL(/\/student-session/, { timeout: 20_000 })

    // 2. Verify active practice input & submit a student message
    const chatInput = page.locator('input[placeholder*="thinking"], input[placeholder*="answer"], textarea').first()
    await expect(chatInput).toBeVisible({ timeout: 20_000 })
    await chatInput.fill('I think we should multiply first')
    await chatInput.press('Enter')

    // Expect Socratic tutor reply bubble
    await expect(page.locator('.tutor-bubble, .message-tutor, [class*="tutor"]').first()).toBeVisible({ timeout: 20_000 })

    // 3. Open Parent Link modal and generate 6-digit pairing code
    const parentLinkBtn = page.getByRole('button', { name: /Parent Link/i }).first()
    await expect(parentLinkBtn).toBeVisible()
    await parentLinkBtn.click()

    await expect(page.getByText(/Parent Account Linking/i)).toBeVisible()
    await page.getByRole('button', { name: /Generate 6-Digit Pairing Code/i }).click()

    await expect(page.getByText(/15-Minute Pairing Code/i)).toBeVisible({ timeout: 10_000 })
  })

  test('demo student navigates to Math Arcade and launches server-verified Level 1', async ({ page }) => {
    await page.goto('/#demo')
    const demoStudentBtn = page.getByRole('button', { name: /Demo as Student/i }).first()
    await expect(demoStudentBtn).toBeVisible({ timeout: 15_000 })
    await demoStudentBtn.click()
    await page.waitForURL(/\/student-session/, { timeout: 20_000 })

    await page.goto('/arcade')
    await expect(page.getByText('Multiplier Matrix')).toBeVisible({ timeout: 15_000 })

    // Launch Level 1 Blitz arena and ensure server round loads plasma answer bubbles
    const playBtn = page.getByRole('button', { name: /Play Game/i }).first()
    await expect(playBtn).toBeVisible()
    await playBtn.click()

    await expect(page.locator('.plasma-bubble-btn').first()).toBeVisible({ timeout: 15_000 })
  })
})
