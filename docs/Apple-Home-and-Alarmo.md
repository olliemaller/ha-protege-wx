# Apple Home and Alarmo

## Apple Home (HomeKit Bridge)

Add these to your HomeKit Bridge and they appear in the Home app:

- the **alarm panel**: Away, Home and Night map to HomeKit's Away, Stay and Night;
- the **locks**;
- the **zone sensors**;
- **Alarm fault**.

Diagnostic and configuration entities, including *Hold open* and *Arm when ready*, are left out of the bridge by default. "Turn on all switches" can't hold every door open or arm the house.

> [!TIP]
> If you set up PINs, Apple Home needs one too. Add it to the HomeKit Bridge's YAML `entity_config` for the alarm panel (`code: "1234"`); the bridge's UI options don't have this setting.

## Wall tablets and keypad cards

Add users and PINs in the [options](Setup.md#3-options). Any keypad-style alarm card then works: the [Protege WX alarm card](Alarm-card.md), the built-in **Alarm panel** card, or other custom cards. You need a valid PIN to disarm, and to arm unless you turn that off. The force-arm buttons can't take a PIN, so they refuse while arming needs one. The user's name shows as `changed_by`.

## Alarmo

Already using **[Alarmo](https://github.com/nielsfaber/alarmo)**? Turn on **Alarmo sync** in the options and pick the Alarmo alarm and the Protege area. Arming or disarming either one does the same to the other:

- the controller has the final say. If it refuses to arm because a zone is open, Alarmo is disarmed again, so the two never disagree about whether the house is protected;
- arming from a Protege keypad arms Alarmo straight away, skipping Alarmo's own exit delay;
- after a restart, Alarmo is set to match the controller, never the other way round;
- if Alarmo asks for a code from automations, save it in the sync options.

> [!IMPORTANT]
> Both ways, anyone who can arm or disarm Alarmo can do the same to the real alarm, with Alarmo's codes rather than the PINs set up here. Make sure Alarmo asks for a code to disarm, or choose **Protege to Alarmo only**.

For most homes, the Protege panel and PINs on their own are enough.
