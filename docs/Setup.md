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

- **Host:** the web interface address and port, for example `192.168.1.10:7377`. `http://` is optional. HTTPS isn't supported; see [Installation](Installation.md).
- **Operator username and password.** The password is never sent to the controller; login is a challenge/response.

Setup checks what the operator can see. If something's hidden (the event log, record details, doors), it tells you what that costs, so you can fix the role and re-check, or carry on.

Areas, doors, inputs, trouble inputs and outputs are discovered with their names from the controller.

## 3. Options

**Settings > Devices & services > ICT Protege WX > Configure** has five sections:

- **Settings:**
  - update interval (1 to 30 s, default 1 s)
  - "Arming" display
  - notifications for failed arms (on by default)
  - whether a PIN is needed to arm (on by default; only applies once you add users)
  - outputs to add as switches
  - visitor unlock time (1 to 240 minutes, default 15)
  - how long [Arm when ready](Arm-when-ready.md) waits (1 to 240 minutes, default 30)
- **Alarm areas:** per area, what Night arms as (instant, stay or off), and the exit and entry delays (0 to 600 s). Only areas with inputs are listed, and only the Night modes the controller allows. Delays the controller reports are filled in for you; otherwise the defaults are 60 s exit and 30 s entry.
- **Input types:** motion, door, window, smoke and so on, per input.
- **Users and PINs:** add, edit or remove users and choose whether each can arm and disarm. PINs are at least 4 digits and must be different for each user. Only a salted hash of each PIN is stored. After 5 wrong PINs in 5 minutes, every PIN is blocked for 5 minutes. These users are separate from the controller's own keypad users.
- **Alarmo sync:** see [Apple Home and Alarmo](Apple-Home-and-Alarmo.md#alarmo).

## Changing the address or login

If the controller's address or the operator's password changes, open the integration's ⋮ menu and choose **Reconfigure**. If the password stops working, Home Assistant asks you to sign in again: look for **Re-authenticate** under **Settings > Devices & services**. Either way, your devices and entities are kept.

Next: add the [Alarm card](Alarm-card.md) to a dashboard.
