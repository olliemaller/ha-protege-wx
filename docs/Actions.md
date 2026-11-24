# Actions

| Action | Target | Fields | What it does |
|---|---|---|---|
| `protege_wx.arm` | alarm panel | `mode` (required): `away`, `stay` or `instant`. `force`: true or false (default false). `code`: a PIN | Arm in one of the controller's own modes, optionally forcing it (open zones are left out until disarmed). `force` can't be used with `stay` |
| `protege_wx.arm_when_ready` | alarm panel | `mode`: `away`, `home` or `night` (default `away`). `minutes`: 1 to 240 (default from the options, 30). `code`: a PIN | Arm as soon as every zone is closed, or give up after `minutes`. See [Arm when ready](Arm-when-ready.md) |
| `protege_wx.unlock_door` | lock | `hold_open`: true or false (default false). `code`: a PIN, needed only when unlocking needs one | Unlock for the door's programmed unlock time, after which the controller locks it again. `hold_open: true` latches it unlocked until something locks it |
| `protege_wx.visitor_unlock` | lock | `minutes`: 1 to 240 (default from the options, 15). `code`: as above | Hold unlocked for `minutes`, then Home Assistant locks it |
| `protege_wx.bypass` | zone sensor | `mode` (required): `none`, `temporary` (until disarmed) or `permanent`. `code`: a PIN | With PINs set up, bypassing a zone in an armed area needs a `code` from a user who can disarm |
| `protege_wx.pulse_output` | output switch | `seconds` (required): 1 to 65535 | On for `seconds`, timed by the controller |
| `protege_wx.set_user_enabled` | alarm panel | `user` (required): the user's name. `enabled` (required): true or false | Turn a user's PIN on or off without opening the options, for example a cleaner's PIN only on cleaning days |

### Why `stay` in one action and `home` in the other

The two arm actions take different words on purpose, and each accepts only its own:

- `protege_wx.arm` takes the **controller's** modes: `away`, `stay` (the controller's partial arm, leaving stay-type zones out) and `instant` (no entry delay).
- `protege_wx.arm_when_ready` takes **Home Assistant's** modes, the same as the alarm panel's buttons: `away`, `home` (arms the controller in `stay`) and `night` (arms whatever Night is set to for that area in the options: `instant` by default, or `stay`).

So `mode: home` is refused by `protege_wx.arm`, and `mode: stay` is refused by `protege_wx.arm_when_ready`.

The standard `alarm_control_panel.*` and `lock.*` actions work too.

## Examples

```yaml
# Force-arm away at night, even if a window was left open
action: protege_wx.arm
target:
  entity_id: alarm_control_panel.alarm
data:
  mode: away
  force: true
```

```yaml
# Let the cleaner in for an hour
action: protege_wx.visitor_unlock
target:
  entity_id: lock.front_door
data:
  minutes: 60
```

```yaml
# Leave the garage window out of tonight's arm
action: protege_wx.bypass
target:
  entity_id: binary_sensor.garage_window
data:
  mode: temporary
```

```yaml
# Open the gate: pulse its output for 2 seconds
action: protege_wx.pulse_output
target:
  entity_id: switch.gate
data:
  seconds: 2
```

```yaml
# Arm in stay mode as soon as everything is closed, waiting up to 10 minutes
action: protege_wx.arm_when_ready
target:
  entity_id: alarm_control_panel.alarm
data:
  mode: home
  minutes: 10
  code: "1234"
```

```yaml
# Hold the front door unlocked until someone locks it
action: protege_wx.unlock_door
target:
  entity_id: lock.front_door
data:
  hold_open: true
```

```yaml
# Turn the cleaner's PIN off
action: protege_wx.set_user_enabled
target:
  entity_id: alarm_control_panel.alarm
data:
  user: Cleaner
  enabled: false
```
