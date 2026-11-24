# Installation

## Requirements

- An ICT Protege WX with its **web interface** turned on over **plain HTTP**. Port 7377 is the usual default.
- Home Assistant **2025.6** or newer. The integration's own icon shows from **2026.3**.
- A controller **operator** for Home Assistant (see [Setup](Setup.md)).

> [!NOTE]
> **HTTPS, or the Automation and Control licence?** Use [ICT Protege](https://github.com/caboose014/ICT-Protege-Home-Assistant) by caboose014 instead. This integration only speaks HTTP. Set up one integration per controller, not both.

Both web protocol versions are supported and **detected automatically**:

| Web interface | Protocol | Status |
|---|---|---|
| **2.3.x** (e.g. 2.3.628, WX firmware 4.00) | Requests sent as HTTP POST; the controller hands out a login cookie | Tested on a real controller |
| Older | Requests sent as HTTP GET; the browser side keeps the login, as in [protege-wx-cli](https://github.com/mitchell-johnson/protege-wx-cli) | Written for, but only tested against a simulated controller, not real hardware |

You don't need to pick one: the integration tries both. Tested on one real controller so far. Please [send a compatibility report](https://github.com/olliemaller/ha-protege-wx/issues/new/choose) with your web interface version and whether it worked.

## Supported models

- **ICT Protege WX** controllers (the all-in-one WX board) with the built-in web interface turned on over plain HTTP. Tested on web interface 2.3.628 with WX firmware 4.00.
- Not supported: **Protege GX** (a different system with its own server software), and WX controllers whose web interface only answers over HTTPS (firmware 4.00.1676 or later can be set that way). For those, see the note above.

## Marketplace (Home Assistant 2026.11 and later)

[![Open this repository in the Home Assistant Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=olliemaller&repository=ha-protege-wx&category=integration)

1. Select the button above. Or go to **Settings** > **Marketplace**, select **Add from link**, enter `olliemaller/ha-protege-wx` and select **Add**. Adding from a link needs GitHub connected; the Marketplace asks for it.
2. Open **ICT Protege WX** and select **Install**.
3. The setup opens straight away. No restart is needed for a first install.

Updates appear under **Settings** > **Updates** with the release notes. After an update, the repair under **Settings** > **System** > **Repairs** restarts Home Assistant for you. To try pre-releases, turn on the repository's **Pre-release** switch on its Marketplace device page.

## HACS (Home Assistant 2025.6 to 2026.10)

1. Select the button above, or in **HACS** open the ⋮ menu > **Custom repositories**, add `https://github.com/olliemaller/ha-protege-wx` and choose type **Integration**.
2. Download **ICT Protege WX**.
3. Restart Home Assistant.

Updating Home Assistant to 2026.11 moves this to the Marketplace automatically. It stays installed and keeps getting updates.

## Manual

1. Download `protege_wx.zip` from the [latest release](https://github.com/olliemaller/ha-protege-wx/releases/latest).
2. Unzip it into `config/custom_components/protege_wx/`.
3. Restart Home Assistant.

## Removing it

1. Go to **Settings** > **Devices & services** > **ICT Protege WX**, open the ⋮ menu on the controller and select **Delete**. The integration logs out of the controller as it goes.
2. If you installed it through the Marketplace or HACS, remove it there too, then restart Home Assistant.
3. Nothing changes on the controller. You can delete the Home Assistant operator in the web interface if you made one just for this.

Next: [Setup](Setup.md).
