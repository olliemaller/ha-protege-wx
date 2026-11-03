# Setup

## 1. Set up the controller

In the Protege web interface, create an **operator** for Home Assistant, for example `homeassistant`.

| Setting | Recommendation |
|---|---|
| **Permissions** | View status and the event log. Control only the areas, doors and outputs you want in Home Assistant. |
| **Session timeout** | About **15 minutes**. The integration keeps one session open and logs out when it stops. If Home Assistant crashes, the controller frees the session after this time. |
| **Don't give it** | Programming or user-management rights. If it's allowed to read names and settings it uses them; if not, it still works. |

> [!WARNING]
> This controls a live security system. Give the operator only what Home Assistant needs, and test arming, disarming and door control while you're on site.

## 2. Add the integration

[![Add the integration to your Home Assistant.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=protege_wx)

Go to **Settings > Devices & services > Add integration > ICT Protege WX** and enter:

- **Host:** the web interface address and port, for example `192.168.1.10:7377`. Pasting a full `http://…` address works too.
- **Operator username and password.** The password is never sent to the controller; login is a challenge/response.

Setup checks what the operator can see. If something's hidden (the event log, record details, doors), it tells you what that costs, so you can fix the role and re-check, or carry on.

Areas, doors, inputs, trouble inputs and outputs are discovered with their names from the controller.

## 3. Options

**Settings > Devices & services > ICT Protege WX > Configure** has five sections:

- **Settings:**
  - update interval (default 1 s)
  - "Arming" display
  - notifications for failed arms
  - whether a PIN is needed to arm
  - outputs to add as switches
  - visitor unlock time (default 15 minutes)
  - how long [Arm when ready](Arm-when-ready.md) waits (default 30 minutes)
- **Alarm areas:** per area, what Night arms as (instant, stay or off), and the exit and entry delays.
- **Input types:** motion, door, window, smoke and so on, per input.
- **Users and PINs:** add, edit or remove users and choose whether each can arm and disarm. Only a salted hash of each PIN is stored. These users are separate from the controller's own keypad users.
- **Alarmo sync:** see [Apple Home and Alarmo](Apple-Home-and-Alarmo.md#alarmo).

Next: add the [Alarm card](Alarm-card.md) to a dashboard.
