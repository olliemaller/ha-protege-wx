"""Config and options flows for the ICT Protege WX integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)

try:  # Home Assistant 2025.8+: the entry reloads itself after options change.
    from homeassistant.config_entries import OptionsFlowWithReload as _BaseOptionsFlow
except ImportError:  # pragma: no cover - older Home Assistant
    _BaseOptionsFlow = OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_PROTOCOL,
    CONF_SERIAL,
    DEFAULT_INPUT_TYPE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    INPUT_TYPES,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    OPT_CODE_ARM_REQUIRED,
    OPT_INPUT_TYPES,
    OPT_NOTIFY_FAILED_ARM,
    OPT_OUTPUTS,
    OPT_PANEL_CODE,
    OPT_SCAN_INTERVAL,
    OPT_SHOW_ARMING,
    OPT_USERS,
    USER_CAN_ARM,
    USER_CAN_DISARM,
    USER_NAME,
)
from .users import UserCodes, make_user
from .wxapi import (
    PROTOCOL_AUTO,
    ProtegeAuthError,
    ProtegeClient,
    ProtegeConnectionError,
    ProtegeError,
    normalise_host,
)

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
    }
)
MIN_CODE_LENGTH = 4


async def validate_login(
    hass: HomeAssistant, host: str, username: str, password: str
) -> dict[str, Any]:
    """Log in once, read the serial number, log out. Returns entry data extras."""
    from . import create_session  # local import keeps the flow importable alone

    session = create_session(hass)
    client = ProtegeClient(session, host, username, password, protocol=PROTOCOL_AUTO)
    try:
        await client.login()
        try:
            health = await client.health_values()
        except ProtegeAuthError:
            raise
        except ProtegeError:
            health = {}
        # Prove the operator can at least read live status.
        await client.area_status()
        return {
            CONF_PROTOCOL: client.protocol,
            CONF_SERIAL: (health.get("SerialNumber") or "").strip() or None,
        }
    finally:
        await client.close()
        await session.close()


def _errors_for(err: Exception, placeholders: dict[str, str]) -> dict[str, str]:
    if isinstance(err, ProtegeAuthError):
        if err.lockout_seconds:
            placeholders["seconds"] = str(err.lockout_seconds)
            return {"base": "locked_out"}
        return {"base": "invalid_auth"}
    if isinstance(err, ProtegeConnectionError):
        return {"base": "cannot_connect"}
    _LOGGER.exception("Unexpected error talking to the controller")
    return {"base": "unknown"}


class ProtegeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Protege WX controller."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            host = normalise_host(user_input[CONF_HOST])
            self._async_abort_entries_match({CONF_HOST: host})
            try:
                extra = await validate_login(
                    self.hass, host, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except Exception as err:  # noqa: BLE001 - mapped to form errors
                errors = _errors_for(err, placeholders)
            else:
                if extra[CONF_SERIAL]:
                    await self.async_set_unique_id(extra[CONF_SERIAL])
                    self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=f"Protege WX ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_PROTOCOL: extra[CONF_PROTOCOL],
                    },
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"host": entry.data[CONF_HOST]}
        if user_input is not None:
            try:
                extra = await validate_login(
                    self.hass,
                    entry.data[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except Exception as err:  # noqa: BLE001
                errors = _errors_for(err, placeholders)
            else:
                if extra[CONF_SERIAL] and entry.unique_id and extra[CONF_SERIAL] != entry.unique_id:
                    return self.async_abort(reason="wrong_controller")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_PROTOCOL: extra[CONF_PROTOCOL],
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            host = normalise_host(user_input[CONF_HOST])
            try:
                extra = await validate_login(
                    self.hass, host, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except Exception as err:  # noqa: BLE001
                errors = _errors_for(err, placeholders)
            else:
                if extra[CONF_SERIAL] and entry.unique_id:
                    await self.async_set_unique_id(extra[CONF_SERIAL])
                    self._abort_if_unique_id_mismatch(reason="wrong_controller")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: host,
                        CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_PROTOCOL: extra[CONF_PROTOCOL],
                    },
                )
        suggested = {
            CONF_HOST: entry.data[CONF_HOST],
            CONF_USERNAME: entry.data[CONF_USERNAME],
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input or suggested),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ProtegeOptionsFlow()


def _input_key(info) -> str:
    """Field key shown as the label, since input names aren't translatable."""
    return f"{info.name} (input {info.id})"


