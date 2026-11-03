# Security policy

This integration controls a live alarm system and door locks, so security problems matter more than usual. Thank you for reporting them carefully.

## Reporting a vulnerability

**Please don't open a public issue, discussion or pull request.**

Report it privately through GitHub: go to the [Security tab](https://github.com/olliemaller/ha-protege-wx/security) and select **Report a vulnerability**. Only the maintainer can see the report.

Include as much of this as you can:

- what someone could do (for example disarm, unlock a door, read PINs or credentials, or knock the controller offline);
- how to reproduce it, and what access they'd need (local network, a Home Assistant user, a dashboard, an automation);
- the integration version, Home Assistant version and Protege WX web interface version;
- diagnostics or logs, with your own passwords, PINs and addresses removed.

## What happens next

- You'll get a reply within **7 days**.
- Once it's confirmed, a fix is aimed for within **30 days**, sooner for anything that lets someone disarm or unlock without permission.
- A fixed release goes out with a GitHub security advisory. You'll be credited unless you'd rather not be.

Please give a reasonable time for a fix to be released before telling anyone else.

## Supported versions

Only the **latest release** gets security fixes. Update through the Marketplace or HACS.

## In scope

- Anything that lets someone arm, disarm, bypass, unlock or pulse outputs without the permission or PIN the integration should require.
- PINs, operator credentials or session tokens being stored, logged or exposed (including in diagnostics).
- The alarm card or actions doing something a user didn't ask for.
- The integration making a controller unstable (for example by exhausting its sessions).

## Out of scope

- Weaknesses in the Protege WX controller, its firmware or its web interface. Report those to [Integrated Control Technology](https://ict.co).
- Home Assistant itself. See [Home Assistant's security policy](https://www.home-assistant.io/security/).
- Someone who already has administrator access to your Home Assistant.

## Keeping your own system safe

- Give the Home Assistant operator only the areas, doors and outputs it needs, and no programming rights. See [Setup](docs/Setup.md).
- Turn on PINs for arming and disarming if anyone else uses your dashboards.
- Keep the controller's web interface off the internet. Use a VPN to reach it remotely.
