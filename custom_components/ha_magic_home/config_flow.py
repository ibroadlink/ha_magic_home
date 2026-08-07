# -*- coding: utf-8 -*-
"""
The Ha Magic Home integration config_flow File.
"""
import logging
import asyncio
import aiohttp
import voluptuous as vol

from .iot.const import (DOMAIN, INTEGRATION_LANGUAGES, CLOUD_SERVERS,
                        DEFAULT_CLOUD_SERVER, HA_REDIRECT_URL,
                        DEFAULT_INTEGRATION_LANGUAGE, CLOUD_SERVERS_DOMAIN,
                        CLOUD_SERVERS_PATH)
from .iot.iot_i18n import IoTI18n

from homeassistant import config_entries
from homeassistant.helpers.translation import async_get_translations

_LOGGER = logging.getLogger(__name__)


class HaMagicHomeCustomIntegrationConfigFlow(config_entries.ConfigFlow,
                                             domain=DOMAIN):

    _main_loop: asyncio.AbstractEventLoop

    def __init__(self):
        self._iot_i18n = IoTI18n
        self._main_loop = asyncio.get_running_loop()
        self._token = None
        self._cloud_server = None
        self._integration_language = None
        self._oauth_redirect_url = None
        self.auth_code = None
        self.token = None
        self.refresh_token = None
        self.expires_in = None
        self.family_name = None
        self.family_id = None

    async def async_step_user(self, user_input=None):
        """Step 1: Show security information and wait for user confirmation."""
        if user_input is not None:
            agree = user_input.get("confirm")
            if agree is not None and isinstance(agree, bool):
                if agree:
                    return await self.async_step_family_info()
                else:
                    return await self._sync_show_form("not_agreed")

        return await self._sync_show_form("")

    async def _sync_show_form(self, reason: str):
        errors = {"base": reason} if reason else None
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required('confirm', default=False):
                bool,
            }),
            errors=errors,
            last_step=False,
        )

    async def async_step_family_info(self, user_input=None):
        if user_input is not None:
            self._cloud_server = user_input.get('cloud_server',
                                                DEFAULT_CLOUD_SERVER)
            self._integration_language = user_input.get(
                'integration_language', DEFAULT_INTEGRATION_LANGUAGE)
            self._iot_i18n = IoTI18n(lang=self._integration_language,
                                     loop=self._main_loop)
            await self._iot_i18n.init_async()

            self._oauth_redirect_url = f"{user_input.get('oauth_redirect_url')}{'webhook_path'}"
            return await self.async_step_auth_code()

        default_language = self.hass.config.language
        if default_language not in INTEGRATION_LANGUAGES:
            default_language = DEFAULT_INTEGRATION_LANGUAGE

        return self.async_show_form(
            step_id='family_info',
            data_schema=vol.Schema({
                vol.Required('cloud_server', default=DEFAULT_CLOUD_SERVER):
                vol.In(CLOUD_SERVERS),
                vol.Required('integration_language', default=default_language):
                vol.In(INTEGRATION_LANGUAGES),
            }),
            last_step=False,
        )

    async def async_step_auth_code(self, user_input=None):
        """Step 2: User enters authorization code."""
        errors = {}

        if user_input is not None:
            if not user_input["auth_code"]:
                errors["auth_code"] = "empty_auth_code"
            else:
                self.auth_code = user_input["auth_code"]
                return await self.async_step_validate_code()

        # 显示输入授权码的表单
        return self.async_show_form(
            step_id="auth_code",
            data_schema=vol.Schema({
                vol.Required("auth_code"): str,
            }),
            errors=errors,
        )

    async def async_step_validate_code(self, user_input=None):
        """Step 3: Validate authorization code and retrieve token."""
        try:
            token = await self._validate_auth_code(self.auth_code)
            self.token = token
            return await self.async_step_save_token()
        except Exception as e:
            _LOGGER.error(e)
            error_message = str(e)
            return self.async_show_form(
                step_id="validate_code",
                data_schema=vol.Schema({
                    vol.Required("auth_code"): str,
                }),
                errors={"base": error_message},
            )

    async def async_step_save_token(self, user_input=None):
        """Step 4: Save token to Home Assistant configuration."""
        return self.async_create_entry(
            title=self.family_name,
            data={
                "access_token": self.token,
                "family_id": self.family_id,
                "cloud_server": self._cloud_server,
                "refresh_token": self.refresh_token,
                "expires_in": self.expires_in
            },
        )

    async def _validate_auth_code(self, auth_code):

        url = CLOUD_SERVERS_DOMAIN[
            self._cloud_server] + CLOUD_SERVERS_PATH['getToken']
        payload = {"auth_code": auth_code}
        url = url + "?grant_type=authorization_code"
        url = url + '&code=' + auth_code + '&client_id=' \
            + '&redirect_uri='+HA_REDIRECT_URL
        header = {}
        header["CLOUD_SERVERS_DOMAIN"] = self._cloud_server
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload,headers=header) as response:
                    if response.status != 200:
                        raise ValueError(
                            self._iot_i18n.translate(
                                key='error.invalid_http_status'))

                    response_data = await response.json()
                    _LOGGER.debug(
                        "Authorization succeeded; token expires in %s seconds",
                        response_data.get("expires_in"),
                    )

                    if response_data["expires_in"] == 0:
                        raise ValueError(
                            self._iot_i18n.translate(
                                key='error.server_validation_failed').format(
                                    status_code=response_data["status"]))

                    self.token = response_data["access_token"]
                    self.refresh_token = response_data["refresh_token"]
                    self.expires_in = response_data["expires_in"]

                    self.family_name = ""
                    self.family_id = ""

                    return response_data["access_token"]
            except aiohttp.ClientError as e:

                raise ValueError(
                    self._iot_i18n.translate(key='error.network_error').format(
                        error_message=str(e)))
