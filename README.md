# ICT Protege WX for Home Assistant

Control and monitor an **ICT Protege WX** alarm and access-control controller from Home Assistant, and through the HomeKit Bridge, from Apple Home.

It talks to the controller through **its built-in web interface**, the same encrypted protocol the WX web pages use. You **don't need the Automation & Integration licence** or the Automation service on port 21000. If you do have that licence, [caboose014/ICT-Protege-Home-Assistant](https://github.com/caboose014/ICT-Protege-Home-Assistant) uses it instead.

> **Unofficial.** This project isn't affiliated with or endorsed by Integrated Control Technology. "Protege" is a trademark of its owner and is used only to describe compatibility.
>
> **It controls a live security system.** Use a dedicated operator with only the permissions Home Assistant needs, and test arming, disarming and door control while you're on site.

## Features

### Areas
- **Alarm control panel** for arming and disarming:
  - Away, Home (stay) and Night (instant), with disarm.
  - During the exit delay it shows the mode being armed, so Apple Home displays it correctly. An option switches this to "Arming".
  - Pending during the entry delay; Triggered only while an alarm or siren is actually active, not just held in alarm memory.
- **Who changed it** (`changed_by`): the keypad user, card or Home Assistant user, read from the controller's event log.
- **Arm-failure feedback.** When the controller refuses to arm, Home Assistant:
  - shows an error naming the open zones;
  - fires a `protege_wx_failed_to_arm` event;
  - optionally shows a notification.
  This works whether the arm came from Home Assistant or a keypad.
- **Ready to arm** sensors, one for away and one for stay. Stay-type zones are ignored for stay.
- **Buttons:** force arm away, force arm night, and silence siren. Force arming bypasses open zones until disarmed.
- **Events entity** for automations: armed, arming started or cancelled, failed to arm, disarmed and alarm, each with who did it.

### Doors
- **Lock.** Unlocking releases the door for its programmed time.
- **Hold open switch** that latches the door unlocked until switched off.
- **Events entity:** access granted or denied (with the user and whether a card or PIN was used), unlocked, locked, opened, closed, forced open and left open.
- **Door open/closed sensor** if the door has a door-position input programmed.

### Inputs (zones)
- **Motion, door, window, smoke and other sensor types,** chosen per input. A tamper or short reads as "on", so a damaged sensor never looks quiet.
- **Tamper sensor** (diagnostic).
- **Bypass selector** (config): not bypassed, until disarmed, or permanent.

### Controller
- **Trouble sensors** such as mains failure, low battery and siren tamper.
- **Alarm fault:** one sensor that turns on if anything needs attention.
- **Supply voltage** and memory use.
- **Last event:** the most recent event-log line.
- **Controller events** entity.

### Users and PINs
- Add named users with a PIN, and choose whether each can arm and disarm. This lets keypad cards and wall tablets work properly, and records who armed or disarmed.
- Only a salted hash of each PIN is stored. These users are separate from the controller's own keypad users.

### Actions
| Action | What it does |
|---|---|
| `protege_wx.arm` | Arm in `away`, `stay` or `instant` mode, optionally with `force` |
| `protege_wx.unlock_door` | Timed unlock, or `hold_open` |
| `protege_wx.bypass` | Bypass an input: `none`, `temporary` or `permanent` |
| `protege_wx.pulse_output` | An output on for N seconds, timed by the controller |

### Bus events
- `protege_wx_event`: every meaningful event-log line.
- `protege_wx_failed_to_arm`: when an arm fails.

### Notifications blueprint
`blueprints/automation/protege_wx/protege_wx_notifications.yaml` sends push notifications for:
- the alarm going off;
- a failed arm, with the zones that stopped it;
- a door forced or left open;
- controller faults.

### HomeKit
- Diagnostic and config entities are left out of the HomeKit Bridge by default.
- Add the alarm panel, locks, motion sensors and "Alarm fault" to the bridge.
- If you set up PINs, give the bridge one in the alarm panel's entity configuration (`code:`).

## Compatibility

Both versions of the controller's web protocol are supported, and the integration **detects which one your controller uses**:
- **Web interface 2.3.x** (tested on 2.3.628.P028 with WX firmware 4.00): requests are HTTP POSTs, and the controller issues a session cookie.
- **Older web interfaces:** requests are HTTP GETs with a client-generated session, as documented by [protege-wx-cli](https://github.com/mitchell-johnson/protege-wx-cli).

So far it's been tested on one controller. Please open an issue with your web interface version and whether it worked.

## Installation

### HACS
1. In HACS, open the menu → **Custom repositories**. Add this repository's URL as type **Integration**.
2. Install **ICT Protege WX**, then restart Home Assistant.

### Manual
Copy `custom_components/protege_wx` into your Home Assistant `config/custom_components/` folder and restart.

## Setting up the controller

**Create a dedicated operator** in the Protege web interface, for example `homeassistant`:
- **Permissions:** viewing status and the event log, plus controlling only the areas, doors and outputs you want in Home Assistant.
- **Session timeout:** about 15 minutes. The integration keeps one session alive while it runs and logs out when it stops; if Home Assistant stops without logging out, the controller frees the session after this time. Operators default to about 1 hour.
- **Don't give it** programming or user-management rights. The integration reads names and settings if the operator is allowed to, and works without them if it isn't.

## Setting up Home Assistant

Go to **Settings → Devices & services → Add integration → ICT Protege WX** and enter:
- **Host:** the controller's web interface address and port, for example `192.168.1.10:7377`, without `http://`.
- **Operator username and password.** The password is never sent to the controller; the login is a challenge/response.

The integration's options have three sections:
- **Settings:**
  - update interval (default 1 s)
  - "Arming" display
  - failed-arm notifications
  - PIN required to arm
  - outputs to add as switches
- **Input types.**
- **Users and PINs.**

## How it works, and how it protects the controller

**What it reads, and how often:**
- **Every second:** area status, input status and the latest page of the event log, as three small encrypted requests over one session.
- **Door, trouble and output status:** when the event log says they changed, after any command, and at least every 5 seconds.
- **Controller health:** every minute.

**Protecting the session.** A controller whose session table filled with abandoned sessions has been seen to stall and reboot, so:
- the integration uses exactly one session and logs out on reload and shutdown;
- a dropped session is re-established once; if the new one is refused straight away, logins pause for 30 s, doubling up to 10 minutes;
- there are never more than 6 logins in 10 minutes.

**Protecting the operator from lockout:**
- A rejected password stops all login attempts and asks you to log in again. At most two failed attempts are made.
- Unknown or unreadable states show as unavailable, never as a reassuring "disarmed", "locked" or "closed".

## Development

```
python -m venv .venv && . .venv/bin/activate
pip install pytest-homeassistant-custom-component
pytest
```

The tests run against `tests/fake_controller.py`. It speaks both protocols with the real cryptography, and reproduces a real controller's behaviour and event-log lines, including refusing to arm with a zone open.

## Credits

The protocol work builds on [protege-wx-cli](https://github.com/mitchell-johnson/protege-wx-cli) by Mitchell Johnson (MIT), extended for web interface 2.3.x. The user experience is inspired by [caboose014/ICT-Protege-Home-Assistant](https://github.com/caboose014/ICT-Protege-Home-Assistant). No code is shared with that project.

## Licence

MIT. See [LICENSE](LICENSE).
