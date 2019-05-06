"""
Support for Zway z-wave thermostats.

http://localhost:8083/ZWaveAPI/Run/devices[2].instances[0]

http://IP:8083/ZWaveAPI/Run/devices[4].instances[0].commandClasses[67].data[1].modeName (get mode)
http://IP:8083/ZWaveAPI/Run/devices[4].instances[0].commandClasses[67].data[1].val.value (get temperature)
http://IP:8083/ZWaveAPI/Run/devices[4].instances[0].commandClasses[67].data[1].setVal=17  (set temperature)
http://IP:8083/ZWaveAPI/Run/devices[4].instances[0].commandClasses[128].data.last.value  (get battery state)


OR through the ZWAY automations API

http://IP:8083/ZWaveAPI/Run/devices[4].instances[0].commandClasses[67].data[1].modeName (get mode)
http://IP:8083/ZAutomation/api/v1/devices/ZWayVDev_zway_4-0-67-1 (get temperature JSON data.metrics.level)
http://IP:8083/ZAutomation/api/v1/devices/ZWayVDev_zway_4-0-67-1/command/exact?level=17  (set temperature)
http://IP:8083/ZAutomation/api/v1/devices/ZWayVDev_zway_4-0-128 (get battery state JSON data.metrics.value)

configuration.yaml

climate:
  - platform: zway
    name: bedroom
    host: IP_ADDRESS
    port: 8083
    login: admin
    password: admin
    scan_interval: 10
    node: 4
"""

import logging
import json
import asyncio
import requests
import voluptuous as vol

from homeassistant.core import callback
from homeassistant.core import DOMAIN as HA_DOMAIN
from homeassistant.components.climate import (
    ClimateDevice, PLATFORM_SCHEMA)
from homeassistant.components.climate.const import (
    STATE_AUTO, STATE_HEAT, STATE_IDLE, STATE_AUTO, ATTR_OPERATION_MODE, SUPPORT_OPERATION_MODE,
    SUPPORT_TARGET_TEMPERATURE)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT, STATE_ON, STATE_OFF, STATE_UNKNOWN, ATTR_TEMPERATURE, CONF_NAME, ATTR_ENTITY_ID,
    CONF_HOST, PRECISION_HALVES)
from homeassistant.helpers import condition
from homeassistant.helpers.event import (
    async_track_state_change, async_track_time_interval)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.restore_state import RestoreEntity

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'Zway Thermostat'
DEFAULT_TIMEOUT = 10
DEFAULT_AWAY_TEMP = 15
DEFAULT_TARGET_TEMP = 21
DEFAULT_MIN_TEMP = 4
DEFAULT_MAX_TEMP = 40

