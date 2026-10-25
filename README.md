<p align="center">
  <img src="https://raw.githubusercontent.com/olliemaller/ha-protege-wx/main/images/banner.png" alt="Protege WX for Home Assistant" width="100%">
</p>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-185FA5?style=for-the-badge&logo=homeassistantcommunitystore&logoColor=white&labelColor=042C53" alt="HACS Custom"></a>
  <a href="https://github.com/olliemaller/ha-protege-wx/releases"><img src="https://img.shields.io/github/v/release/olliemaller/ha-protege-wx?style=for-the-badge&color=185FA5&labelColor=042C53" alt="Release"></a>
  <a href="https://github.com/olliemaller/ha-protege-wx/actions/workflows/validate.yml"><img src="https://img.shields.io/github/actions/workflow/status/olliemaller/ha-protege-wx/validate.yml?branch=main&style=for-the-badge&label=checks&labelColor=042C53" alt="Checks"></a>
  <img src="https://img.shields.io/badge/Home%20Assistant-2025.1%2B-185FA5?style=for-the-badge&logo=homeassistant&logoColor=white&labelColor=042C53" alt="Home Assistant 2025.1+">
  <a href="https://github.com/olliemaller/ha-protege-wx/blob/main/LICENSE"><img src="https://img.shields.io/github/license/olliemaller/ha-protege-wx?style=for-the-badge&color=185FA5&labelColor=042C53" alt="Licence"></a>
</p>

<p align="center">
  <b>Arm, disarm, unlock and watch your ICT Protege WX from Home Assistant and Apple Home.</b><br>
  Through the controller's own web interface, so <b>no Automation &amp; Integration licence is needed.</b>
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=olliemaller&repository=ha-protege-wx&category=integration"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open in HACS"></a>
  &nbsp;
  <a href="https://my.home-assistant.io/redirect/config_flow_start/?domain=protege_wx"><img src="https://my.home-assistant.io/badges/config_flow_start.svg" alt="Add integration"></a>
</p>

---

<p align="center">
  <img src="https://raw.githubusercontent.com/olliemaller/ha-protege-wx/main/images/dashboard.png" alt="Alarm, doors, zones and controller status on a Home Assistant dashboard" width="88%">
</p>

## Why this exists

ICT's official way to talk to other systems is the **Automation & Integration** service on port 21000. It needs a paid licence, and many WX controllers don't have one. Without it, existing integrations can't connect.

Every WX does have a **web interface**. This integration speaks the same encrypted protocol as those web pages, so if you can log in to your controller in a browser, Home Assistant can control it.

> [!IMPORTANT]
> **Unofficial.** Not affiliated with or endorsed by Integrated Control Technology. "ICT" and "Protege" are trademarks of their owner, used here only to describe compatibility.

> [!WARNING]
> **It controls a live security system.** Use a dedicated operator with only the permissions Home Assistant needs, and test arming, disarming and door control while you're on site.

## Highlights

| Feature | What it does |
|---|---|
| **Alarm panel** | Arm Away, Home (stay), Night (you choose what it does) and Holidays, and disarm. Correct modes in Apple Home, even during the exit delay. |
| **Alarm card** | A keypad card with the exit/entry countdown, open zones, what set the alarm off and recent activity. Ships with the integration. |
| **Ask Assist** | "Is the house armed?", "Can I arm?", "Who came in last?" |
| **Fast** | Updates about every second, driven by the controller's event log. |
| **Who did it** | Shows which keypad user, card, PIN or Home Assistant user armed, disarmed or opened a door. |
| **Doors** | Timed unlock, hold open, visitor unlock (re-locks itself), forced and left-open sensors, and who came in last. |
| **Emergencies** | Duress, panic and medical alarms raise a critical alert that stays until you mark it handled. |
| **Alarmo** | Optional two-way sync with an Alarmo alarm. |
| **Won't arm? Know why** | A failed arm names the zones that stopped it, and can send you a notification. |
| **PINs** | Named users with their own PINs and arm/disarm permissions, for wall tablets and keypad cards. |
| **Health** | Trouble inputs, a single "Alarm fault" sensor, supply voltage, a connection sensor, and Repairs alerts when something's wrong. |
| **Logbook** | Plain sentences in Activity: "Front Door: access granted to Jane (PIN)", "Alarm: failed to arm, Living is open". |
| **Local** | Talks only to your controller over your own network. No cloud, and no extra Python packages. |

## Features

<img src="https://raw.githubusercontent.com/olliemaller/ha-protege-wx/main/images/mobile.png" alt="Mobile dashboard" width="260" align="right">

