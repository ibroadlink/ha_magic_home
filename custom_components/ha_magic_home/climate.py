# -*- coding: utf-8 -*-
"""
The Ha Magic Home integration climate File.
"""
import logging
import math
from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.climate import (SWING_ON, SWING_OFF, SWING_BOTH,
                                              SWING_VERTICAL, SWING_HORIZONTAL,
                                              ATTR_TEMPERATURE, HVACMode,
                                              ClimateEntity,
                                              ClimateEntityFeature)
from .iot.device_class import (Endpoint, Capability)

from .iot.common import control_req, report_state

from .iot.const import (DOMAIN)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a config entry."""
    _LOGGER.debug('AcInit')
    device_list = hass.data[DOMAIN]['devices'][config_entry.entry_id]["AC"]
    new_entities = []

    for device in device_list:
        new_entities.append(Climate(device, config_entry.entry_id))
    if new_entities:
        async_add_entities(new_entities)


class Climate(ClimateEntity):

    def __init__(self, device: Endpoint, entry_id: str):
        self.device_id = device.endpointId
        self._cookie = device.cookie
        self._capability_map: dict[str, Capability] = {}
        self._mode_map: dict[str, str] = {}
        self._appliance_id = device.endpointId
        self._entry_id = entry_id
        self._attr_unique_id = device.endpointId
        self._attr_name = device.friendlyName
        self._is_on = device.isReachable
        self._attr_is_on = device.isReachable
        if device.isReachable == False:
            self._status = "off"
        else:
            self._status = "on"

        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_mode = HVACMode.OFF

        self._attr_hvac_modes = []

        self._attr_fan_modes = []

        self._attr_is_closed = True
        self._attr_supported_features = ClimateEntityFeature(0)
        self._attr_supported_features |= (ClimateEntityFeature.TURN_OFF)
        self._attr_supported_features |= (ClimateEntityFeature.TURN_ON)

        for capability in device.capabilities:
            for support in capability.actions.supported:
                self._capability_map[support.name] = capability
            if capability.properties.supported == None:
                continue
            for support in capability.properties.supported:
                _LOGGER.debug(support.name)
                if support.name == 'mode':
                    for val in support.enums:
                        if val == 'HEAT':
                            self._attr_hvac_modes.append(HVACMode.HEAT)
                            self._mode_map[HVACMode.HEAT] = val
                        if val == 'VENT':
                            self._attr_hvac_modes.append(HVACMode.FAN_ONLY)
                            self._mode_map[HVACMode.FAN_ONLY] = val

                        if val == 'AUTO':
                            self._attr_hvac_modes.append(HVACMode.AUTO)
                            self._mode_map[HVACMode.AUTO] = val

                        if val == 'COLD':
                            self._attr_hvac_modes.append(HVACMode.COOL)
                            self._mode_map[HVACMode.COOL] = val

                        if val == 'DEHUMI':
                            self._attr_hvac_modes.append(HVACMode.DRY)
                            self._mode_map[HVACMode.DRY] = val

                elif support.name == 'fixedTargetTemperature':
                    self._attr_supported_features |= (
                        ClimateEntityFeature.TARGET_TEMPERATURE)
                    self._attr_target_temperature = support.range['max']
                    self._attr_min_temp = support.range['min']
                    self._attr_max_temp = support.range['max']
                    self._attr_target_temperature_high = support.range['max']
                    self._attr_target_temperature_low = support.range['min']
                    self._attr_target_temperature_step = 1
                elif support.name == 'windSpeed':
                    self._attr_supported_features |= (
                        ClimateEntityFeature.FAN_MODE)
                    for val in support.enums:
                        self._attr_fan_modes.append(
                            val)  #设置风速的时候更新_attr_fan_mode
                        self._attr_fan_mode = val
                elif support.name == 'powerState':
                    self._attr_hvac_modes.append(HVACMode.OFF)

        _LOGGER.debug(self._capability_map)

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        _LOGGER.debug('async_set_hvac_mode')
        _LOGGER.debug(hvac_mode)

        if hvac_mode == 'off':
            await control_req(self, 'off', "OFF")
        else:
            await control_req(self, 'on', "ON")
            await control_req(self, 'mode', self._mode_map[hvac_mode])
            self._attr_hvac_mode = hvac_mode

        await self.handle_state()

    async def async_set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        _LOGGER.debug('async_set_fan_mode')
        _LOGGER.debug(fan_mode)

        await control_req(self, 'fan_mode', fan_mode)
        await self.handle_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        _LOGGER.debug('async_set_temperature')
        _LOGGER.debug(kwargs)
        await control_req(self, 'set_temperature', kwargs['temperature'])
        await self.handle_state()

    async def async_remove(self):
        """Clean up the entity when it is removed from Home Assistant."""
        print(f"Removing entity {self.entity_id}")
        await super().async_remove()

    @property
    def is_on(self):
        """Return if the light is on."""
        return self._attr_is_on

    @property
    def is_closed(self):
        return self._attr_is_closed


    async def handle_state(self):
        res, res_state = await report_state(self)

        if res_state != 0 or res.event.payload.status != 0:
            self._attr_hvac_mode = HVACMode.OFF
            return

        for property in res.context.properties:
            if property.name == 'powerState' and property.value.value == 'OFF':
                self._attr_hvac_mode = HVACMode.OFF
                return

        for property in res.context.properties:
            if property.name == 'mode':
                for key, val in self._mode_map.items():
                    if val == property.value.value:
                        self._attr_hvac_mode = key
            if property.name == 'fixedTargetTemperature':
                self._attr_current_temperature = property.value.value
                self._attr_target_temperature = property.value.value
            if property.name == 'windSpeed':
                self._attr_fan_mode = property.value.value
