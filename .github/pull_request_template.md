## What and why

<!-- What does this change, and what problem does it solve? Link any issue: "Fixes #123". -->

## Type

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Tidy-up or tests only

## Tested on

- Home Assistant version:
- Protege WX web interface and firmware (if tried on a real controller):

## Checklist

- [ ] `pytest` and `ruff check custom_components tests` pass
- [ ] New or changed behaviour has tests against the fake controller
- [ ] Unknown states still show as unavailable, never as disarmed, locked or closed
- [ ] No extra logins, sessions or polling, and no secrets in logs or diagnostics
- [ ] User-facing text is in `strings.json` and `translations/en.json`
- [ ] Docs in `docs/` and `CHANGELOG.md` are updated
- [ ] I've read [CONTRIBUTING](../CONTRIBUTING.md) and agree to the [code of conduct](../CODE_OF_CONDUCT.md)

<!-- Found a security problem? Don't open a pull request; see SECURITY.md. -->