class ProtegeOptionsFlow(_BaseOptionsFlow):
    """Settings, input types, and the users whose PINs arm and disarm."""

    def __init__(self) -> None:
        self._editing: str | None = None
        self._base: dict[str, Any] | None = None

    def _options(self) -> dict[str, Any]:
        return dict(self._base if self._base is not None else self.config_entry.options)

    def _users(self) -> list[dict[str, Any]]:
        return list(self._options().get(OPT_USERS, []))

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self._options(), **changes})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        options = dict(self.config_entry.options)
        # Convert a v0.1 single panel code into a hashed user (off the event loop).
        legacy = (options.pop(OPT_PANEL_CODE, "") or "").strip()
        if legacy and not options.get(OPT_USERS):
            options[OPT_USERS] = [
                await self.hass.async_add_executor_job(make_user, "Panel code", legacy)
            ]
        self._base = options
        return self.async_show_menu(step_id="init", menu_options=["settings", "inputs", "users"])

    # ── settings ───────────────────────────────────────────────────────────

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        site = self.config_entry.runtime_data.site
        options = self._options()
        if user_input is not None:
            return self._save(
                **{
                    OPT_SCAN_INTERVAL: int(user_input[OPT_SCAN_INTERVAL]),
                    OPT_SHOW_ARMING: bool(user_input.get(OPT_SHOW_ARMING, False)),
                    OPT_NOTIFY_FAILED_ARM: bool(user_input.get(OPT_NOTIFY_FAILED_ARM, True)),
                    OPT_CODE_ARM_REQUIRED: bool(user_input.get(OPT_CODE_ARM_REQUIRED, True)),
                    OPT_OUTPUTS: [str(rec_id) for rec_id in user_input.get(OPT_OUTPUTS, [])],
                }
            )
        schema = vol.Schema(
            {
                vol.Required(
                    OPT_SCAN_INTERVAL,
                    default=options.get(OPT_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    OPT_SHOW_ARMING, default=options.get(OPT_SHOW_ARMING, False)
                ): selector.BooleanSelector(),
                vol.Optional(
                    OPT_NOTIFY_FAILED_ARM, default=options.get(OPT_NOTIFY_FAILED_ARM, True)
                ): selector.BooleanSelector(),
                vol.Optional(
                    OPT_CODE_ARM_REQUIRED, default=options.get(OPT_CODE_ARM_REQUIRED, True)
                ): selector.BooleanSelector(),
                vol.Optional(
                    OPT_OUTPUTS, default=options.get(OPT_OUTPUTS, [])
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=str(rec_id), label=f"{name} ({rec_id})")
                            for rec_id, name in site.outputs.items()
                        ],
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    # ── input types ────────────────────────────────────────────────────────

    async def async_step_inputs(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        site = self.config_entry.runtime_data.site
        current: dict[str, str] = self._options().get(OPT_INPUT_TYPES, {})
        if not site.inputs:
            return self.async_abort(reason="no_inputs")
        if user_input is not None:
            types = {str(info.id): user_input[_input_key(info)] for info in site.inputs.values()}
            return self._save(**{OPT_INPUT_TYPES: types})
        type_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(INPUT_TYPES),
                translation_key="input_type",
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
        schema = vol.Schema(
            {
                vol.Required(
                    _input_key(info), default=current.get(str(info.id), DEFAULT_INPUT_TYPE)
                ): type_selector
                for info in site.inputs.values()
            }
        )
        return self.async_show_form(step_id="inputs", data_schema=schema)

    # ── users ──────────────────────────────────────────────────────────────

    async def async_step_users(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["add_user"]
        if self._users():
            menu += ["edit_user", "remove_user"]
        return self.async_show_menu(
            step_id="users",
            menu_options=menu,
            description_placeholders={
                "users": ", ".join(u[USER_NAME] for u in self._users()) or "-",
            },
        )

    async def _code_in_use(self, code: str, ignore: str | None = None) -> bool:
        others = [u for u in self._users() if u[USER_NAME] != ignore]
        checker = UserCodes({OPT_USERS: others})
        result = await self.hass.async_add_executor_job(checker.check, code, "disarm")
        return result.reason != "invalid_code" and others != []

    def _code_errors(self, code: str, confirm: str) -> dict[str, str]:
        if not code.isdigit():
            return {"code": "code_not_numeric"}
        if len(code) < MIN_CODE_LENGTH:
            return {"code": "code_too_short"}
        if code != confirm:
            return {"confirm_code": "code_mismatch"}
        return {}

    async def async_step_add_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[USER_NAME].strip()
            code = user_input["code"].strip()
            if not name:
                errors[USER_NAME] = "name_required"
            elif any(u[USER_NAME].lower() == name.lower() for u in self._users()):
                errors[USER_NAME] = "name_in_use"
            errors |= self._code_errors(code, user_input["confirm_code"].strip())
            if not errors and await self._code_in_use(code):
                errors["code"] = "code_in_use"
            if not errors:
                user = await self.hass.async_add_executor_job(
                    make_user, name, code, user_input[USER_CAN_ARM], user_input[USER_CAN_DISARM]
                )
                return self._save(**{OPT_USERS: [*self._users(), user]})
        schema = vol.Schema(
            {
                vol.Required(USER_NAME): str,
                vol.Required("code"): PASSWORD_SELECTOR,
                vol.Required("confirm_code"): PASSWORD_SELECTOR,
                vol.Required(USER_CAN_ARM, default=True): selector.BooleanSelector(),
                vol.Required(USER_CAN_DISARM, default=True): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="add_user",
            data_schema=self.add_suggested_values_to_schema(
                schema, {k: v for k, v in (user_input or {}).items() if "code" not in k}
            ),
            errors=errors,
        )

    async def async_step_edit_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        names = [u[USER_NAME] for u in self._users()]
        if user_input is not None:
            self._editing = user_input[USER_NAME]
            return await self.async_step_edit_user_details()
        return self.async_show_form(
            step_id="edit_user",
            data_schema=vol.Schema(
                {vol.Required(USER_NAME): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=names, mode=selector.SelectSelectorMode.LIST)
                )}
            ),
        )

    async def async_step_edit_user_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        users = self._users()
        current = next((u for u in users if u[USER_NAME] == self._editing), None)
        if current is None:
            return self.async_abort(reason="user_not_found")
        errors: dict[str, str] = {}
        if user_input is not None:
            code = (user_input.get("code") or "").strip()
            updated = {
                **current,
                USER_CAN_ARM: user_input[USER_CAN_ARM],
                USER_CAN_DISARM: user_input[USER_CAN_DISARM],
            }
            if code:
                errors = self._code_errors(code, (user_input.get("confirm_code") or "").strip())
                if not errors and await self._code_in_use(code, ignore=current[USER_NAME]):
                    errors["code"] = "code_in_use"
                if not errors:
                    fresh = await self.hass.async_add_executor_job(
                        make_user, current[USER_NAME], code
                    )
                    updated |= {k: fresh[k] for k in fresh if k not in (USER_CAN_ARM, USER_CAN_DISARM)}
            if not errors:
                return self._save(
                    **{OPT_USERS: [updated if u is current else u for u in users]}
                )
        schema = vol.Schema(
            {
                vol.Optional("code"): PASSWORD_SELECTOR,
                vol.Optional("confirm_code"): PASSWORD_SELECTOR,
                vol.Required(USER_CAN_ARM, default=current.get(USER_CAN_ARM, True)): selector.BooleanSelector(),
                vol.Required(
                    USER_CAN_DISARM, default=current.get(USER_CAN_DISARM, True)
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="edit_user_details",
            data_schema=schema,
            errors=errors,
            description_placeholders={"user": current[USER_NAME]},
        )

    async def async_step_remove_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        names = [u[USER_NAME] for u in self._users()]
        if user_input is not None:
            remove = set(user_input.get("remove", []))
            return self._save(**{OPT_USERS: [u for u in self._users() if u[USER_NAME] not in remove]})
        return self.async_show_form(
            step_id="remove_user",
            data_schema=vol.Schema(
                {vol.Required("remove"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=names, multiple=True, mode=selector.SelectSelectorMode.LIST
                    )
                )}
            ),
        )
