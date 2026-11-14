# Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install pytest-homeassistant-custom-component ruff
# the voice tests also need Assist's requirements:
python -c "import json,pathlib,homeassistant as h; print('\\n'.join(json.loads((pathlib.Path(h.__file__).parent/'components/conversation/manifest.json').read_text())['requirements']))" > assist.txt
pip install -r assist.txt
pytest
ruff check custom_components tests
```

Tests run against `tests/fake_controller.py`. It speaks both protocols with the real cryptography and reproduces a real controller's behaviour and event-log lines, including refusing to arm with a zone open.

`tests/smoke.py` boots a real Home Assistant core in-process against the same fake controller, for checking a beta release where the pytest plugin isn't available yet:

```bash
pip install homeassistant==<version>
python tests/smoke.py
```

## Checks

Every push runs:

- **hassfest** and the **HACS** action (which the Marketplace uses);
- the tests on Home Assistant 2025.6 (Python 3.13, the oldest the test harness supports; the declared minimum is 2025.1) and the latest (Python 3.14);
- the smoke test on the latest stable and beta.

## Releasing

1. Bump `version` in `custom_components/protege_wx/manifest.json` (and `VERSION` in `frontend/protege-alarm-card.js` if the card changed), and add a `## x.y.z` section to `CHANGELOG.md`.
2. Push to `main`. The release workflow sees the new version, creates the `vx.y.z` tag and release with the changelog section as its notes, and attaches `protege_wx.zip`. The Marketplace and HACS then offer the update.

You can still publish a release by hand on GitHub. The workflow then checks the version and attaches the zip.

## Credits

- Protocol work builds on [protege-wx-cli](https://github.com/mitchell-johnson/protege-wx-cli) by Mitchell Johnson (MIT), extended for web interface 2.3.x.
- [ICT Protege](https://github.com/caboose014/ICT-Protege-Home-Assistant) by caboose014 inspired this integration, and credits it in return. It connects over HTTPS (firmware 4.00.1676 or later) or through the licensed Automation and Control service, so it's the one to use for those panels. The two projects share no code.

See [CONTRIBUTING](../CONTRIBUTING.md) before opening a pull request.
