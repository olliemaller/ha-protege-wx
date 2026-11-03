# Accessibility

Everyone in a home should be able to arm, disarm and check the alarm, including people who use a screen reader, larger text, voice or a switch.

## What the integration does

- **Works with Home Assistant's own accessible interfaces.** Every alarm, lock and sensor is a standard entity, so it works with the built-in cards, the Companion app's accessibility features, Apple Home and VoiceOver.
- **Voice.** Ask Assist "Is the house armed?", "Can I arm?" and "Who came in last?". See [Voice](docs/Voice.md).
- **Plain language.** States, errors, logbook lines and notifications are short sentences, for example "Living is open", not codes.
- **Never colour alone.** Every state on the alarm card is written in words as well as shown by colour.

## The alarm card

- Follows your Home Assistant theme, including dark mode.
- Buttons are 44 pixels high, and the keypad keys are 60 pixels across.
- Every control is a real button with a label screen readers can read, and shows a clear focus ring when used from a keyboard.
- Errors are announced to screen readers.
- Countdown and status changes are written out, not only animated, and motion is reduced when your device asks for it.

## Known gaps

- Assist questions are English only.
- The card hasn't been tested with every screen reader. If something doesn't work for you, please tell us.

## Feedback

Found a barrier? [Open an issue](https://github.com/olliemaller/ha-protege-wx/issues/new/choose) and add **accessibility** to the title. Describe what you were trying to do, and the device, browser or assistive technology you use. These are treated as bugs, not feature requests.