### Areas
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
- **Open zones** sensor: how many zones are open right now, with their names. Handy for a "Can I arm?" tile or asking a voice assistant.
- **Delay ends** sensor: when the exit or entry delay runs out, so dashboards can count down. Delays are read from the controller, or set in the options.
- **Alarm cause** sensor: the zone that set the alarm off, kept until the area is disarmed.
- **Walk test** switch: zones chime as you test them instead of setting off the alarm.
- **Buttons:** Force arm away, Force arm night and Silence siren.
- **Events entity:** armed, arming started or cancelled, failed to arm, disarmed and alarm, each with who did it.

### Doors
- **Lock.** Unlocking releases the door for its programmed time.
- **Hold open** switch, which latches the door unlocked until switched off.
- **Events entity:** access granted or denied (with the user and whether a card or PIN was used), unlocked, locked, opened, closed, forced open and left open.
- **Visitor unlock**: a button and an action that hold the door unlocked for 15 minutes (or as long as you choose), then lock it. Locking it sooner cancels it, and it still locks after a restart.
- **Forced open** and **Left open** sensors, and a **door open/closed** sensor, when the door has a door-position input.
- **Last seen** sensor per person who badges in: when, at which door, and card or PIN. Created the first time each person is seen.

### Inputs (zones)
- **Motion, door, window, smoke, moisture** and other types, chosen per input. A tamper or short reads as *on*, so a damaged sensor never looks quiet.
- **Last triggered** sensor: when the zone last opened, kept across restarts.
- **Tamper** sensor (diagnostic).
- **Bypass** selector: not bypassed, until disarmed, or permanent.

### Controller
- **Trouble inputs** such as mains failure, low battery, siren tamper and module offline.
- **Alarm fault**: one sensor that turns on if anything needs attention.
- **Supply voltage**, **Last event** and memory use.
- **Connection** sensor (diagnostic): Connected, Reconnecting, Backing off or Login failed, with the last successful update, protocol, response time and recent logins.
- **Controller events** entity.

### Logbook
Activity shows what happened in plain English, linked to the right area or door:
- *Alarm* armed (home) by Home Assistant
- *Front Door* access granted to Jane Citizen (PIN)
- *Alarm* failed to arm by Jane Citizen: Living is open
- *Gate* unlocked by Front Door

Zone openings aren't repeated here, because each zone's own sensor already logs them. Lines read late, for example after a network outage, end with the time they really happened.

### Repairs
**Settings → Repairs** tells you when something needs attention. Each alert clears itself once the problem is gone:
- the controller has been **unreachable for 15 minutes**;
- the **supply voltage** has been under 12.0 V for 5 minutes (usually a mains failure with the battery running down);
- the operator **can't read the event log**, so "who did it" and failed-arm reasons won't work;
- the controller's **clock is more than 2 minutes out** (set it in the Protege web interface, or turn on its time server);
- a **duress, panic or medical alarm**: a critical alert, a persistent notification and a `protege_wx_emergency` event. This one stays until you mark it handled.

### Outputs
- Choose any outputs (PGMs) to add as switches, and pulse them for a set time with an action.

<br clear="right">

## Requirements

- An ICT Protege WX with its **web interface** turned on. Port 7377 is the usual default.
- Home Assistant **2025.1** or newer. The integration's own icon shows from **2026.3**.
- A controller **operator** for Home Assistant (see **Setup** below).

Both web protocol versions are supported and **detected automatically**:

