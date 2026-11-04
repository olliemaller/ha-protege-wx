# Troubleshooting

| Problem | Fix |
|---|---|
| **"Invalid authentication"** | Log in to the web interface with the same operator to check the details. Check the operator isn't disabled or locked out. |
| **"This integration talks to the web interface over plain HTTP"** | You entered an HTTPS address or port 443. Use the web interface's HTTP port (usually 7377). If your controller only offers HTTPS, use [ICT Protege](https://github.com/caboose014/ICT-Protege-Home-Assistant) instead. |
| **Can't connect** | Check you can open `http://<host>:<port>` in a browser on the same network as Home Assistant. |
| **Away won't arm, Home works** | A zone is open (for example someone moving in a room). Check *Ready to arm* or the error message, use [Arm when ready](Arm-when-ready.md), or **Force arm away**. |
| **No "who did it"** | The operator needs permission to view the event log. Repairs will also tell you. |
| **Arm when ready switch won't turn on** | Arming needs a PIN. Use the alarm card's button or the `protege_wx.arm_when_ready` action with a `code`. |
| **Alarm card shows "Configuration error"** | Update to 0.3.1 or later, restart Home Assistant, then refresh the browser or app (in the Companion app: **Settings > Reset frontend cache**). |
| **No triggers in the automation editor** | They need Home Assistant 2026.10 or later. On older versions, use the [event entities](Automations.md#event-entities). |
| **No "Last seen" sensor for someone** | It's created the first time that person uses a card or PIN at a door after the integration is running. Entries read while Home Assistant was restarting don't count. |
| **Something seems stuck** | Check the **Connection** sensor on the controller device: it shows whether the link is up, reconnecting or backing off to protect the controller. |

## Diagnostics and logs

Download diagnostics from the integration's ⋮ menu. Passwords, PINs, serials and names in event lines are redacted. Attach it to a [bug report](https://github.com/olliemaller/ha-protege-wx/issues/new/choose).

Debug logging:

```yaml
logger:
  logs:
    custom_components.protege_wx: debug
```

Found a security problem? Please don't open an issue; see the [security policy](../SECURITY.md).
