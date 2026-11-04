# Actions

| Action | Target | What it does |
|---|---|---|
| `protege_wx.arm` | alarm panel | Arm in `away`, `stay` or `instant` mode, optionally with `force` and a `code`. `force` can't be used with `stay` |
| `protege_wx.arm_when_ready` | alarm panel | Arm in `away`, `home` or `night` as soon as every zone is closed. Gives up after `minutes` (default from the options). Takes a `code` like arming does. See [Arm when ready](Arm-when-ready.md) |
| `protege_wx.unlock_door` | lock | Timed unlock, or `hold_open: true` to latch |
| `protege_wx.visitor_unlock` | lock | Hold unlocked for `minutes` (default from the options), then lock |
| `protege_wx.bypass` | zone sensor | `none`, `temporary` (until disarmed) or `permanent`. With PINs set up, bypassing a zone in an armed area needs a `code` from a user who can disarm |
| `protege_wx.pulse_output` | output switch | On for `seconds`, timed by the controller |

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
