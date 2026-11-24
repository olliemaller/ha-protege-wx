# Changelog

## 0.8.3

Released 2026-11-24.

**Before you update**

- Needs Home Assistant 2025.6 or later (was 2025.1), the oldest version the tests run on.
- Reloading, disabling or removing the integration now locks any door held open by a visitor unlock straight away, instead of leaving it to the end of the visitor time.

**New**

- **Optional PIN for unlocking doors.** Turn on "Require a PIN to unlock doors" in the options (off by default, so nothing changes unless you do). Unlocking then needs the PIN of a user allowed to disarm, and wrong PINs count towards the same lockout as the alarm. `protege_wx.unlock_door` and `protege_wx.visitor_unlock` take a `code`; a door's Hold open switch and Visitor unlock button refuse while it's on.
- A Repairs issue when a door can't be locked at the end of a visitor unlock after 3 tries. It clears once the door locks.

**Improved**

- One missed reading no longer makes everything unavailable: up to 2 failed polls in a row keep the last readings, and entities go unavailable on the 3rd.
- The All areas panel checks a PIN once, so a wrong PIN counts once instead of once per area.
- The wrong-PIN lockout is kept across a reload of the integration, and is forgotten only when the integration is removed.
- Actions are set up once with the integration, and say clearly when the target's controller isn't loaded.
- The connection to the controller uses Home Assistant's own connection pool, with its own cookie jar.
- A visitor unlock that couldn't be locked when the integration was removed is locked when the same controller is added again.
- The "Alarm didn't arm" notification is kept separate for each controller.
- Polling error messages are translatable.
- Removing the integration also clears its login guards and health tracking from memory.
- aioprotegewx 0.1.2.

**Docs**

- Fields, ranges and more examples for every action, and why `protege_wx.arm` says `stay` while `protege_wx.arm_when_ready` says `home`.
- Supported models, a warning that DHCP discovery matches any ICT device, debug logging for both loggers and the "Enable debug logging" button, a note about the plain HTTP web interface, and plainer words for PGMs and the login.
- Older web interfaces are described honestly: tested only against a simulated controller.

## 0.8.2

Released 2026-11-22.

**Fixed**

- On a controller set to month/day dates, event-log times from the 1st to the 12th of a month were read as day/month (4 March became 3 April). The weekday the controller prints now decides which it is (aioprotegewx 0.1.1). Controllers set to day/month, like the Australian default, were not affected.

## 0.8.1

Released 2026-11-20.

**Improved**

