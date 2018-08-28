"""
Support for Zway z-wave thermostats.
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
import voluptuous as vol

from homeassistant.components.climate import (ClimateDevice, PLATFORM_SCHEMA, SUPPORT_TARGET_TEMPERATURE)
from homeassistant.const import (CONF_NAME, CONF_HOST, TEMP_CELSIUS, ATTR_UNIT_OF_MEASUREMENT, ATTR_TEMPERATURE,  CONF_TIMEOUT, CONF_CUSTOMIZE)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_track_state_change
from homeassistant.core import callback
from homeassistant.helpers.restore_state import async_get_last_state

import requests

SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE | SUPPORT_OPERATION_MODE

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
CONF_AWAY_TEMP = 'away_temp'
CONF_TARGET_TEMP = 'target_temp'
CONF_TEMP_SENSOR = 'temp_sensor'
CONF_MIN_TEMP = 'min_temp'
CONF_MAX_TEMP = 'max_temp'
ATTR_MODE = 'mode'
STATE_OFF = 'off'
STATE_HEAT = 'heat'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_HOST, default='http://127.0.0.1:8083'): cv.string,
    vol.Required(CONF_NODE): cv.positive_int,
    vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): cv.positive_int,
    vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): cv.positive_int,
    vol.Optional(CONF_TARGET_TEMP, default=DEFAULT_TARGET_TEMP): cv.positive_int,
    vol.Optional(CONF_TEMP_SENSOR): cv.entity_id,
    vol.Optional(CONF_AWAY_TEMP, default=DEFAULT_AWAY_TEMP): cv.positive_int,
})

def setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Setup the Zway thermostat."""
    name = config.get(CONF_NAME)
    host = config.get(CONF_HOST)
    node = config.get(CONF_NODE)
    login = config.get(CONF_LOGIN)
    password = config.get(CONF_PASSWORD)
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    temp_sensor_entity_id = config.get(CONF_TEMP_SENSOR)

    async_add_devices([
        ZwayClimate(hass, name, host, node, login, password, min_temp, max_temp, target_temp, temp_sensor_entity_id)
    ])


class ZwayClimate(ClimateDevice):
    """Representation of a Zwave thermostat."""

    def __init__(self, hass, name, host, node, login, password, min_temp, max_temp, target_temp, temp_sensor_entity_id):
        """Initialize the thermostat."""
        self.hass = hass
        self._name = name
        self._node = node
        self._host = host
        self._login = login
        self._password = password
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temperature = target_temp
        self._target_temperature_step = 0.5
        self._current_operation = 'off'
        self._unit_of_measurement = hass.config.units.temperature_unit
        self._current_temperature = None
        self._temp_sensor_entity_id = temp_sensor_entity_id
         
        if temp_sensor_entity_id:
            async_track_state_change(
                hass, temp_sensor_entity_id, self._async_temp_sensor_changed)
                
            sensor_state = hass.states.get(temp_sensor_entity_id)    
                
            if sensor_state:
                self._async_update_current_temp(sensor_state)

    @asyncio.coroutine
    def _async_temp_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._async_update_current_temp(new_state)
        yield from self.async_update_ha_state()

    @staticmethod
    def represents_float(s):
        try:
            float(s)
            return True
        except ValueError:
            return False
         
    @callback
    def _async_update_current_temp(self, state):
        """Update thermostat with latest state from sensor."""
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        try:
            _state = state.state
            if self.represents_float(_state):
                self._current_temperature = self.hass.config.units.temperature(
                    float(_state), unit)
        except ValueError as ex:
            _LOGGER.error('Unable to update from sensor: %s', ex)    


    @property
    def should_poll(self):
        """Polling needed for thermostat."""
        _LOGGER.debug("Should_Poll called")
        return True

    def update(self):
        """Update the data from the thermostat."""
        self._post_data = '{"form":True, "login": ' + self._login + ', "password": ' + self._password + ', "keepme":False, "default_ui":1}'
        self._data = requests.post(self._host + '/ZAutomation/api/v1/devices/ZWayVDev_zway_' + str(self._node) + '-0-67-1', timeout=DEFAULT_TIMEOUT, json=self._post_data)
        self._json = json.loads(self._data)
        self._current_setpoint = float(self._json['data']['metrics']['level'])
        _LOGGER.debug("Update called")

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_FLAGS

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        else:
            self._post_data = '{"form":True, "login": ' + self._login + ', "password": ' + self._password + ', "keepme":False, "default_ui":1}'
            self._data = requests.post(self._host + '/ZAutomation/api/v1/devices/ZWayVDev_zway_' + str(self._node) + '-0-67-1/command/exact?level=' + str(self._target_temperature), timeout=DEFAULT_TIMEOUT, json=self._post_data)
            _LOGGER.debug("Set temperature=%s", str(temperature))
