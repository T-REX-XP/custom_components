"""
Support for Zway z-wave thermostats.
http://IP:8083/ZWaveAPI/Run/devices[4].instances[0].commandClasses[67].data[1].modeName (get mode)
http://IP:8083/ZWaveAPI/Run/devices[4].instances[0].commandClasses[67].data[1].val.value (get temperature)
http://IP:8083/ZWaveAPI/Run/devices[4].instances[0].commandClasses[67].data[1].setVal=17  (set temperature)
http://IP:8083/ZWaveAPI/Run/devices[4].instances[0].commandClasses[128].data.last.value  (get battery state)

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
import voluptuous as vol

from homeassistant.components.climate import (ClimateDevice, PLATFORM_SCHEMA, SUPPORT_TARGET_TEMPERATURE, SUPPORT_OPERATION_MODE)
from homeassistant.const import (CONF_NAME, CONF_HOST,
                                 TEMP_CELSIUS, ATTR_TEMPERATURE)
import homeassistant.helpers.config_validation as cv

import requests

SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE | SUPPORT_OPERATION_MODE

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'Zway Thermostat'
DEFAULT_TIMEOUT = 5
DEFAULT_AWAY_TEMP = 16
DEFAULT_TARGET_TEMP = 21
DEFAULT_MIN_TEMP = 4
DEFAULT_MAX_TEMP = 40
DEFAULT_OPERATION_LIST = [STATE_OFF, STATE_HEAT, ]
CONF_NODE = 'node'
CONF_HOST = 'host'
CONF_AWAY_TEMP = 'away_temp'
CONF_TARGET_TEMP = 'target_temp'
CONF_TEMP_SENSOR = 'temp_sensor'
CONF_MIN_TEMP = 'min_temp'
CONF_MAX_TEMP = 'max_temp'
ATTR_MODE = 'mode'
STATE_OFF = 'off'
STATE_HEAT = 'heat'
BASE_URL = 'http://{0}:{1}{2}{3}{4}'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_HOST, default='127.0.0.1:8083'): cv.string,
    vol.Required(CONF_NODE): cv.positive_int,
    vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): cv.positive_int,
    vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): cv.positive_int,
    vol.Optional(CONF_TARGET_TEMP, default=DEFAULT_TARGET_TEMP): cv.positive_int,
    vol.Optional(CONF_DEFAULT_OPERATION, default=DEFAULT_OPERATION): cv.string,
    vol.Optional(CONF_TEMP_SENSOR): cv.entity_id,
    vol.Optional(CONF_AWAY_TEMP, default=DEFAULT_AWAY_TEMP): cv.positive_int,
})

def setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Setup the Zway thermostat."""
    name = config.get(CONF_NAME)
    ip_addr = config.get(CONF_HOST)
    node = config.get(CONF_NODE)
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    temp_sensor_entity_id = config.get(CONF_TEMP_SENSOR)
    default_operation = config.get(CONF_DEFAULT_OPERATION)

class ZwayClimate(ClimateDevice):
    """Representation of a Zwave thermostat."""

    def __init__(self, hass, name, host, min_temp, max_temp, target_temp, temp_sensor_entity_id, operation_list):
        """Initialize the thermostat."""
        self.hass = hass
        self._name = name
        self._node = node
        self._host = host
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temperature = target_temp
        self._target_temperature_step = 0.5
        self._battery = battery
        self._unit_of_measurement = hass.config.units.temperature_unit
        self._current_temperature = 0
        self._temp_sensor_entity_id = temp_sensor_entity_id
        self._current_operation = default_operation
        self._operation_list = ['Heating', 'Energy Saving', 'Frost Protection']
         
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

    @staticmethod
    def do_api_request(url):
        """Does an API request."""
        req = requests.get(url, timeout=DEFAULT_TIMEOUT)
        if req.status_code != requests.codes.ok:
            _LOGGER.exception("Error doing API request")
        else:
            _LOGGER.debug("API request ok %d", req.status_code)

        """Fixes invalid JSON output by TOON"""
        reqinvalid = req.text
        reqvalid = reqinvalid.replace('",}', '"}')

        return json.loads(req.text)

    @property
    def should_poll(self):
        """Polling needed for thermostat."""
        _LOGGER.debug("Should_Poll called")
        return True

    def update(self):
        """Update the data from the thermostat."""
        self._data = self.do_api_request(
            self._host+'/ZWaveAPI/Run/devices['+self._node+'].instances[0].commandClasses')
        self._current_setpoint = float(self._data['67.data.setVal.value'])
        self._current_mode = float(self._data['67.data.modeName.value'])
        self._battery = int(self._data['128.data.last.value'])
        self._schedule_type = int(self._data['70.overrideType.value'])
        self._schedule_state = int(self._data['70.overrideState.value'])
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
    def device_state_attributes(self):
        """Return the device specific state attributes."""
        return {
            ATTR_MODE: self._current_state
        }

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temp

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._current_setpoint

    @property
    def current_operation(self):
        """Return the current state of the thermostat."""
        state = self._current_state
        if state in (0, 1, 2):
            return self._operation_list[state]
        else:
            return STATE_UNKNOWN

    @property
    def operation_list(self):
        """List of available operation modes."""
        return self._operation_list

"""commandClasses 70, 
        override_type:
            0 - no override
            1 - permanently
            2 - temporary
        override_state:
            127 - unused
            122 - energy saving
            121 - frost protection

http://IP:8083/ZWaveAPI/Run/devices[4].instances[0].commandClasses[70].data.overrideType=1
http://IP:8083/ZWaveAPI/Run/devices[4].instances[0].commandClasses[67].data[1].modeName

        self._override_state = self.do_api_request(self._host+'/ZWaveAPI/Run/devices['+str(nodeid)+'].instances[0].commandClasses[70].data.overrideState='+str(override_state)))
        self._override_type = self.do_api_request(self._host+'/ZWaveAPI/Run/devices['+str(nodeid)+'].instances[0].commandClasses[70].data.overrideType='+str(override_type))
"""

    def set_operation_mode(self, operation_mode):
        """Set HVAC mode (heating)."""
        if operation_mode == "Heating":
            override_type = 0,
            override_state = 127
        elif operation_mode == "Energy Saving":
            override_type = 1,
            override_state = 122
        elif operation_mode == "Frost Protection":
            override_type = 1,
            override_state = 121

        self._operation_mode = self.do_api_request(
            self._host+'/ZWaveAPI/Run/devices['+str(nodeid)+'].instances[0].commandClasses[67].data[1].modeName.value=1')
        _LOGGER.debug("Set operation mode=%s(%s, %s)", str(operation_mode), 
                      str(override_type), 
                      str(override_state))

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        else:
            self._data = self.do_api_request(BASE_URL.format(
                self._host,
                '/ZWaveAPI/Run/devices['+str(node)+'].instances[0].commandClasses[67].data[1].setVal='
                +str(temperature)))
            _LOGGER.debug("Set temperature=%s", str(temperature))