- Fully typed (mypy strict, checked in CI) and tested to at least 95% in every module, with CI failing below that. The new tests cover the voice answers, every options step (including editing a user's PIN), the Alarmo sync, arm when ready, triggers, visitor unlocks and the all-areas panel.
- Ready for Home Assistant's probatio schemas while still working on older versions.
- Nothing changes in how the integration behaves.

## 0.8.0

Released 2026-11-20.

**Changed**

- The controller client moved into its own library, [aioprotegewx](https://github.com/olliemaller/aioprotegewx) on PyPI, so other projects can use it. Home Assistant installs it for you; nothing changes in how the integration works.

**Fixed**

- When two names overlap (doors "Front" and "Front Door", say), an event for the longer one was matched to the shorter. It now matches the right one.

## 0.7.0

Released 2026-11-20.

**New**

- **Found automatically.** A controller that gets its address by DHCP shows up under **Discovered**, with its address filled in; you add the operator login. ICT devices are recognised by their MAC address (starting `00:1B:C2`).
- **Follows a new address.** Once Home Assistant knows a controller's MAC address, it updates the address by itself if the controller moves. A controller you added by hand learns its MAC the first time it's seen.

## 0.6.1

Released 2026-11-20.

**Improved**

- Setup errors (controller unreachable, login rejected) are translatable.
- Brand images trimmed to Home Assistant's rules, and a `quality_scale.yaml` self-assessment against every quality scale rule.
- Docs: removing the integration, and known limitations.

## 0.6.0

Released 2026-11-17.

**New**

- **PIN limits.** Each user's PIN can be turned off without deleting it, limited to certain days, to a time range (overnight works) or to a last day: for a cleaner, tradesperson or guest. Set them under **Users and PINs**. A PIN used outside its limits is refused and says why. New action `protege_wx.set_user_enabled` turns a PIN on or off from an automation.
- **Allow arm switches** per area (away, home, night). Turn a mode off and Home Assistant, the alarm card and voice assistants stop offering it for that area.
- **All areas** alarm panel when there's more than one area: arm or disarm everything at once, through each area's own checks.
- **Alarm history** calendar: armed periods with who armed them, alarms and failures to arm, kept across restarts.
- **Quieter polling.** After a minute with nothing happening, the controller is read every 2 s instead of every 1 s (*Update interval when quiet*). It switches back the moment a zone, door, delay or event changes, or after a command. That halves the load on the controller most of the day.
- Zone sensors have a `trips_today` attribute: how many times the zone opened today.
- **Notifications blueprint:** optional camera snapshot on alarm, entry delay, emergency and door forced notifications.
- **New blueprints:** *Auto arm* (arm away when everyone's left, and at bedtime when everyone's home, using Arm when ready) and *Door unlock schedule* (hold a door open while a schedule is on, optionally only while disarmed).

## 0.5.0

Released 2026-11-17.

**Fixed**

- **Alarms during a Home Assistant restart weren't announced.** The first read of the controller's log after a start was treated as history. An alarm, a duress/panic/medical alarm or a failure to arm logged while Home Assistant was restarting fired no automations or notifications. Those from the last 10 minutes are now announced on the first read, with `replayed: true` on the event so automations can tell. Everything else on that page stays history.
- **Busy spells could lose events.** Only the newest page of the log was read. If more happened between two reads than one page holds (after a network drop, or a crowd through a door), the earlier lines were never seen. When every line on the newest page is new, earlier pages are now read until the last known line turns up (up to 3 pages).

**New**

- **Rescan controller** button on the controller device (under Configuration). It reads the controller again, so doors, zones and outputs added or renamed on the controller appear without removing the integration.
- New black-and-white icon, logo and banner, with dark-mode versions of the icon and logo for Home Assistant's integration list.
- README badges now match the black-and-white look.

## 0.4.3

Released 2026-11-04.

- **Force arm buttons follow the PIN rule.** When arming needs a PIN, the Force arm away and Force arm night buttons now refuse (a button can't take a PIN) instead of arming without one. Use the `protege_wx.arm` action with `force: true` and a `code`. If you don't require a PIN to arm, nothing changes.
- The alarm card's help link in the card picker now opens the card's documentation.
- Documentation checked line by line against the code and corrected: event fields, which entities start disabled, option ranges, PIN rules, Arm when ready after a restart, the bypass PIN rule, voice with AI agents, and more.
- The setup form says `http://` is optional.

## 0.4.2

Released 2026-11-04.

- Setup now says clearly when an HTTPS address is entered: this integration uses the web interface over plain HTTP, and points HTTPS and licensed (Automation and Control) panels to [ICT Protege](https://github.com/caboose014/ICT-Protege-Home-Assistant) by caboose014.
- README: a "Which integration is right for you?" guide and a credit to caboose014's ICT Protege, which credits this project too.
- Documentation moved to [docs/](docs/README.md) (also published to the wiki); the README is now a short overview with the new alarm card in light and dark.
- Added a security policy, contributing guide, code of conduct, accessibility statement and pull request template.

## 0.4.1

Released 2026-11-03.

- The project now stands on its own: the alarm card, README, brand images and blueprint no longer carry any company branding.
- Area, door, input and output devices now show Integrated Control Technology as their manufacturer.
- **Alarm card redesign:** quieter and easier to read. It uses your Home Assistant theme's font and colours, shows the state with a tinted icon, puts one line underneath about what matters now (open zones, the exit delay, who set it off), keeps the arm modes on one row, and has a round, phone-style PIN pad. Buttons respond to the press and respect reduced motion.

## 0.4.0

Released 2026-11-01.

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

Released 2026-10-26.

- The alarm card's recent activity skips restart states and repeats.

## 0.3.1

Released 2026-10-26.

- The alarm card registers in Home Assistant's own element registry, so dashboards no longer say "Custom element doesn't exist".
- Area exit and entry delays are read from the controller's real field names.

## 0.3.0

Released 2026-10-26.

- Visitor unlock, and Forced open and Left open sensors for doors.
- Night mapped to instant or stay, Vacation, emergency alerts, what set the alarm off, a delay countdown, zone and person activity, and clock drift checks.
- Walk test switch and two-way Alarmo sync.
- Assist questions, setup permission checks and a release zip.
- The alarm card, an actionable notifications blueprint, stay-arm zones and late times in the logbook.
- Fixes from an independent review: visitor unlock ignores readings from before the unlock and keeps the re-lock if locking fails; Night and Vacation survive restarts; failed-to-arm events carry the entity and mode.

## 0.2.4

Released 2026-10-26.

- Logbook entries in plain English for area, door, access, trouble and system events.
- Repairs for an unreachable controller, low supply voltage and an unreadable event log.
- Connection and open zones sensors.
- Works on Home Assistant 2025.1 and later.
- README images use full links so HACS shows them.

## 0.2.3

Released 2026-10-25.

- Devices the integration creates are named, and the controller keeps ICT as its manufacturer.
- README fixes.

## 0.2.2

Released 2026-10-25.

- README tidied.

## 0.2.1

Released 2026-10-25.

- Health and doors are read on the first poll, and everything is read again straight after a command.
- Brand images, screenshots and a full README.
