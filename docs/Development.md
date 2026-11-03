# Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install pytest-homeassistant-custom-component ruff
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
- the tests on the oldest supported Home Assistant (2025.6, Python 3.13) and the latest (Python 3.14);
- the smoke test on the latest stable and beta.

## Releasing

1. Bump `version` in `custom_components/protege_wx/manifest.json` and add a `## x.y.z` section to `CHANGELOG.md`.
2. Publish a GitHub release tagged `vx.y.z`. Leave the notes empty to use the changelog section.
3. The release workflow checks the version and attaches `protege_wx.zip`.

## Credits

- Protocol work builds on [protege-wx-cli](https://github.com/mitchell-johnson/protege-wx-cli) by Mitchell Johnson (MIT), extended for web interface 2.3.x.
- Inspired by [caboose014/ICT-Protege-Home-Assistant](https://github.com/caboose014/ICT-Protege-Home-Assistant). If you *do* have the Automation & Integration licence, that integration uses it. No code is shared.

See [CONTRIBUTING](../CONTRIBUTING.md) before opening a pull request.
