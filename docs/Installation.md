# Installation

## Requirements

- An ICT Protege WX with its **web interface** turned on over **plain HTTP**. Port 7377 is the usual default.
- Home Assistant **2025.1** or newer. The integration's own icon shows from **2026.3**.
- A controller **operator** for Home Assistant (see [Setup](Setup.md)).

> [!NOTE]
> **HTTPS, or the Automation and Control licence?** Use [ICT Protege](https://github.com/caboose014/ICT-Protege-Home-Assistant) by caboose014 instead. This integration only speaks HTTP. Set up one integration per controller, not both.

Both web protocol versions are supported and **detected automatically**:

| Web interface | Protocol | Status |
|---|---|---|
| **2.3.x** (e.g. 2.3.628, WX firmware 4.00) | HTTP POST, controller-issued session cookie | Tested |
| Older | HTTP GET, client session, as in [protege-wx-cli](https://github.com/mitchell-johnson/protege-wx-cli) | Supported |

Tested on one controller so far. Please [send a compatibility report](https://github.com/olliemaller/ha-protege-wx/issues/new/choose) with your web interface version and whether it worked.

## Marketplace (Home Assistant 2026.11 and later)

[![Open this repository in the Home Assistant Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=olliemaller&repository=ha-protege-wx&category=integration)

1. Select the button above. Or go to **Settings** > **Marketplace**, select **Add from link**, enter `olliemaller/ha-protege-wx` and select **Add**. Adding from a link needs GitHub connected; the Marketplace asks for it.
2. Open **ICT Protege WX** and select **Install**.
3. The setup opens straight away. No restart is needed for a first install.

Updates appear under **Settings** > **Updates** with the release notes. After an update, the repair under **Settings** > **System** > **Repairs** restarts Home Assistant for you. To try pre-releases, turn on the repository's **Pre-release** switch on its Marketplace device page.

## HACS (Home Assistant 2025.1 to 2026.10)

1. Select the button above, or in **HACS** open the ⋮ menu > **Custom repositories**, add `https://github.com/olliemaller/ha-protege-wx` and choose type **Integration**.
2. Download **ICT Protege WX**.
3. Restart Home Assistant.

Updating Home Assistant to 2026.11 moves this to the Marketplace automatically. It stays installed and keeps getting updates.

## Manual

1. Download `protege_wx.zip` from the [latest release](https://github.com/olliemaller/ha-protege-wx/releases/latest).
2. Unzip it into `config/custom_components/protege_wx/`.
3. Restart Home Assistant.

Next: [Setup](Setup.md).
