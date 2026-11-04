# Changelog

## 0.4.2

- Setup now says clearly when an HTTPS address is entered: this integration uses the web interface over plain HTTP, and points HTTPS and licensed (Automation and Control) panels to [ICT Protege](https://github.com/caboose014/ICT-Protege-Home-Assistant) by caboose014.
- README: a "Which integration is right for you?" guide and a credit to caboose014's ICT Protege, which credits this project too.
- Documentation moved to [docs/](docs/README.md) (also published to the wiki); the README is now a short overview with the new alarm card in light and dark.
- Added a security policy, contributing guide, code of conduct, accessibility statement and pull request template.

## 0.4.1

- The project now stands on its own: the alarm card, README, brand images and blueprint no longer carry any company branding.
- Area, door, input and output devices now show Integrated Control Technology as their manufacturer.
- **Alarm card redesign:** quieter and easier to read. It uses your Home Assistant theme's font and colours, shows the state with a tinted icon, puts one line underneath about what matters now (open zones, the exit delay, who set it off), keeps the arm modes on one row, and has a round, phone-style PIN pad. Buttons respond to the press and respect reduced motion.

## 0.4.0

**Before you update**

- Needs nothing new. Home Assistant 2025.1 or later still works; the automation triggers and conditions need 2026.10 or later.
- Two entity names are shorter so they read well with Home Assistant 2026.11's device-plus-entity names: a door's **Door** sensor is now **Position**, and the controller's **Controller events** are now **Events**. Entity IDs you already have don't change.
- Outputs you added as switches now each get their own device, under the controller, so you can put them in an area. Their entity IDs don't change.

**New**

- **Arm when ready.** Each area has an **Arm when ready** switch and a mode select (Away, Home or Night), both under the area's configuration. The area arms the moment every zone closes and the panel says it's ready, or gives up after 30 minutes (set in the options) and says what was still open. Turn the switch off to stop. When arming needs a PIN, the switch refuses: use the alarm card's button or the `protege_wx.arm_when_ready` action with a code. Voice assistants don't get the switch by default, and turning on a whole area or device never arms the alarm. A reload or restart stops a wait and says so.
- **Automation triggers and conditions** in the automation editor (Home Assistant 2026.10+): Access granted (optionally only certain people, card or PIN), Access denied, Door forced or left open, Area failed to arm, and Duress, panic or medical alarm; and the condition Area is ready to arm.
- **Alarm card:** a visual editor (no YAML needed), an **Arm when ready** button while zones are open, a status dot beside the state, and pill buttons.
- **Home Assistant Marketplace ready** (2026.11): manifest categories, the HACS action passing with no ignored checks, and these notes shown in **Settings** > **Updates**.

**Fixed and tidied**

- Assist's "Is the house armed?", "Can I arm?" and "Who came in last?" weren't understood on Home Assistant 2026.x, which changed how integrations add sentences. They work again.
- Renaming an entity in Home Assistant 2026.11 updates it in place instead of removing and re-adding it. The Alarmo sync follows a renamed alarm panel.
- In the hour the clocks go back, controller log lines were read as an hour old, so Activity added "(at ...)" to them and a few checks treated them as history. The repeated hour is now read correctly.
- New README banner and brand icons.

## 0.3.2

- The alarm card's recent activity skips restart states and repeats.