| Web interface | Protocol | Status |
|---|---|---|
| **2.3.x** (e.g. 2.3.628, WX firmware 4.00) | HTTP POST, controller-issued session cookie | Tested |
| Older | HTTP GET, client session, as in [protege-wx-cli](https://github.com/mitchell-johnson/protege-wx-cli) | Supported |

Tested on one controller so far. Please [open an issue](https://github.com/olliemaller/ha-protege-wx/issues) with your web interface version and whether it worked.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=olliemaller&repository=ha-protege-wx&category=integration)

1. Click the button above, or in **HACS** open the ⋮ menu → **Custom repositories**, add `https://github.com/olliemaller/ha-protege-wx` and choose type **Integration**.
2. Download **ICT Protege WX**.
3. Restart Home Assistant.

### Manual

1. Download `protege_wx.zip` from the [latest release](https://github.com/olliemaller/ha-protege-wx/releases/latest).
2. Unzip it into `config/custom_components/protege_wx/`.
3. Restart Home Assistant.

## Setup

### 1. Set up the controller

In the Protege web interface, create an **operator** for Home Assistant, for example `homeassistant`.

| Setting | Recommendation |
|---|---|
| **Permissions** | View status and the event log. Control only the areas, doors and outputs you want in Home Assistant. |
| **Session timeout** | About **15 minutes**. The integration keeps one session open and logs out when it stops. If Home Assistant crashes, the controller frees the session after this time. |
| **Don't give it** | Programming or user-management rights. If it's allowed to read names and settings it uses them; if not, it still works. |

### 2. Add the integration

[![Add the integration to your Home Assistant.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=protege_wx)

Go to **Settings → Devices & services → Add integration → ICT Protege WX** and enter:

- **Host:** the web interface address and port, for example `192.168.1.10:7377`. Pasting a full `http://…` address works too.
- **Operator username and password.** The password is never sent to the controller; login is a challenge/response.

Setup checks what the operator can see. If something's hidden (the event log, record details, doors), it tells you what that costs, so you can fix the role and re-check, or carry on.

Areas, doors, inputs, trouble inputs and outputs are discovered with their names from the controller.

### 3. Options

**Settings → Devices & services → ICT Protege WX → Configure** has five sections:

- **Settings:**
  - update interval (default 1 s)
  - "Arming" display
  - notifications for failed arms
  - whether a PIN is needed to arm
  - outputs to add as switches
  - visitor unlock time (default 15 minutes)
- **Alarm areas:** per area, what Night arms as (instant, stay or off), and the exit and entry delays.
- **Input types:** motion, door, window, smoke and so on, per input.
- **Users and PINs:** add, edit or remove users and choose whether each can arm and disarm. Only a salted hash of each PIN is stored. These users are separate from the controller's own keypad users.
- **Alarmo sync:** see below.

## Apple Home (HomeKit Bridge)

Add these to your HomeKit Bridge and they appear in the Home app:

- the **alarm panel**: Away, Home and Night map to HomeKit's Away, Stay and Night;
- the **locks**;
- the **zone sensors**;
- **Alarm fault**.

Diagnostic and configuration entities, including *Hold open*, are left out of the bridge by default. "Turn on all switches" can't hold every door open.

> [!TIP]
> If you set up PINs, Apple Home needs one too. Add it to the HomeKit Bridge's YAML `entity_config` for the alarm panel (`code: "1234"`); the bridge's UI options don't have this setting.

## Wall tablets, keypads and Alarmo

Add users and PINs in the options. Any keypad-style alarm card then works: the built-in **Alarm panel** card, or custom cards. You need a valid PIN to disarm, and to arm unless you turn that off. The user's name shows as `changed_by`.

Already using **[Alarmo](https://github.com/nielsfaber/alarmo)**? Turn on **Alarmo sync** in the options and pick the Alarmo alarm and the Protege area. Arming or disarming either one does the same to the other:

- the controller has the final say. If it refuses to arm because a zone is open, Alarmo is disarmed again, so the two never disagree about whether the house is protected;
- arming from a Protege keypad arms Alarmo straight away, skipping Alarmo's own exit delay;
- if Alarmo asks for a code from automations, save it in the sync options.

For most homes, the Protege panel and PINs on their own are enough.

## Alarm card

<img src="https://raw.githubusercontent.com/olliemaller/ha-protege-wx/main/images/alarm-card.png" alt="Alarm card: disarmed with open zones, exit delay countdown, and an alarm" width="100%">

The integration adds a dashboard card. There's nothing to download or add to resources:

```yaml
type: custom:protege-alarm-card
entity: alarm_control_panel.alarm
# optional
name: House
show_keypad: true     # when a PIN is needed
show_activity: true   # recent arming, disarming and doors
activity_count: 5
```

It finds the area's open-zones, delay and alarm-cause sensors by itself, and follows your light or dark theme.

## Voice (Assist)

Ask Assist, in English:

| Ask | Answer |
|---|---|
| "Is the house armed?" | "The Alarm is armed home." |
| "Can I arm?" | "Not yet: Living and Kitchen are open, but you can arm it in home mode." |
| "Who came in last?" | "Jane, at 6:42 pm at the Front Door." |

## Actions

| Action | Target | What it does |
|---|---|---|
| `protege_wx.arm` | alarm panel | Arm in `away`, `stay` or `instant` mode, optionally with `force` and a `code` |
| `protege_wx.unlock_door` | lock | Timed unlock, or `hold_open: true` to latch |
| `protege_wx.visitor_unlock` | lock | Hold unlocked for `minutes` (default from the options), then lock |
| `protege_wx.bypass` | zone sensor | `none`, `temporary` (until disarmed) or `permanent` |
| `protege_wx.pulse_output` | output switch | On for `seconds`, timed by the controller |

```yaml
# Force-arm away at night, even if a window was left open
action: protege_wx.arm
target:
  entity_id: alarm_control_panel.alarm
data:
  mode: away
  force: true
```

## Events and automations

| Event | When |
|---|---|
| `protege_wx_event` | Every meaningful event-log line: `kind`, `subject`, `type`, `by`, `user`, `method` |
| `protege_wx_failed_to_arm` | An arm attempt fails. Includes `area` and the `zones` that stopped it |
| `protege_wx_emergency` | A duress, panic or medical alarm: `type`, `area`, `by`, `text` |

The area, door and controller **event entities** carry the same information for the automation editor.

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

### Notifications blueprint

[![Import the blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Folliemaller%2Fha-protege-wx%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fprotege_wx%2Fprotege_wx_notifications.yaml)

One automation that sends phone notifications, with buttons that act on them (needs the Companion app):

- the alarm going off, with **Disarm** (type your PIN in the notification) and **Silence**;
- duress, panic and medical alarms, as critical alerts;
- a failed arm with the zones that stopped it, with **Retry when closed** and **Force arm**;
- a **bedtime reminder** when everyone's home and the alarm is off, with **Arm home**;
- a door **left unlocked** for 10 minutes, with **Lock**;
- a door forced or left open;
- controller faults.

## How it protects your controller

A controller whose session table filled with abandoned sessions has been seen to stall and reboot. This integration is careful:

- **One session.** It logs in once, keeps that session, and logs out on reload and shutdown.
- **Gentle reconnects.** A dropped session is re-established once. If the controller refuses straight away, logins pause for 30 s, doubling up to 10 minutes, and never exceed 6 in 10 minutes.
- **No operator lockouts.** A wrong password stops all login attempts after at most two tries and asks you to sign in again.
- **Small, cheap polls.** Every second it reads area status, zone status and the newest event-log page. Doors, troubles and outputs are read when the log says they changed, and at least every 5 s. Health is read every minute.
- **Honest states.** Unknown or unreadable states show as unavailable, never as a reassuring *disarmed*, *locked* or *closed*. An arm is reported as successful only after the controller confirms it.

## Troubleshooting

| Problem | Fix |
|---|---|
| **"Invalid authentication"** | Log in to the web interface with the same operator to check the details. Check the operator isn't disabled or locked out. |
| **Can't connect** | Check you can open `http://<host>:<port>` in a browser on the same network as Home Assistant. |
| **Away won't arm, Home works** | A zone is open (for example someone moving in a room). Check *Ready to arm* or the error message, or use **Force arm away**. |
| **No "who did it"** | The operator needs permission to view the event log. Repairs will also tell you. |
| **Something seems stuck** | Check the **Connection** sensor on the controller device: it shows whether the link is up, reconnecting or backing off to protect the controller. |
| **Need help** | Download diagnostics from the integration's ⋮ menu. Passwords, PINs, serials and names in event lines are redacted. Attach it to an [issue](https://github.com/olliemaller/ha-protege-wx/issues). |

Debug logging:

```yaml
logger:
  logs:
    custom_components.protege_wx: debug
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install pytest-homeassistant-custom-component ruff
pytest
ruff check custom_components tests
```

Tests run against `tests/fake_controller.py`. It speaks both protocols with the real cryptography and reproduces a real controller's behaviour and event-log lines, including refusing to arm with a zone open. Pull requests are welcome.

## Built by Arcnode IT

<a href="https://arcnode.com.au"><img src="https://raw.githubusercontent.com/olliemaller/ha-protege-wx/main/images/built-by-arcnode.png" width="100%" alt="Built and maintained by Oliver Maller at Arcnode IT in Melbourne. Arcnode IT designs, installs and supports UniFi networks, Apple HomeKit and alarm systems across Melbourne and Victoria."></a>

Found a bug or want a feature? [Open an issue](https://github.com/olliemaller/ha-protege-wx/issues). Want a UniFi network, HomeKit setup or alarm system installed professionally? [Get in touch with Arcnode](https://arcnode.com.au).

## Credits

- Protocol work builds on [protege-wx-cli](https://github.com/mitchell-johnson/protege-wx-cli) by Mitchell Johnson (MIT), extended for web interface 2.3.x.
- Inspired by [caboose014/ICT-Protege-Home-Assistant](https://github.com/caboose014/ICT-Protege-Home-Assistant). If you *do* have the Automation & Integration licence, that integration uses it. No code is shared.

## Licence

[MIT](https://github.com/olliemaller/ha-protege-wx/blob/main/LICENSE). See also [NOTICE](https://github.com/olliemaller/ha-protege-wx/blob/main/NOTICE).
