# Arm when ready

Each area has an **Arm when ready** switch and an **Arm when ready mode** select (Away, Home or Night).

- Turn the switch on and the area arms straight away if every zone is closed, or the moment the last one closes.
- It turns itself off when the area arms, whoever arms it.
- It gives up after the time limit in the options (30 minutes unless changed) and says which zones were still open.
- Turn it off to stop waiting. Reloading the integration also stops it (and says so), and so does restarting Home Assistant (without an event), so the house never arms long after someone expected.
- It stops if the area goes into alarm while waiting.
- It also waits while the panel itself isn't ready (for example a bypass error, or users still inside).
- When arming needs a PIN, the switch won't turn on by itself: use the [alarm card](Alarm-card.md)'s **Arm when ready** button (it asks for the PIN) or the action below with a `code`.
- The switch is a configuration entity, so voice assistants don't get it by default and turning on a whole area or device never arms the alarm.

## Action

```yaml
# Arm away when the last window is shut, as long as that's within 10 minutes
action: protege_wx.arm_when_ready
target:
  entity_id: alarm_control_panel.alarm
data:
  mode: away      # away, home or night
  minutes: 10     # 1 to 240; default from the options
  # code: "1234"  # when arming needs a PIN
```

## Results

Every result fires a `protege_wx_arm_when_ready` event (with `area`, `entity_id`, `mode`, `result`, `armed_elsewhere`, `open_zones` and `error`) and writes a line in Activity.

| `result` | Meaning |
|---|---|
| `armed` | The area armed. `armed_elsewhere` is `true` if someone armed it another way first. |
| `timed_out` | The time ran out. `open_zones` lists what was still open. |
| `cancelled` | Turned off (`error` is empty), the area went into alarm, or the integration was reloaded (`error` says so). |
| `failed` | The controller refused for a reason waiting won't fix, or a zone kept reopening three times in a row. `error` has the reason. |

```yaml
# Tell me if the house didn't arm
triggers:
  - trigger: event
    event_type: protege_wx_arm_when_ready
    event_data:
      result: timed_out
actions:
  - action: notify.mobile_app_phone
    data:
      message: "Didn't arm: {{ trigger.event.data.open_zones | join(', ') }} still open"
```
