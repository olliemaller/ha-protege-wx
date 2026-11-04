# How it protects your controller

## Why the web interface

ICT's official way to talk to other systems is the **Automation and Control** service on port 21000. It needs a paid licence, and many WX controllers don't have one. Every WX does have a **web interface**. This integration speaks the same encrypted protocol as those web pages, so if you can log in to your controller in a browser, Home Assistant can control it.

If your controller has the licence, or only offers its web interface over HTTPS, [ICT Protege](https://github.com/caboose014/ICT-Protege-Home-Assistant) by caboose014 is the better fit.

## Being gentle

A controller whose session table filled with abandoned sessions has been seen to stall and reboot. This integration is careful:

- **One session.** It logs in once, keeps that session, and logs out on reload and shutdown.
- **Gentle reconnects.** A dropped session is re-established once. If the controller refuses straight away, logins pause for 30 s, doubling up to 10 minutes, and never exceed 6 in 10 minutes.
- **No operator lockouts.** A wrong password stops all login attempts after at most two tries and asks you to sign in again.
- **Small, cheap polls.** At the default 1 s interval, every second it reads area status, zone status and the newest event-log page. Doors, troubles and outputs are read when the log says they changed, and at least every 5 s. Health is read every minute.
- **Honest states.** Unknown or unreadable states show as unavailable, never as a reassuring *disarmed*, *locked* or *closed*. An arm is reported as successful only after the controller confirms it.
- **Local only.** It talks only to your controller over your own network. No cloud, and no extra Python packages.
