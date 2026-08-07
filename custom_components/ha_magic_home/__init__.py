# -*- coding: utf-8 -*-
"""
The Ha Magic Home integration Init File.
"""
import logging
import aiohttp
from collections import defaultdict
from datetime import timedelta
from urllib.parse import quote

import uuid
import json

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_call_later
from .iot.const import (SUPPORTED_PLATFORMS, DOMAIN, CLOUD_SERVERS_DOMAIN, CLOUD_SERVERS_PATH)
from .iot.device_class import Discovery

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration from a config entry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    family_id = entry.data.get("family_id")
    cloud_server = entry.data.get("cloud_server")

    expires_in = entry.data.get("expires_in")

    async def dynamic_task():
        """Periodically refresh token and reschedule next refresh."""
        expires_in = await refresh_token_handle(hass, entry)

        async_call_later(hass, timedelta(seconds=expires_in), dynamic_task)

    expires_in = await refresh_token_handle(hass, entry)
    async_call_later(hass, timedelta(seconds=expires_in), dynamic_task)
    token = entry.data.get("access_token")

    _LOGGER.debug('Family info: %s, %s, %s', family_id, token, cloud_server)

    await async_get_devices(hass, token, cloud_server, entry)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload an integration."""
    await hass.config_entries.async_unload_platforms(
        entry, SUPPORTED_PLATFORMS)

    return True


async def async_get_devices(hass: HomeAssistant, token, cloud_server,
                            entry: ConfigEntry):
    """Discover and register devices from cloud server."""
    url = CLOUD_SERVERS_DOMAIN[cloud_server] + CLOUD_SERVERS_PATH["discover"]
    random_uuid = uuid.uuid4()
    header = {}
    header["CLOUD_SERVERS_DOMAIN"] = cloud_server
    
    body_dict = {
        "directive": {
            "header": {
                "namespace": "DNA.Discovery",
                "name": "Discover",
                "interfaceVersion": "2",
                "messageId": f"{random_uuid}"
            },
            "payload": {
                "scope": {
                    "type": "BearerToken",
                    "token": f"{token}"
                }
            }
        }
    }
    body = json.dumps(body_dict)

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, data=body,headers=header) as response:
                res = await response.text()
                discovery = Discovery.parse_raw(res)
                _LOGGER.debug(
                    "Device discovery completed with status %s",
                    discovery.event.payload.status,
                )
                device_category_map = defaultdict(list)
                for device in discovery.event.endpoints or []:
                    device_type = device.displayCategories[0]

                    tmp_dev_list = device_category_map[device_type]
                    tmp_dev_list.append(device)

                if 'devices' not in hass.data[DOMAIN]:
                    hass.data[DOMAIN]['devices'] = {}

                hass.data[DOMAIN]['devices'][
                    entry.entry_id] = device_category_map
                await hass.config_entries.async_forward_entry_setups(
                    entry, SUPPORTED_PLATFORMS)
        except aiohttp.ClientError as e:
            _LOGGER.error("Failed to discover devices: %s", str(e))
            raise


async def refresh_token_handle(hass: HomeAssistant, entry: ConfigEntry) -> int:
    cloud_server = entry.data.get("cloud_server")
    refresh_token = entry.data.get("refresh_token")

    url = CLOUD_SERVERS_DOMAIN[cloud_server] + CLOUD_SERVERS_PATH['getToken']
    # payload = {"auth_code": auth_code}
    url = url + "?grant_type=refresh_token"
    url = url + '&refresh_token=' + refresh_token 
    
    header = {}
    header["CLOUD_SERVERS_DOMAIN"] = cloud_server
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url=url, headers=header) as response:
                if response.status != 200:
                    _LOGGER.error("Invalid response status: %s", response.status)
                    raise ValueError(f"Invalid response status: {response.status}")

                response_data = await response.json()
                _LOGGER.debug(
                    "Cloud token refreshed; expires in %s seconds",
                    response_data.get("expires_in"),
                )

                if response_data["expires_in"] == 0:
                    _LOGGER.error("Server validation failed: %s", response)
                    raise ValueError("Server validation failed")
                hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data, "access_token":
                        response_data["access_token"],
                        "refresh_token": response_data["refresh_token"],
                        "expires_in": response_data["expires_in"]
                    },
                )
                return response_data["expires_in"] // 2
        except aiohttp.ClientError as e:
            _LOGGER.error("HTTP error during token refresh: %s", str(e))
            raise ValueError(f"HTTP error: {str(e)}")
