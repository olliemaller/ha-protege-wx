# Automations

Three ways to automate, from simplest to most flexible: the **triggers and conditions** in the automation editor, the **event entities**, and the **bus events**. The [notifications blueprint](#notifications-blueprint) covers the common alerts in one go.

## Triggers and conditions

On Home Assistant 2026.10 and later, the automation editor lists these under **Protege WX**. Pick doors, areas or the controller by device, area or entity.

| Trigger | Fires when | Options |
|---|---|---|
| **Access granted** | someone badges in at the door | only certain people; card or PIN |
| **Access denied** | a card or PIN is refused | |
| **Door forced or left open** | the door is forced or left open | which alerts |
| **Area failed to arm** | the area refuses to arm | |
| **Duress, panic or medical alarm** | the controller logs one | which types |

| Condition | True when |
|---|---|
| **Area is ready to arm** | every chosen area could arm now in Away, or in Home (which ignores the zones that only arm when away) |

```yaml
# Welcome home: turn the lights on when Jane badges in after dark
triggers:
  - trigger: protege_wx.access_granted
    target:
      entity_id: event.front_door_events
    options:
      people: [Jane Citizen]
conditions:
  - condition: sun
    after: sunset
actions:
  - action: light.turn_on
    target:
      area_id: hallway
```

The trigger variables include `user`, `by`, `method` (`card` or `pin`), `event_type`, `subject` (the door or area), `text` (the controller's own line), `entity_id`, `from_state` and `to_state`.

## Event entities

Each area, door and the controller has an **Events** entity. They carry the same information as the triggers and work on every supported version.

```yaml
# Tell me who's at the front door
triggers:
  - trigger: state
    entity_id: event.front_door_events
    not_from: [unavailable, unknown]
conditions:
  - condition: state
    entity_id: event.front_door_events
    attribute: event_type
    state: access_granted
actions:
  - action: notify.mobile_app_phone
    data:
      message: "{{ trigger.to_state.attributes.user }} came in the front door"
```

## Bus events

| Event | When |
|---|---|
| `protege_wx_event` | Every meaningful event-log line: `kind`, `subject`, `type`, `by`, `mode`, `method`, `text`, `time`, `replayed` and `entry_id`. `replayed` is `true` for an alarm, emergency or failure to arm that happened in the 10 minutes before Home Assistant started, announced on the first read so it isn't lost |
| `protege_wx_failed_to_arm` | An arm attempt fails. Includes `area` and the `zones` that stopped it |
| `protege_wx_emergency` | A duress, panic or medical alarm: `type`, `area`, `by`, `text`, `replayed` |
| `protege_wx_arm_when_ready` | An [Arm when ready](Arm-when-ready.md#results) wait finished |

## Notifications blueprint

[![Import the blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Folliemaller%2Fha-protege-wx%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fprotege_wx%2Fprotege_wx_notifications.yaml)

One automation that sends phone notifications, with buttons that act on them (needs the Companion app):

- the entry delay starting, with **Disarm**, and the alarm going off, with **Disarm** and **Silence** (type your PIN in the notification to disarm);
- duress, panic and medical alarms, as critical alerts;
- a failed arm with the zones that stopped it, with **Retry when closed** and **Force arm** (not offered after a failed Home arm);
- a **bedtime reminder** when everyone's home and the alarm is off, with **Arm home**;
- a door **left unlocked** for 10 minutes, with **Lock**;
- a door forced or left open;
- controller faults.

The notifications blueprint can also attach a **camera snapshot** to alarm, entry delay, emergency and door forced notifications (choose the camera under *Camera snapshot*).

## Auto arm blueprint

[![Import the blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Folliemaller%2Fha-protege-wx%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fprotege_wx%2Fprotege_wx_auto_arm.yaml)

Arms away a few minutes after everyone has left, and optionally at bedtime when everyone's home (Night or Home). It uses Arm when ready, so an open door delays arming instead of stopping it. It never disarms. Needs arming without a PIN.

## Door unlock schedule blueprint

[![Import the blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Folliemaller%2Fha-protege-wx%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fprotege_wx%2Fprotege_wx_door_schedule.yaml)

Keeps a door unlocked (its **Hold open** switch) while a Home Assistant schedule helper is on, optionally only while an area is disarmed, and locks it when the schedule ends.
