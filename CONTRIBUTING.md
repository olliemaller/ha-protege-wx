# Contributing

Thanks for helping. Bug reports, controller compatibility reports, documentation fixes and code are all welcome.

By taking part you agree to the [code of conduct](CODE_OF_CONDUCT.md).

## Reporting

- **Bugs:** use the [bug report form](https://github.com/olliemaller/ha-protege-wx/issues/new/choose). Attach diagnostics from the integration's ⋮ menu; they're redacted.
- **Worked (or didn't) on your controller:** use the compatibility report form, with your web interface and firmware version. This is one of the most useful things you can do.
- **Security problems:** don't open an issue. See the [security policy](SECURITY.md).
- **Ideas:** open an issue describing what you're trying to do, before writing code, so we can agree on the approach.

## Code

### Set up

```bash
git clone https://github.com/olliemaller/ha-protege-wx
cd ha-protege-wx
python -m venv .venv && . .venv/bin/activate
pip install pytest-homeassistant-custom-component ruff
# the voice tests also need Assist's requirements:
python -c "import json,pathlib,homeassistant as h; print('\\n'.join(json.loads((pathlib.Path(h.__file__).parent/'components/conversation/manifest.json').read_text())['requirements']))" > assist.txt
pip install -r assist.txt
pytest
ruff check custom_components tests
```

More in [Development](docs/Development.md).

### Ground rules

This talks to people's real alarm systems, so a few rules are firm:

- **Never report something as safe when it isn't known.** Unknown or unreadable states are *unavailable*, never *disarmed*, *locked* or *closed*. An arm only succeeds once the controller confirms it.
- **Be gentle with the controller.** No extra logins, no extra sessions, and no new polling without a good reason. Read [How it protects your controller](docs/How-it-protects-your-controller.md) first.
- **Never log or store secrets.** Passwords, PINs and session keys stay out of logs and diagnostics.
- **No new Python requirements** unless there's no other way.
- **Test it.** Add tests against `tests/fake_controller.py` for every change in behaviour. If you can, try it on a real controller and say which version in the pull request.

### Style

- `ruff check custom_components tests` passes (the rules are in `pyproject.toml`, the same as the checks).
- Support every Home Assistant version from the minimum in `hacs.json` to the current beta. Feature-detect newer APIs rather than requiring them.
- User-facing text goes in `strings.json` and `translations/en.json`, in plain, short sentences.
- Documentation is written in Australian English (*colour*, *licence*, *organise*).

### Pull requests

1. Branch from `main`.
2. Keep it to one change, and explain what and why. The pull request template has a checklist.
3. Update the docs in `docs/` and add a line to `CHANGELOG.md` under an `Unreleased` heading.
4. The checks (hassfest, HACS, tests and the smoke test) must pass.

The maintainer handles version numbers and releases.

## Licence

Contributions are licensed under the [MIT licence](LICENSE), the same as the project.
