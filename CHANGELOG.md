# Changelog

## 0.4.0

**Before you update**

- Needs nothing new. Home Assistant 2025.1 or later still works; the automation triggers and conditions need 2026.10 or later.
- Two entity names are shorter so they read well with Home Assistant 2026.11's device-plus-entity names: a door's **Door** sensor is now **Position**, and the controller's **Controller events** are now **Events**. Entity IDs you already have don't change.
- Outputs you added as switches now each get their own device, under the controller, so you can put them in an area. Their entity IDs don't change.

**New**

- **Arm when ready.** Each area has an **Arm when ready** switch and a mode select (Away, Home or Night). The area arms the moment every zone closes, or gives up after 30 minutes (set in the options) and says what was still open. Turn the switch off to stop. Also the `protege_wx.arm_when_ready` action, which takes a PIN like arming does.
- **Automation triggers and conditions** in the automation editor (Home Assistant 2026.10+): Access granted (optionally only certain people, card or PIN), Access denied, Door forced or left open, Area failed to arm, and Duress, panic or medical alarm; and the condition Area is ready to arm.
- **Home Assistant Marketplace ready** (2026.11): manifest categories, the HACS action passing with no ignored checks, and these notes shown in **Settings** > **Updates**.

**Fixed and tidied**

- Renaming an entity in Home Assistant 2026.11 updates it in place instead of removing and re-adding it. The Alarmo sync follows a renamed alarm panel.
- In the hour the clocks go back, controller log lines were read as an hour old, so Activity added "(at ...)" to them and a few checks treated them as history. The repeated hour is now read correctly.

## 0.3.2

- The alarm card's recent activity skips restart states and repeats.