CONF_NODE = 'node'
CONF_HOST = 'host'
CONF_LOGIN = 'login'
CONF_PASSWORD = 'password'
CONF_SENSOR = 'target_sensor'
CONF_MIN_TEMP = 'min_temp'
CONF_MAX_TEMP = 'max_temp'
CONF_TARGET_TEMP = 'target_temp'
CONF_AWAY_TEMP = 'away_temp'
CONF_INITIAL_OPERATION_MODE = 'initial_operation_mode'
SUPPORT_FLAGS = (SUPPORT_TARGET_TEMPERATURE |
                 SUPPORT_OPERATION_MODE)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_SENSOR): cv.entity_id,
    vol.Required(CONF_NODE): cv.positive_int,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_HOST, default='http://127.0.0.1:8083'): cv.string,
    vol.Optional(CONF_LOGIN): cv.string,
    vol.Optional(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_MAX_TEMP): vol.Coerce(float),
    vol.Optional(CONF_MIN_TEMP): vol.Coerce(float),
    vol.Optional(CONF_TARGET_TEMP): vol.Coerce(float),
    vol.Optional(CONF_AWAY_TEMP, default=DEFAULT_AWAY_TEMP): vol.Coerce(float),
    vol.Optional(CONF_INITIAL_OPERATION_MODE):
        vol.In([STATE_AUTO, STATE_OFF]),
})


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the generic thermostat platform."""
    name = config.get(CONF_NAME)
    host = config.get(CONF_HOST)
    node = config.get(CONF_NODE)
    login = config.get(CONF_LOGIN)
    password = config.get(CONF_PASSWORD)
    sensor_entity_id = config.get(CONF_SENSOR)
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    initial_operation_mode = config.get(CONF_INITIAL_OPERATION_MODE)

    async_add_entities([ZwayThermostat(
        hass, name, host, node, login, password, sensor_entity_id, 
        min_temp, max_temp, target_temp, initial_operation_mode)])


class ZwayThermostat(ClimateDevice, RestoreEntity):
    """Representation of a Zway Thermostat device."""

    def __init__(self, hass, name, host, node, login, password,             
                 sensor_entity_id, min_temp, max_temp, target_temp, 
                 initial_operation_mode):
        """Initialize the thermostat."""
        self.hass = hass
        self._name = name
        self._node = node
        self._host = host
        self._login = login
        self._password = password
        self._initial_operation_mode = initial_operation_mode
        self._temp_precision = 0.5
        self._current_operation = STATE_AUTO
        self._operation_list = [STATE_AUTO, STATE_HEAT, STATE_OFF]
        self._cur_temp = None
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temp = target_temp
        self._unit = hass.config.units.temperature_unit
        self._support_flags = SUPPORT_FLAGS

        async_track_state_change(
            hass, sensor_entity_id, self._async_sensor_changed)
        
        sensor_state = hass.states.get(sensor_entity_id)
        if sensor_state and sensor_state.state != STATE_UNKNOWN:
            self._async_update_temp(sensor_state)

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        # Check If we have an old state
        self._data = requests.get(self._host + '/ZAutomation/api/v1/devices/ZWayVDev_zway_' + str(self._node) + '-0-67-1', timeout=DEFAULT_TIMEOUT)
        self._json = self._data.json
        self._target_temp = float(self._json()["data"]["metrics"]["level"])
        old_state = await self.async_get_last_state()
        if old_state is not None:
            if (self._initial_operation_mode is None and
                    old_state.attributes[ATTR_OPERATION_MODE] is not None):
                self._current_operation = \
                    old_state.attributes[ATTR_OPERATION_MODE]

    @property
    def state(self):
        """Return the current state."""
        return self.current_operation

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def precision(self):
        """Return the precision of the system."""
        return super().precision

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    @property
    def current_operation(self):
        """Return current operation."""
        return self._current_operation

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def operation_list(self):
        """List of available operation modes."""
        return self._operation_list

    async def async_set_operation_mode(self, operation_mode):
        """Set operation mode."""
        if operation_mode == STATE_HEAT:
            self._current_operation = STATE_HEAT
        elif operation_mode == STATE_AUTO:
            self._current_operation = STATE_AUTO
        elif operation_mode == STATE_OFF:
            self._current_operation = STATE_OFF
        else:
            _LOGGER.error("Unrecognized operation mode: %s", operation_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.schedule_update_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            self._target_temp = kwargs.get(ATTR_TEMPERATURE)
            self._data = requests.get(self._host + '/ZAutomation/api/v1/devices/ZWayVDev_zway_' + str(self._node) + '-0-67-1/command/exact?level=' + str(self._target_temp), timeout=DEFAULT_TIMEOUT)
        await self.async_update_ha_state()

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self._min_temp:
            return self._min_temp

        # get default temp from super class
        return super().min_temp

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self._max_temp:
            return self._max_temp

        # Get default temp from super class
        return super().max_temp

    async def _async_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._async_update_temp(new_state)
        await self.async_update_ha_state()

    @callback
    def _async_switch_changed(self, entity_id, old_state, new_state):
        """Handle heater switch state changes."""
        if new_state is None:
            return
        self.async_schedule_update_ha_state()

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from sensor."""
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        try:
            self._cur_temp = self.hass.config.units.temperature(
                float(state.state), unit)
        except ValueError as ex:
            _LOGGER.error('Unable to update from sensor: %s', ex)

	
    def update(self):
           """Update the data from the thermostat."""
           self._data = requests.get(self._host + '/ZAutomation/api/v1/devices/ZWayVDev_zway_' + str(self._node) + '-0-67-1', timeout=DEFAULT_TIMEOUT)
           self._json = self._data.json
           self._target_temp = float(self._json()["data"]["metrics"]["level"])

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

