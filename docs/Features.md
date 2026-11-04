# Features

Each area, door, input and chosen output is its own device under the controller. Trouble inputs and the *Last seen* sensors belong to the controller itself.

Some entities start disabled, so they don't clutter your dashboards: everything for an area with no inputs (such as a "System" area), inputs that belong to no area, *Forced open* and *Left open* on doors without a door-position input, and *Memory used*. Turn them on under **Settings > Devices & services > Entities** if you want them.

## Areas

- **Alarm control panel** with Away, Home (stay), Night, Holidays and Disarm.
  - **Night** arms instantly (no entry delay) by default. Per area you can make it a stay arm instead, or turn it off.
  - **Holidays** arms away and shows as *Armed vacation*, for automations that treat a trip differently.
  - During the exit delay it shows the mode being armed, so Apple Home shows Home and Away correctly. An option switches this to "Arming".
  - *Pending* during the entry delay. *Triggered* only while an alarm or siren is actually active, not just held in alarm memory.
- **`changed_by`**: the keypad user, card or Home Assistant user, read from the controller's event log.
- **Arm-failure feedback.** When the controller refuses to arm, you get:
  - an error naming the open zones (when the arm came from Home Assistant);
  - a `protege_wx_failed_to_arm` event, from Home Assistant or a keypad;
  - a notification (on by default; turn it off in the options).
- **Ready to arm** sensors for away and for stay. Stay-type zones are ignored for stay. The open zones are listed as an attribute.
- **Open zones** sensor: how many zones are open right now, with their names.
- **Delay ends** sensor: when the exit or entry delay runs out, so dashboards can count down. Delays are read from the controller, or set in the options.
- **Alarm cause** sensor: the zone that set the alarm off, kept until the area is disarmed.
- **Arm when ready** switch and mode select. See [Arm when ready](Arm-when-ready.md).
- **Walk test** switch: zones chime as you test them instead of setting off the alarm.
- **Buttons:** Force arm away, Force arm night (when Night arms instantly) and Silence siren. When arming needs a PIN, the force-arm buttons refuse; use the [`protege_wx.arm`](Actions.md) action with `force: true` and a `code` instead.
- **Events entity:** armed, arming started or cancelled, failed to arm, disarmed and alarm, each with who did it.

## Doors

- **Lock.** Unlocking releases the door for its programmed time.
- **Hold open** switch, which latches the door unlocked until switched off.
- **Events entity:** access granted or denied (with the user and whether a card or PIN was used), unlocked, locked, opened, closed, forced open and left open.
- **Visitor unlock**: a button and an action that hold the door unlocked for 15 minutes (or as long as you choose), then lock it. Locking it sooner cancels it, and it still locks after a restart.
- **Position** (open/closed) sensor, when the door has a door-position input, and **Forced open** and **Left open** sensors (disabled by default on doors without one).
- **Last seen** sensor per person who badges in: when, at which door, and card or PIN. Created the first time each person is seen.

## Inputs (zones)

- **Motion, door, window, smoke, moisture** and other types, chosen per input. A tamper or short reads as *on*, so a damaged sensor never looks quiet.
- **Last triggered** sensor: when the zone last opened, kept across restarts.
- **Tamper** sensor (diagnostic).
- **Bypass** selector: not bypassed, until disarmed, or permanent. With PINs set up, it only works while the zone's area is disarmed; use the [`protege_wx.bypass`](Actions.md) action with a `code` for an armed area.

## Controller

- **Trouble inputs** such as mains failure, low battery, siren tamper and module offline.
- **Alarm fault**: one sensor that turns on if anything needs attention.
- **Supply voltage**, **Last event** and **Memory used** (diagnostic, disabled by default).
- **Connection** sensor (diagnostic): Connected, Reconnecting, Backing off or Login failed, with the last successful update, protocol, response time and recent logins.
- **Events** entity for the controller.

## Outputs

Choose any outputs (PGMs) in the options. Each becomes its own device with a switch, and can be pulsed for a set time with [`protege_wx.pulse_output`](Actions.md).

## Useful attributes

For templates and automations:

| Entity | Attributes |
|---|---|
| Alarm panel | `changed_by`, `controller_state`, `flags`, `alarms_in_memory`, `open_zones` |
| Ready to arm, Open zones | `zones` / `open_zones`: the names of the open zones |
| Delay ends | `phase` (exit or entry), `exit_delay`, `entry_delay` |
| Lock | `held_open`, `visitor_until` |
| Arm when ready switch | `mode`, `until`, `open_zones` |
| Events entities | `event_type`, `user`, `by`, `method`, `subject`, `text` |

## Logbook

Activity shows what happened in plain English, linked to the right area or door:

- *Alarm* armed (home) by Home Assistant
- *Front Door* access granted to Jane Citizen (PIN)
- *Alarm* failed to arm by Jane Citizen: Living is open
- *Gate* unlocked by Front Door

Zone openings aren't repeated here, because each zone's own sensor already logs them. Lines read late, for example after a network outage, end with the time they really happened.

## Repairs

**Settings > Repairs** tells you when something needs attention. Each alert clears itself once the problem is gone:

- the controller has been **unreachable for 15 minutes**;
- the **supply voltage** has been under 12.0 V for 5 minutes (usually a mains failure with the battery running down);
- the operator **can't read the event log**, so "who did it" and failed-arm reasons won't work;
- the controller's **clock is more than 2 minutes out** (set it in the Protege web interface, or turn on its time server);
- a **duress, panic or medical alarm**: a critical alert, a persistent notification and a `protege_wx_emergency` event. This one stays until you mark it handled.
