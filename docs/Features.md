# Features

Each area, door and chosen output is its own device; inputs belong to the controller.

## Areas

- **Alarm control panel** with Away, Home (stay), Night, Holidays and Disarm.
  - **Night** arms instantly (no entry delay) by default. Per area you can make it a stay arm instead, or turn it off.
  - **Holidays** arms away and shows as *Armed vacation*, for automations that treat a trip differently.
  - During the exit delay it shows the mode being armed, so Apple Home shows Home and Away correctly. An option switches this to "Arming".
  - *Pending* during the entry delay. *Triggered* only while an alarm or siren is actually active, not just held in alarm memory.
- **`changed_by`**: the keypad user, card or Home Assistant user, read from the controller's event log.
- **Arm-failure feedback.** When the controller refuses to arm, from Home Assistant or a keypad, you get:
  - an error naming the open zones;
  - a `protege_wx_failed_to_arm` event;
  - optionally, a notification.
- **Ready to arm** sensors for away and for stay. Stay-type zones are ignored for stay. The open zones are listed as an attribute.
- **Open zones** sensor: how many zones are open right now, with their names.
- **Delay ends** sensor: when the exit or entry delay runs out, so dashboards can count down. Delays are read from the controller, or set in the options.
- **Alarm cause** sensor: the zone that set the alarm off, kept until the area is disarmed.
- **Arm when ready** switch and mode select. See [Arm when ready](Arm-when-ready.md).
- **Walk test** switch: zones chime as you test them instead of setting off the alarm.
- **Buttons:** Force arm away, Force arm night and Silence siren.
- **Events entity:** armed, arming started or cancelled, failed to arm, disarmed and alarm, each with who did it.

## Doors

- **Lock.** Unlocking releases the door for its programmed time.
- **Hold open** switch, which latches the door unlocked until switched off.
- **Events entity:** access granted or denied (with the user and whether a card or PIN was used), unlocked, locked, opened, closed, forced open and left open.
- **Visitor unlock**: a button and an action that hold the door unlocked for 15 minutes (or as long as you choose), then lock it. Locking it sooner cancels it, and it still locks after a restart.
- **Forced open**, **Left open** and **Position** (open/closed) sensors, when the door has a door-position input.
- **Last seen** sensor per person who badges in: when, at which door, and card or PIN. Created the first time each person is seen.

## Inputs (zones)

- **Motion, door, window, smoke, moisture** and other types, chosen per input. A tamper or short reads as *on*, so a damaged sensor never looks quiet.
- **Last triggered** sensor: when the zone last opened, kept across restarts.
- **Tamper** sensor (diagnostic).
- **Bypass** selector: not bypassed, until disarmed, or permanent.

## Controller

- **Trouble inputs** such as mains failure, low battery, siren tamper and module offline.
- **Alarm fault**: one sensor that turns on if anything needs attention.
- **Supply voltage**, **Last event** and memory use.
- **Connection** sensor (diagnostic): Connected, Reconnecting, Backing off or Login failed, with the last successful update, protocol, response time and recent logins.
- **Events** entity for the controller.

## Outputs

Choose any outputs (PGMs) in the options. Each becomes its own device with a switch, and can be pulsed for a set time with [`protege_wx.pulse_output`](Actions.md).

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
