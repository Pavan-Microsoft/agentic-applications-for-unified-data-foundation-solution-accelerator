# Message input character count

## Application Overview

Multi-Agent Custom Automation Engine web app. The landing page ("Multi-Agent Planner", heading "How can I help?") contains a single message textarea where the user describes a task. A live character counter is displayed immediately below the textarea in the format `N/5000` (max length 5000). This plan verifies that the counter accurately reflects the current length of the text in the input as characters are typed and cleared.

Discovered selectors:
- Textbox: role `textbox`, accessible name begins with `Tell us what needs planning,` (full placeholder: "Tell us what needs planning, building, or connecting—we'll handle the rest."). Underlying element is a `<textarea>`.
- Counter: static text node matching the pattern `^\d+\/5000$`, sits in the container immediately below the textbox (same parent as the send toolbar).
- Initial counter value on a fresh page load: `0/5000`.
- Observed behavior: counter updates synchronously as the textarea value changes (typing "Hello world" -> `11/5000`; clearing -> `0/5000`).

## Test Scenarios

### 1. Message input character count

**Seed:** `e2e/seed.spec.ts`

#### 1.1. should update the character count to reflect the typed message length

**File:** `tests/message-input/character-count-reflects-typed-message.spec.ts`

**Steps:**
  1. Navigate to https://app-mv403b4qbg.azurewebsites.net and wait for the initial `Loading...` indicator to disappear, then wait for the `Loading team configuration...` progressbar to disappear so the planner UI is fully rendered.
    - expect: The page title is `Multi-Agent - Custom Automation Engine`.
    - expect: The heading text `How can I help?` is visible.
    - expect: The message textbox (role `textbox`, accessible name starting with `Tell us what needs planning,`) is visible and enabled.
  2. Locate the character counter element by finding the text matching the regular expression `/^\d+\/5000$/` in the region below the textbox.
    - expect: The counter is visible.
    - expect: The counter's initial text is exactly `0/5000`.
  3. Click the message textbox to focus it, then type the exact string `Hello world` (11 characters, including the single space).
    - expect: The textbox has value `Hello world`.
    - expect: The counter text updates to exactly `11/5000`, matching the length of the typed string.
  4. Append the additional string ` from Playwright` (16 more characters including the leading space) to the textbox so the full contents become `Hello world from Playwright` (27 characters total).
    - expect: The textbox has value `Hello world from Playwright`.
    - expect: The counter text updates to exactly `27/5000`, matching the new length.
  5. Clear the textbox by selecting all of its contents (ControlOrMeta+A) and pressing Backspace (or by filling it with an empty string).
    - expect: The textbox has an empty value.
    - expect: The counter text returns to exactly `0/5000`.
