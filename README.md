# Domoticz MQTT Discovery plugin
Domoticz Python plugin which implements support for [Home-Assistant style MQTT discovery](https://home-assistant.io/docs/mqtt/discovery/).

### Features:
- Switch and dimmer devices will be automatically found and added to Domoticz device database
- State in Domoticz in synchronized with device state (unlike with "Dummy hardware")
- Note: Sensors are not yet supported
- The plugin has some special adaptations for the Tasmota ESP8266 firmware.

### Prerequisites (general):

### Prerequisites (Sonoff or other ESP8266 devices with tasmota firmware):
- Domoticz must be from April 3 2018 or newer (must include PR #2249)
- Sonoff devices must be flashed with 5.11.1c or newer (must include support for home-assistant style MQTT discovery)
- Sonoff devices must have option 19 set to 1 (setoption19 1)
- Sonoff devices must be connected to MQTT server, and must have individual topics (by default all devices topic will be set to `sonoff`, this will not work)
- Sonoff fulltopic should be reasonable, for example "tasmota/%topic%/%prefix%/"

### Instructions:
- Clone this project into Domoticz 'plugins' folder
- Restart Domoticz
- Create hardware of type "MQTT Discovery"
  - Set MQTT IP and port
  - Set "Debug" to "Verbose" for debug log
- Domoticz should now detect any device running Tasmota firmware
