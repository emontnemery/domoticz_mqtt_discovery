#           MQTT discovery plugin
#
"""
<plugin key="MQTTDiscovery" name="MQTT discovery" version="0.0.5">
    <description>
      MQTT discovery, compatible with home-assistant.<br/><br/>
      Specify MQTT server and port.<br/>
      <br/>
      Automatically creates Domoticz device entries for all discovered devices.<br/>
    </description>
    <params>
        <param field="Address" label="MQTT Server address" width="300px" required="true" default="127.0.0.1"/>
        <param field="Port" label="Port" width="300px" required="true" default="1883"/>
        <!-- <param field="Mode5" label="MQTT QoS" width="300px" default="0"/> -->
        <param field="Username" label="Username" width="300px"/>
        <param field="Password" label="Password" width="300px"/>
        <!-- <param field="Mode1" label="CA Filename" width="300px"/> -->

        <param field="Mode2" label="Discovery topic" width="300px" default="homeassistant"/>
        <param field="Mode4" label="Ignored device topics (comma separated)" width="300px" default="tasmota/sonoff/"/>

        <param field="Mode3" label="Options" width="300px"/>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="Extra verbose: (Framework logs 2+4+8+16+64 + MQTT dump)" value="Verbose+"/>
                <option label="Verbose: (Framework logs 2+4+8+16+64 + MQTT dump)" value="Verbose"/>
                <option label="Normal: (Framework logs 2+4+8)" value="Debug"/>
                <option label="None" value="Normal"  default="true" />
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
#from Domoticz import Devices # Used for local debugging without Domoticz
from datetime import datetime
from itertools import count, filterfalse
import json
import re
import time
import traceback

class MqttClient:
    Address = ""
    Port = ""
    mqttConn = None
    isConnected = False
    mqttConnectedCb = None
    mqttDisconnectedCb = None
    mqttPublishCb = None

    def __init__(self, destination, port, mqttConnectedCb, mqttDisconnectedCb, mqttPublishCb, mqttSubackCb):
        Domoticz.Debug("MqttClient::__init__")
        self.Address = destination
        self.Port = port
        self.mqttConnectedCb = mqttConnectedCb
        self.mqttDisconnectedCb = mqttDisconnectedCb
        self.mqttPublishCb = mqttPublishCb
        self.mqttSubackCb = mqttSubackCb
        self.Open()

    def __str__(self):
        Domoticz.Debug("MqttClient::__str__")
        if (self.mqttConn != None):
            return str(self.mqttConn)
        else:
            return "None"

    def Open(self):
        Domoticz.Debug("MqttClient::Open")
        if (self.mqttConn != None):
            self.Close()
        self.isConnected = False
        self.mqttConn = Domoticz.Connection(Name=self.Address, Transport="TCP/IP", Protocol="MQTT", Address=self.Address, Port=self.Port)
        self.mqttConn.Connect()

    def Connect(self):
        Domoticz.Debug("MqttClient::Connect")
        if (self.mqttConn == None):
            self.Open()
        else:
            ID = 'Domoticz_'+Parameters['Key']+'_'+str(Parameters['HardwareID'])+'_'+str(int(time.time()))
            Domoticz.Log("MQTT CONNECT ID: '" + ID + "'")
            self.mqttConn.Send({'Verb': 'CONNECT', 'ID': ID})

    def Ping(self):
        Domoticz.Debug("MqttClient::Ping")
        if (self.mqttConn == None or not self.isConnected):
            self.Open()
        else:
            self.mqttConn.Send({'Verb': 'PING'})

    def Publish(self, topic, payload, retain = 0):
        Domoticz.Log("MqttClient::Publish " + topic + " (" + payload + ")")
        if (self.mqttConn == None or not self.isConnected):
            self.Open()
        else:
            self.mqttConn.Send({'Verb': 'PUBLISH', 'Topic': topic, 'Payload': bytearray(payload, 'utf-8'), 'Retain': retain})

    def Subscribe(self, topics):
        Domoticz.Debug("MqttClient::Subscribe")
        subscriptionlist = []
        for topic in topics:
            subscriptionlist.append({'Topic':topic, 'QoS':0})
        if (self.mqttConn == None or not self.isConnected):
            self.Open()
        else:
            self.mqttConn.Send({'Verb': 'SUBSCRIBE', 'Topics': subscriptionlist})

    def Close(self):
        Domoticz.Log("MqttClient::Close")
        #TODO: Disconnect from server
        self.mqttConn = None
        self.isConnected = False

    def onConnect(self, Connection, Status, Description):
        Domoticz.Debug("MqttClient::onConnect")
        if (Status == 0):
            Domoticz.Log("Successful connect to: "+Connection.Address+":"+Connection.Port)
            self.Connect()
        else:
            Domoticz.Log("Failed to connect to: "+Connection.Address+":"+Connection.Port+", Description: "+Description)

    def onDisconnect(self, Connection):
        Domoticz.Log("MqttClient::onDisonnect Disconnected from: "+Connection.Address+":"+Connection.Port)
        self.Close()
        # TODO: Reconnect?
        if self.mqttDisconnectedCb != None:
            self.mqttDisconnectedCb()

    def onMessage(self, Connection, Data):
        topic = ''
        if 'Topic' in Data:
            topic = Data['Topic']
        payloadStr = ''
        if 'Payload' in Data:
            payloadStr = Data['Payload'].decode('utf8','replace')
            payloadStr = str(payloadStr.encode('unicode_escape'))
        #Domoticz.Debug("MqttClient::onMessage called for connection: '"+Connection.Name+"' type:'"+Data['Verb']+"' topic:'"+topic+"' payload:'" + payloadStr + "'")

        if Data['Verb'] == "CONNACK":
            self.isConnected = True
            if self.mqttConnectedCb != None:
                self.mqttConnectedCb()

        if Data['Verb'] == "SUBACK":
            if self.mqttSubackCb != None:
                self.mqttSubackCb()

        if Data['Verb'] == "PUBLISH":
            if self.mqttPublishCb != None:
                self.mqttPublishCb(topic, Data['Payload'])

CONF_DEVICE = 'device'
TOPIC_BASE = '~'

ABBREVIATIONS = {
    'aux_cmd_t': 'aux_command_topic',
    'aux_stat_tpl': 'aux_state_template',
    'aux_stat_t': 'aux_state_topic',
    'avty_t': 'availability_topic',
    'away_mode_cmd_t': 'away_mode_command_topic',
    'away_mode_stat_tpl': 'away_mode_state_template',
    'away_mode_stat_t': 'away_mode_state_topic',
    'bri_cmd_t': 'brightness_command_topic',
    'bri_scl': 'brightness_scale',
    'bri_stat_t': 'brightness_state_topic',
    'bri_val_tpl': 'brightness_value_template',
    'clr_temp_cmd_tpl': 'color_temp_command_template',
    'bat_lev_t': 'battery_level_topic',
    'bat_lev_tpl': 'battery_level_template',
    'chrg_t': 'charging_topic',
    'chrg_tpl': 'charging_template',
    'clr_temp_cmd_t': 'color_temp_command_topic',
    'clr_temp_stat_t': 'color_temp_state_topic',
    'clr_temp_val_tpl': 'color_temp_value_template',
    'cln_t': 'cleaning_topic',
    'cln_tpl': 'cleaning_template',
    'cmd_t': 'command_topic',
    'curr_temp_t': 'current_temperature_topic',
    'dev': 'device',
    'dev_cla': 'device_class',
    'dock_t': 'docked_topic',
    'dock_tpl': 'docked_template',
    'err_t': 'error_topic',
    'err_tpl': 'error_template',
    'fanspd_t': 'fan_speed_topic',
    'fanspd_tpl': 'fan_speed_template',
    'fanspd_lst': 'fan_speed_list',
    'fx_cmd_t': 'effect_command_topic',
    'fx_list': 'effect_list',
    'fx_stat_t': 'effect_state_topic',
    'fx_val_tpl': 'effect_value_template',
    'exp_aft': 'expire_after',
    'fan_mode_cmd_t': 'fan_mode_command_topic',
    'fan_mode_stat_tpl': 'fan_mode_state_template',
    'fan_mode_stat_t': 'fan_mode_state_topic',
    'frc_upd': 'force_update',
    'hold_cmd_t': 'hold_command_topic',
    'hold_stat_tpl': 'hold_state_template',
    'hold_stat_t': 'hold_state_topic',
    'ic': 'icon',
    'init': 'initial',
    'json_attr': 'json_attributes',
    'json_attr_t': 'json_attributes_topic',
    'max_temp': 'max_temp',
    'min_temp': 'min_temp',
    'mode_cmd_t': 'mode_command_topic',
    'mode_stat_tpl': 'mode_state_template',
    'mode_stat_t': 'mode_state_topic',
    'name': 'name',
    'on_cmd_type': 'on_command_type',
    'opt': 'optimistic',
    'osc_cmd_t': 'oscillation_command_topic',
    'osc_stat_t': 'oscillation_state_topic',
    'osc_val_tpl': 'oscillation_value_template',
    'pl_arm_away': 'payload_arm_away',
    'pl_arm_home': 'payload_arm_home',
    'pl_avail': 'payload_available',
    'pl_cls': 'payload_close',
    'pl_disarm': 'payload_disarm',
    'pl_hi_spd': 'payload_high_speed',
    'pl_lock': 'payload_lock',
    'pl_lo_spd': 'payload_low_speed',
    'pl_med_spd': 'payload_medium_speed',
    'pl_not_avail': 'payload_not_available',
    'pl_off': 'payload_off',
    'pl_on': 'payload_on',
    'pl_open': 'payload_open',
    'pl_osc_off': 'payload_oscillation_off',
    'pl_osc_on': 'payload_oscillation_on',
    'pl_stop': 'payload_stop',
    'pl_unlk': 'payload_unlock',
    'pow_cmd_t': 'power_command_topic',
    'ret': 'retain',
    'rgb_cmd_tpl': 'rgb_command_template',
    'rgb_cmd_t': 'rgb_command_topic',
    'rgb_stat_t': 'rgb_state_topic',
    'rgb_val_tpl': 'rgb_value_template',
    'send_cmd_t': 'send_command_topic',
    'send_if_off': 'send_if_off',
    'set_pos_tpl': 'set_position_template',
    'set_pos_t': 'set_position_topic',
    'spd_cmd_t': 'speed_command_topic',
    'spd_stat_t': 'speed_state_topic',
    'spd_val_tpl': 'speed_value_template',
    'spds': 'speeds',
    'stat_clsd': 'state_closed',
    'stat_off': 'state_off',
    'stat_on': 'state_on',
    'stat_open': 'state_open',
    'stat_t': 'state_topic',
    'stat_val_tpl': 'state_value_template',
    'sup_feat': 'supported_features',
    'swing_mode_cmd_t': 'swing_mode_command_topic',
    'swing_mode_stat_tpl': 'swing_mode_state_template',
    'swing_mode_stat_t': 'swing_mode_state_topic',
    'temp_cmd_t': 'temperature_command_topic',
    'temp_stat_tpl': 'temperature_state_template',
    'temp_stat_t': 'temperature_state_topic',
    'tilt_clsd_val': 'tilt_closed_value',
    'tilt_cmd_t': 'tilt_command_topic',
    'tilt_inv_stat': 'tilt_invert_state',
    'tilt_max': 'tilt_max',
    'tilt_min': 'tilt_min',
    'tilt_opnd_val': 'tilt_opened_value',
    'tilt_status_opt': 'tilt_status_optimistic',
    'tilt_status_t': 'tilt_status_topic',
    't': 'topic',
    'uniq_id': 'unique_id',
    'unit_of_meas': 'unit_of_measurement',
    'val_tpl': 'value_template',
    'whit_val_cmd_t': 'white_value_command_topic',
    'whit_val_scl': 'white_value_scale',
    'whit_val_stat_t': 'white_value_state_topic',
    'whit_val_tpl': 'white_value_template',
    'xy_cmd_t': 'xy_command_topic',
    'xy_stat_t': 'xy_state_topic',
    'xy_val_tpl': 'xy_value_template',
}

DEVICE_ABBREVIATIONS = {
    'cns': 'connections',
    'ids': 'identifiers',
    'name': 'name',
    'mf': 'manufacturer',
    'mdl': 'model',
    'sw': 'sw_version',
}


class BasePlugin:
    # MQTT settings
    mqttClient = None
    mqttserveraddress = ""
    mqttserverport = ""
    debugging = "Normal"
    cachedDeviceNames = {}

    options = {"addDiscoveredDeviceUsed":True, # Newly discovered devices added as "used" (visible in swithces tab) or not (only visible in devices list)
               "updateRSSI":False,             # Store Tasmota RSSI
               "updateVCC":False}              # Store Tasmota VCC as battery level

    def copyDevices(self):
        #self.cachedDevices = copy.deepcopy(Devices)
        for k, Device in Devices.items():
            self.cachedDeviceNames[k]=Device.Name

    def deviceStr(self, unit):
        name = "<UNKNOWN>"
        if unit in Devices:
            name = Devices[unit].Name
        return format(unit, '03d') + "/" + name

    def getUnit(self, device):
        unit = -1
        for k, dev in Devices.items():
            if dev == device:
                unit = k
        return unit

    def onStart(self):

        # Parse options
        self.debugging = Parameters["Mode6"]
        DumpConfigToLog()
        if self.debugging == "Verbose+":
            Domoticz.Debugging(2+4+8+16+64)
        if self.debugging == "Verbose":
            Domoticz.Debugging(2+4+8+16+64)
        if self.debugging == "Debug":
            Domoticz.Debugging(2+4+8)
        self.mqttserveraddress = Parameters["Address"].replace(" ", "")
        self.mqttserverport = Parameters["Port"].replace(" ", "")
        self.discoverytopic = Parameters["Mode2"]
        self.ignoredtopics = Parameters["Mode4"].split(',')

        options = ""
        try:
            options = json.loads(Parameters["Mode3"])
        except ValueError:
            options = Parameters["Mode3"]

        if type(options) == str or type(options) == int:
            # JSON decoding failed, check for deprecated used/unused setting
            # <options>
            #   <option label="Unused" value="0"/>
            #   <option label="Used" value="1"  default="true" />
            # </options>
            Domoticz.Log("Warning: could not load plugin options '" + Parameters["Mode3"] + "' as JSON object")
            try:
              if int(options) == 0:
                self.options['addDiscoveredDeviceUsed'] = False
              if int(options) == 1:
                self.options['addDiscoveredDeviceUsed'] = True
            except ValueError: #Options not a valid int
              pass
        elif type(options) == dict:
            self.options.add(options)
        Domoticz.Log("Plugin options: " + str(self.options))

        # Enable heartbeat
        Domoticz.Heartbeat(10)

        # Connect to MQTT server
        self.prefixpos = 0
        self.topicpos = 0
        self.discoverytopiclist = self.discoverytopic.split('/')
        self.mqttClient = MqttClient(self.mqttserveraddress, self.mqttserverport, self.onMQTTConnected, self.onMQTTDisconnected, self.onMQTTPublish, self.onMQTTSubscribed)

        self.copyDevices()

    def onConnect(self, Connection, Status, Description):
        self.mqttClient.onConnect(Connection, Status, Description)

    def onDisconnect(self, Connection):
        self.mqttClient.onDisconnect(Connection)

    def onMessage(self, Connection, Data):
        self.mqttClient.onMessage(Connection, Data)

    def onMQTTConnected(self):
        Domoticz.Debug("onMQTTConnected")
        self.mqttClient.Subscribe(self.getTopics())

    def onMQTTDisconnected(self):
        Domoticz.Debug("onMQTTDisconnected")

    def onMQTTPublish(self, topic, rawmessage):
        validJSON = False
        message = ""
        try:
            message = json.loads(rawmessage.decode('utf8'))
            validJSON = True
        except ValueError:
            message = rawmessage.decode('utf8')

        topiclist = topic.split('/')
        if self.debugging == "Verbose" or self.debugging == "Verbose+":
            DumpMQTTMessageToLog(topic, rawmessage, 'onMQTTPublish: ')

        if topic in self.ignoredtopics:
            Domoticz.Debug("Topic: '"+topic+"' included in ignored topics, message ignored")
            return

        if topic.startswith(self.discoverytopic):
            discoverytopiclen = len(self.discoverytopiclist)
            # Discovery topic format:
            # <discovery_prefix>/<component>/[<node_id>/]<object_id>/<action>
            if len(topiclist) == discoverytopiclen + 3 or len(topiclist) == discoverytopiclen + 4:
              component = topiclist[discoverytopiclen]
              if len(topiclist) == discoverytopiclen + 3:
                node_id = ''
                object_id = topiclist[discoverytopiclen+1]
                action = topiclist[discoverytopiclen+2]
              else:
                node_id = topiclist[discoverytopiclen+1]
                object_id = topiclist[discoverytopiclen+2]
                action = topiclist[discoverytopiclen+3]

              # Sensor support
              if ( component == "sensor" ) and ( node_id != "" ):
                  object_id = node_id
              # End Sensor support

              if validJSON and action == 'config' and ('command_topic' in message or 'state_topic' in message or 'cmd_t' in message or 'stat_t' in message):
                # Do expansion of the message
                payload = dict(message)
                for key in list(payload.keys()):
                  abbreviated_key = key
                  key = ABBREVIATIONS.get(key, key)
                  payload[key] = payload.pop(abbreviated_key)

                if CONF_DEVICE in payload:
                  device = payload[CONF_DEVICE]
                  for key in list(device.keys()):
                    abbreviated_key = key
                    key = DEVICE_ABBREVIATIONS.get(key, key)
                    device[key] = device.pop(abbreviated_key)

                base = payload.pop(TOPIC_BASE, None)
                if base:
                  for key, value in payload.items():
                    if isinstance(value, str) and value:
                      if value[0] == TOPIC_BASE and key.endswith('_topic'):
                        payload[key] = "{}{}".format(base, value[1:])
                      if value[-1] == TOPIC_BASE and key.endswith('_topic'):
                        payload[key] = "{}{}".format(value[:-1], base)

                # Add / update the device
                self.updateDeviceSettings(object_id, component, payload)
        else:
            matchingDevices = self.getDevices(topic=topic)
            for device in matchingDevices:
                # Sensor support. Do not throw exception on unknown topics. See also open pull request #29 https://github.com/emontnemery/domoticz_mqtt_discovery/pulls
                if not self.updateSensor(device, topic, message):
                    self.updateSwitch(device, topic, message)
                # end Sensor support

                # Try to update availability
                self.updateAvailability(device, topic, message)

                # TODO: Try to update sensor
                #self.updateSensor(device, topic, message)

                # TODO: Try to update binary sensor
                #self.updateBinarySensor(device, topic, message)

                # TODO: Try to update tasmota status
                self.updateTasmotaStatus(device, topic, message)

            # Special handling of Tasmota STATE message
            topic2, matches = re.subn(r"\/STATUS\d+$", '/STATE', topic)
            if matches > 0:
                topic2, matches = re.subn(r"\/stat\/", '/tele/', topic2)
                if matches > 0:
                    matchingDevices = self.getDevices(topic=topic2)
                    for device in matchingDevices:
                        # Try to update tasmota settings
                        self.updateTasmotaSettings(device, topic, message)

    def onMQTTSubscribed(self):
        # (Re)subscribed, refresh device info
        Domoticz.Debug("onMQTTSubscribed");
        matchingDevices = self.getDevices(hasconfigkey='tasmota_tele_topic')
        topics = set()
        for device in matchingDevices:
            # Refresh Tasmota specific data
            try:
                configdict = json.loads(device.Options['config'])
                cmnd_topic = re.sub(r"^tele\/", "cmnd/", configdict['tasmota_tele_topic']) # Replace tele with cmnd
                cmnd_topic = re.sub(r"\/tele\/", "/cmnd/", cmnd_topic) # Replace tele with cmnd
                cmnd_topic = re.sub(r"\/STATE", "", cmnd_topic) # Remove '/STATE'
                if cmnd_topic not in topics: self.refreshConfiguration(cmnd_topic)
                topics.add(cmnd_topic)
            except (ValueError, KeyError, TypeError) as e:
                #Domoticz.Error("onMQTTSubscribed: Error: " + str(e))
                Domoticz.Error(traceback.format_exc())

# ==========================================================DASHBOARD COMMAND=============================================================
    def onCommand(self, Unit, Command, Level, sColor):
        Domoticz.Log("onCommand " + self.deviceStr(Unit) + ": Command: '" + str(Command) + "', Level: " + str(Level) + ", Color:" + str(sColor));

        if Unit in Devices:
            try:
                # TODO: Make sure the relevant command topic exists
                configdict = json.loads(Devices[Unit].Options['config'])
                if Command == "Set Level" and  "set_position_topic" in configdict:
                    self.mqttClient.Publish(configdict["set_position_topic"],str(Level))
                elif Command == "Set Brightness" or Command == "Set Level":
                    self.mqttClient.Publish(configdict["brightness_command_topic"],str(Level))
                elif Command == "On":
                    payload = "ON"
                    if "payload_on" in configdict: payload = configdict["payload_on"]
                    elif "payload_close" in configdict: payload = configdict["payload_close"]
                    self.mqttClient.Publish(configdict["command_topic"],payload)
                elif Command == "Off":
                    payload = "OFF"
                    if "payload_off" in configdict: payload = configdict["payload_off"]
                    elif "payload_open" in configdict: payload = configdict["payload_open"]
                    self.mqttClient.Publish(configdict["command_topic"],payload)
                elif Command == "Stop":
                    payload = "STOP"
                    if "payload_stop" in configdict: payload = configdict["payload_stop"]
                    self.mqttClient.Publish(configdict["command_topic"],payload)
                elif Command == "Set Color":
                    try:
                        Color = json.loads(sColor);
                    except (ValueError, KeyError, TypeError) as e:
                        Domoticz.Error("onCommand: Illegal color: '" + str(sColor) + "'")
                    # TODO: This is not really correct, should check color mode
                    r = int(Color["r"]*Level/100)
                    g = int(Color["g"]*Level/100)
                    b = int(Color["b"]*Level/100)
                    cw = int(Color["cw"]*Level/100)
                    ww = int(Color["ww"]*Level/100)
                    if "rgb_command_topic" in configdict and "brightness_command_topic" in configdict:
                        self.mqttClient.Publish(configdict["rgb_command_topic"],format(r, '02x') + format(g, '02x') + format(b, '02x') + format(cw, '02x') + format(ww, '02x'))
                        self.mqttClient.Publish(configdict["brightness_command_topic"],str(Level))
                    elif "color_temp_command_topic" in configdict and "brightness_command_topic" in configdict:
                        self.mqttClient.Publish(configdict["color_temp_command_topic"],str(Color["t"]*(500-153)/255+153))
                        self.mqttClient.Publish(configdict["brightness_command_topic"],str(Level))
            except (ValueError, KeyError, TypeError) as e:
                Domoticz.Error("onCommand: Error: " + str(e))
        else:
            Domoticz.Debug("Device not found, ignoring command");

    def onDeviceAdded(self, Unit):
        Domoticz.Log("onDeviceAdded " + self.deviceStr(Unit))
        self.copyDevices()
        #TODO: Update subscribed topics

    def onDeviceModified(self, Unit):
        Domoticz.Log("onDeviceModified " + self.deviceStr(Unit))

        if Unit in Devices and Devices[Unit].Name != self.cachedDeviceNames[Unit]:
            Domoticz.Log("Device name changed, new name: " + Devices[Unit].Name + ", old name: " + self.cachedDeviceNames[Unit])
            Device = Devices[Unit]

            try:
                configdict = json.loads(Device.Options['config'])
                if "tasmota_tele_topic" in configdict and Device.SwitchType != 9: # Do not set friendly name for button, they don't have their own friendly name
                    #Tasmota device!
                    device_nbr = ''
                    m = re.match(r".*_(\d)$", str(Device.Options['devicename']))
                    if m:
                        device_nbr = m.group(1)
                    cmnd_topic = re.sub(r"\/POWER\d?", "", configdict['command_topic']) # Remove '/POWER'
                    self.mqttClient.Publish(cmnd_topic+'/FriendlyName'+str(device_nbr), Device.Name)
            except (ValueError, KeyError, TypeError) as e:
                Domoticz.Debug("onDeviceModified: Error: " + str(e))
                pass

        self.copyDevices()

    def onDeviceRemoved(self, Unit):
        Domoticz.Log("onDeviceRemoved " + self.deviceStr(Unit))
        if Unit in Devices and 'devicename' in Devices[Unit].Options:
            Device = Devices[Unit]
            # Clear retained topic
            devicetype = ''
            if (Device.Type == 0xf4 and     # pTypeGeneralSwitch
                Device.SubType == 0x49 and  # sSwitchGeneralSwitch
                Device.SwitchType == 0):    # OnOff
                devicetype = 'switch'
            elif (Device.Type == 0xf4 and   # pTypeGeneralSwitch
                Device.SubType == 0x49 and  # sSwitchGeneralSwitch
                Device.SwitchType == 7):    # Dimmer
                devicetype = 'light'
            elif Device.Type == 0xf1:       # pTypeColorSwitch
                devicetype = 'light'
            elif (Device.Type == 0xf4 and   # pTypeGeneralSwitch
                Device.SubType == 0x49 and  # sSwitchGeneralSwitch
                ((Device.SwitchType == 3) or  # Blind (up/down buttons)
                 (Device.SwitchType == 15) or # Venetian blinds EU (up/down/stop buttons)
                 (Device.SwitchType == 13))): # Blinds Percentage
                devicetype = 'blinds' 
            elif (Device.Type == 0xf4 and   # pTypeGeneralSwitch
                Device.SubType == 0x49 and  # sSwitchGeneralSwitch
                Device.SwitchType == 9):    # STYPE_PushOn
                devicetype = 'binary_sensor'
            # Sensor support
            elif self.isMQTTSensor(Device):
                devicetype = 'sensor'
            # End Sensor support
            if devicetype:
                topic = self.discoverytopic + '/' + devicetype + '/' + Devices[Unit].Options['devicename'] + '/config'
                Domoticz.Log("Clearing topic '" + topic + "'")
                self.mqttClient.Publish(topic, '', 1)
        self.copyDevices()
        #TODO: Update subscribed topics

    def onHeartbeat(self):
        Domoticz.Debug("Heartbeating...")

        # Reconnect if connection has dropped
        if self.mqttClient.mqttConn is None or (not self.mqttClient.mqttConn.Connecting() and not self.mqttClient.mqttConn.Connected() or not self.mqttClient.isConnected):
            Domoticz.Debug("Reconnecting")
            self.mqttClient.Open()
        else:
            self.mqttClient.Ping()

    # Pull configuration and status from tasmota device
    def refreshConfiguration(self, Topic):
        Domoticz.Debug("refreshConfiguration for device with topic: '" + Topic + "'");
        # Refresh relay / dimmer configuration
        self.mqttClient.Publish(Topic+"/Status",'11')
        # Refresh sensor configuration
        #self.mqttClient.Publish(Topic+"/Status",'10')
        # Refresh IP configuration
        self.mqttClient.Publish(Topic+"/Status",'5')

    # Returns list of topics to subscribe to
    def getTopics(self):
        topics = set()
        for key,Device in Devices.items():
            #Domoticz.Debug("getTopics: '" + str(Device.Options) +"'")
            try:
                configdict = json.loads(Device.Options['config'])
                #Domoticz.Debug("getTopics: '" + str(configdict) +"'")
                for key, value in configdict.items():
                    #Domoticz.Debug("getTopics: key:'" + str(key) +"' value: '" + str(value) + "'")
                    try:
                        #if key.endswith('_topic'):
                        if key == 'availability_topic' or key == 'state_topic' or key == 'brightness_state_topic' or key == 'rgb_state_topic' or key == 'color_temp_state_topic' or key == 'position_topic':
                            topics.add(value)
                    except (TypeError) as e:
                        Domoticz.Error("getTopics: Error: " + str(e))
                        pass
                if "tasmota_tele_topic" in configdict:
                    #Subscribe to all Tasmota state topics
                    state_topic = re.sub(r"^tele\/", "stat/", configdict['tasmota_tele_topic']) # Replace tele with stat
                    state_topic = re.sub(r"\/tele\/", "/stat/", state_topic) # Replace tele with stat
                    state_topic = re.sub(r"\/STATE", "/#", state_topic) # Replace '/STATE' with /#
                    topics.add(state_topic)
            except (ValueError, KeyError, TypeError) as e:
                Domoticz.Error("getTopics: Error: " + str(e))
                pass
        topics.add(self.discoverytopic+'/#')
        Domoticz.Debug("getTopics: '" + str(topics) +"'")
        return list(topics)

    # Returns list of matching devices
    def getDevices(self, key='', configkey='', hasconfigkey='', value='', config='', topic='', type='', channel=''):
        Domoticz.Debug("getDevices key: '" + key + "' configkey: '" + configkey + "' hasconfigkey: '" + hasconfigkey + "' value: '" + value + "' config: '" + config + "' topic: '" + topic + "'")
        matchingDevices = set()
        if key != '':
            for k, Device in Devices.items():
                try:
                    if Device.Options[key] == value:
                        matchingDevices.add(Device)
                except (ValueError, KeyError) as e:
                    pass
        if configkey != '':
            for k, Device in Devices.items():
                try:
                    configdict = json.loads(Device.Options['config'])
                    if configdict[configkey] == value:
                        matchingDevices.add(Device)
                except (ValueError, KeyError) as e:
                    pass
        elif hasconfigkey != '':
            for k, Device in Devices.items():
                try:
                    configdict = json.loads(Device.Options['config'])
                    if hasconfigkey in configdict:
                        matchingDevices.add(Device)
                except (ValueError, KeyError) as e:
                    pass
        elif config != '':
            for k, Device in Devices.items():
                try:
                    if Device.Options['config'] == config:
                        matchingDevices.add(Device)
                except KeyError:
                    pass
        elif topic != '':
            for k, Device in Devices.items():
                try:
                    configdict = json.loads(Device.Options['config'])
                    for key, value in configdict.items():
                        if value == topic:
                            matchingDevices.add(Device)
                except (ValueError, KeyError) as e:
                    pass
        Domoticz.Debug("getDevices found " + str(len(matchingDevices)) + " devices")
        return list(matchingDevices)

    def makeDevice(self, devicename, TypeName, switchTypeDomoticz, config):
        iUnit = next(filterfalse(set(Devices).__contains__, count(1))) # First unused 'Unit'

        Domoticz.Log("Creating device with unit: " + str(iUnit));

        Options = {'config':json.dumps(config),'devicename':devicename}
        #DeviceName = topic+' - '+type
        DeviceName = config['name']
        Domoticz.Device(Name=DeviceName, Unit=iUnit, TypeName=TypeName, Switchtype=switchTypeDomoticz, Options=Options, Used=self.options['addDiscoveredDeviceUsed']).Create()

    def makeDeviceRaw(self, devicename, Type, Subtype, switchTypeDomoticz, config):
        iUnit = next(filterfalse(set(Devices).__contains__, count(1))) # First unused 'Unit'

        Domoticz.Log("Creating device with unit: " + str(iUnit));

        Options = {'config':json.dumps(config),'devicename':devicename}
        #DeviceName = topic+' - '+type
        DeviceName = config['name']
        Domoticz.Device(Name=DeviceName, Unit=iUnit, Type=Type, Subtype=Subtype, Switchtype=switchTypeDomoticz, Options=Options, Used=self.options['addDiscoveredDeviceUsed']).Create()

    def isDeviceIgnored(self, config):
        ignore = False
        for ignoredtopic in self.ignoredtopics:
            for key, value in config.items():
                if key.endswith('_topic'):
                    if value.startswith(ignoredtopic):
                        ignore = True
                        Domoticz.Debug("isDeviceIgnored: " + str(ignore))
        return ignore

    def addTasmotaTopics(self, config):
        isTasmota = False
        # TODO: Something smarter to detect Tasmota device
        try:
            #if "/cmnd/" in config["command_topic"] and "/POWER" in config["command_topic"] and "/tele/" in config["availability_topic"] and "/LWT" in config["availability_topic"]:
            if (("/stat/" in config["state_topic"] and "/RESULT" in config["state_topic"]) or ("/cmnd/" in config["state_topic"] and "/POWER" in config["state_topic"]) or ("/tele/" in config["state_topic"] and "/STATE" in config["state_topic"])) and "/tele/" in config["availability_topic"] and "/LWT" in config["availability_topic"]:
                isTasmota = True

            Domoticz.Debug("isTasmota: " + str(isTasmota))
            if isTasmota:
                statetopic = config["availability_topic"].replace("/LWT", "/STATE")
                Domoticz.Debug("statetopic: " + statetopic)
                config['tasmota_tele_topic'] = statetopic
        except (ValueError, KeyError) as e:
            pass

# =============================================================DEVICE CONFIG==============================================================
    def updateDeviceSettings(self, devicename, devicetype, config):
        Domoticz.Debug("updateDeviceSettings devicename: '" + devicename + "' devicetype: '" + devicetype + "' config: '" + str(config) + "'")

        TypeName = ''
        Type = 0
        Subtype = 0
        switchTypeDomoticz = 0 # OnOff
        if (devicetype == 'light' or devicetype == 'switch') and ('brightness_command_topic' in config or 'color_temp_command_topic' in config or 'rgb_command_topic' in config):
            Domoticz.Debug("devicetype == 'light'")
            switchTypeDomoticz = 7 # Dimmer
            rgbww = 0
            if 'white_value_command_topic' in config:
                rgbww = 1
            if 'color_temp_command_topic' in config:
                rgbww = 2
            if 'rgb_command_topic' in config:
                rgbww = rgbww + 3
            if rgbww == 2:     # WW
                Type = 0xf1    # pTypeColorSwitch
                Subtype = 0x08 # sTypeColor_CW_WW
            elif rgbww == 3:   # RGB
                Type = 0xf1    # pTypeColorSwitch
                Subtype = 0x02 # sTypeColor_RGB
            elif rgbww == 4:   # RGBW
                Type = 0xf1    # pTypeColorSwitch
                Subtype = 0x06 # sTypeColor_RGB_W_Z
            elif rgbww == 5:   # RGBWW
                Type = 0xf1    # pTypeColorSwitch
                Subtype = 0x07 # sTypeColor_RGB_CW_WW_Z
            else:
                TypeName = 'Switch'
                Type = 0xf4    # pTypeGeneralSwitch
                Subtype = 0x49 # sSwitchGeneralSwitch
        elif devicetype == 'switch' or devicetype == 'light': # Switch or light without dimming/color/color temperature
            Domoticz.Debug("devicetype == 'switch'")
            TypeName = 'Switch'
            Type = 0xf4        # pTypeGeneralSwitch
            Subtype = 0x49     # sSwitchGeneralSwitch
        elif devicetype == 'binary_sensor':
            TypeName = 'Switch'
            Type = 0xf4        # pTypeGeneralSwitch
            Subtype = 0x49     # sSwitchGeneralSwitch
            switchTypeDomoticz = 9 # STYPE_PushOn
        elif (devicetype == 'cover') and ('set_position_topic' in config):
            Type = 0xf4        # pTypeGeneralSwitch
            Subtype = 0x49     # sSwitchGeneralSwitch
            switchTypeDomoticz = 13 # Blinds percent
        elif devicetype == 'cover':
            TypeName = 'Switch'
            Type = 0xf4        # pTypeGeneralSwitch
            Subtype = 0x49     # sSwitchGeneralSwitch
            switchTypeDomoticz = 15 # STYPE_Blinds Venetian-type  with UP / DOWN / STOP   buttons
        # Sensor support
        elif devicetype == 'sensor':
            if 'device_class' in config:
                if config[ 'device_class' ] == 'temperature':
                    Type = 0x50         # pTypeTemp RFXTrx.h
                    Subtype = 0x01      # LaCrosse TX3
                elif config[ 'device_class' ] == 'humidity':
                    Type = 0x52         # pTypeTempHum
                    Subtype = 0x01      # La Crosse
        # End Sensor support

        matchingDevices = self.getDevices(key='devicename', value=devicename)
        if len(matchingDevices) == 0:
            Domoticz.Log("updateDeviceSettings: Did not find device with key='devicename', value = '" +  devicename + "'")
            # Unknown device
            Domoticz.Log("updateDeviceSettings: TypeName: '" + TypeName + "' Type: " + str(Type))
            if TypeName != '':
                self.addTasmotaTopics(config)
                if not self.isDeviceIgnored(config):
                    self.makeDevice(devicename, TypeName, switchTypeDomoticz, config)
                    # Update subscription list
                    self.mqttClient.Subscribe(self.getTopics())
            elif Type != 0:
                self.addTasmotaTopics(config)
                if not self.isDeviceIgnored(config):
                    self.makeDeviceRaw(devicename, Type, Subtype, switchTypeDomoticz, config)
                    # Update subscription list
                    self.mqttClient.Subscribe(self.getTopics())
        else:
            # TODO: What do if len(matchingDevices) > 1?
            device = matchingDevices[0]
            self.addTasmotaTopics(config)
            oldconfigdict = {}
            try:
                oldconfigdict = json.loads(device.Options['config'])
            except (ValueError, KeyError, TypeError) as e:
                pass
            # Sensor support
            # Correction for subsequent messages
            if self.isMQTTSensor(device):
                config['value_template'] = oldconfigdict['value_template']
                if device.Type == 0x52 and Type == 0x50:
                    Type = 0  # Reset, no change
                    Subtype = 0
            # End Sensor support
            if Type != 0 and (device.Type != Type or device.SubType != Subtype or device.SwitchType != switchTypeDomoticz or oldconfigdict != config):
                Domoticz.Log("updateDeviceSettings: " + self.deviceStr(self.getUnit(device)) + ": Device settings not matching, updating Type, SubType, Switchtype and Options['config']")
                Domoticz.Log("updateDeviceSettings: device.Type: " + str(device.Type) + "->" + str(Type) + ", device.SubType: " + str(device.SubType) + "->" + str(Subtype) +
                             ", device.SwitchType: " + str(device.SwitchType) + "->" + str(switchTypeDomoticz) +
                             ", device.Options['config']: " + str(oldconfigdict) + " -> " + str(config))
                nValue = device.nValue
                sValue = device.sValue
                Options = dict(device.Options)
                Options['config'] = json.dumps(config)
                device.Update(nValue=nValue, sValue=sValue, Type=Type, Subtype=Subtype, Switchtype=switchTypeDomoticz, Options=Options, SuppressTriggers=True)
                self.copyDevices()

# ==========================================================UPDATE STATUS from MQTT==============================================================
# Sensor support
    def isMQTTSensor(self, Device):
        return (((Device.Type == 0x50) or (Device.Type == 0x52)) and    # pTypeTemp or pTypeTemHum
                ((Device.SubType == 0x05) or (Device.SubType == 0x01))  # La Cross Temp_Hum combined
               )

    def updateSensor(self, device, topic, message):
        Domoticz.Debug("updateSensor topic: '" + topic + "' message: '" + str(message) + "'")

        nValue = device.nValue #0
        sValue = device.sValue #-1
        isTeleTopic = False # Tasmota tele topic
        updatedevice = False
        bat = 255
        rss = 12
        result = False

        try:
            devicetopics=[]
            configdict = json.loads(device.Options['config'])
            for key, value in configdict.items():
                if value == topic:
                    devicetopics.append(key)
            if ("state_topic" in devicetopics
                or "tasmota_tele_topic" in devicetopics): # Switch status is present in Tasmota tele/STAT message
                if ("state_topic" in devicetopics): Domoticz.Debug("UpdateSensor: Got state_topic " + configdict["state_topic"])
                if ("tasmota_tele_topic" in devicetopics): Domoticz.Debug("UpdateSensor: Got tasmota_tele_topic " + configdict["tasmota_tele_topic"])
                if ("tasmota_tele_topic" in devicetopics): isTeleTopic = True # Suppress device triggers for periodic tele/STAT message

                if self.isMQTTSensor(device):
                    result = True

                    Domoticz.Debug("UpdateSensor: value_template '" +  configdict['value_template'] + "'")
                    value_template = "Temperature"

                    msg = message
                    Domoticz.Debug("UpdateSensor: MSG: " + str(msg))

                    m = re.match(r"^{{[\s]*value_json\.*(.+)[\s]*}}$", configdict['value_template'])

                    if m != None:
                        value_template = m.group( 1 ).strip().strip("'").strip('"')
                        m = re.split(r"\[(.*?)\]", value_template )

                        Domoticz.Debug("UpdateSensor: value_template '" + value_template + "'")

                        if m != None:
                            Domoticz.Debug( "UpdateSensor: M1:" + str( m ))
                            if len( m ) > 1:
                                value_template = m[ len( m ) - 2 ].strip().strip("'").strip('"')
                                Domoticz.Debug("UpdateSensor: value_template '" + value_template + "'")
                                m = m[ 1:len(m) - 2 ]
                                Domoticz.Debug("UpdateSensor: M2:" + str( m ) )
                                for value in m:
                                    val = value.strip().strip("'").strip('"')
                                    Domoticz.Debug("UpdateSensor: VAL: " + str(val))
                                    if len(val) > 0:
                                        msg = msg[ val ]
                                        Domoticz.Debug("UpdateSensor: MSG: " + str(msg))

                    Domoticz.Debug("UpdateSensor: Matched template '" + value_template + "', Message: " + str(msg) )

                    temp = None
                    try:
                        temp = float(msg[value_template])
                    except (ValueError, KeyError, TypeError):
                        pass

                    hum = None
                    try:
                        hum = float(msg["Humidity"])
                    except (ValueError, KeyError, TypeError):
                        pass

                    try:
                        bat = int(round(float(msg["Battery"])))
                        if (bat < 0) or (bat > 100):
                            bat = 255
                    except (ValueError, KeyError, TypeError):
                        pass

                    try:
                        rss = int(round(float(msg["RSSI"])))
                        rss = int(round((140 + rss) / 10))
                    except (ValueError, KeyError, TypeError):
                        pass

                    Domoticz.Debug("UpdateSensor: Temperature: " + str(temp) + ", Humidity: " + str(hum) + ", Battery level: " + str(bat) + ", RSSI: " + str(rss))

                    if temp != None:
                        updatedevice = True

                        sValue = str(temp) # Always transmit temperature

                        if hum != None:
                            wet = 1
                            if hum >= 70:
                                wet = 3
                            elif hum <= 40:
                                wet = 2

                            sValue = sValue + ";" + str(hum) + ";" + str(wet)


        except (ValueError, KeyError) as e:
            pass

        if updatedevice:
                # Do not update if we got Tasmota periodic state update and state has not changed
                if not isTeleTopic or nValue != device.nValue or sValue != device.sValue:
                    Domoticz.Log( "UpdateSensor: "+ self.deviceStr(self.getUnit(device)) + ": Topic: '" + str(topic) + " 'Setting nValue: " + str(device.nValue) + "->" + str(nValue) + ", sValue: '" + str(device.sValue) + "'->'" + str(sValue) + "'")
                    device.Update(nValue=nValue,sValue=sValue, BatteryLevel=bat, SignalLevel=rss)
                    self.copyDevices()

        return result
# End Sensor support

    def updateSwitch(self, device, topic, message):
        #Domoticz.Debug("updateSwitch topic: '" + topic + "' switchNo: " + str(switchNo) + " key: '" + key + "' message: '" + str(message) + "'")
        nValue = device.nValue #0
        sValue = device.sValue #-1
        isTeleTopic = False # Tasmota tele topic
        updatedevice = False
        updatecolor = False
        try:
            Color = json.loads(device.Color);
        except (ValueError, KeyError, TypeError) as e:
            Color = {}
            pass

        try:
            devicetopics=[]
            configdict = json.loads(device.Options['config'])
            for key, value in configdict.items():
                if value == topic:
                    devicetopics.append(key)
            if ("state_topic" in devicetopics
                or "tasmota_tele_topic" in devicetopics): # Switch status is present in Tasmota tele/STAT message
                if ("state_topic" in devicetopics): Domoticz.Debug("Got state_topic")
                if ("tasmota_tele_topic" in devicetopics): Domoticz.Debug("Got tasmota_tele_topic")
                if ("tasmota_tele_topic" in devicetopics): isTeleTopic = True # Suppress device triggers for periodic tele/STAT message
                if "value_template" in configdict:
                    m = re.match(r"^{{value_json\.(.+)}}$", configdict['value_template'])
                    if m:
                        value_template = m.group(1)
                        Domoticz.Debug("value_template: '" + value_template + "'")
                        if value_template in message:
                            Domoticz.Debug("message[value_template]: '" + message[value_template] + "'")
                            payload = message[value_template]
                            if "payload_off" in configdict and payload == configdict["payload_off"]:
                                updatedevice = True
                                nValue = 0
                            if "payload_on" in configdict and  payload == configdict["payload_on"]:
                                updatedevice = True
                                nValue = 1
                        else:
                            Domoticz.Debug("message[value_template]: '-'")
                    else:
                        Domoticz.Debug("unsupported value_template: '" + configdict['value_template'] + "'")
                else:
                    Domoticz.Debug("No value_template")
                    payload = message
                    if  (("payload_off" in configdict and payload == configdict["payload_off"]) or
                         ("state_open" in configdict and payload == configdict["state_open"]) or
                         "payload_off" not in configdict and "state_open" not in configdict and payload == 'OFF'):
                        updatedevice = True
                        nValue = 0
                    if  (("payload_on" in configdict and payload == configdict["payload_on"]) or
                         ("state_close" in configdict and payload == configdict["state_close"]) or
                         "payload_on" not in configdict and "state_close" not in configdict and payload == 'ON'):
                        updatedevice = True
                        nValue = 1
                    if  (("payload_stop" in configdict and payload == configdict["payload_stop"]) or
                         ("state_stop" in configdict and payload == configdict["state_stop"]) or
                         "payload_stop" not in configdict and "state_stop" not in configdict and payload == 'STOP'):
                        updatedevice = True
                        nValue = 17  # state = STOP  in blinds
                    Domoticz.Debug("nValue: '" + str(nValue) + "'")
            if "brightness_state_topic" in devicetopics:
                Domoticz.Debug("Got brightness_state_topic")
                if "brightness_value_template" in configdict:
                    m = re.match(r"^{{value_json\.(.+)}}$", configdict['brightness_value_template'])
                    if m:
                        brightness_value_template = m.group(1)
                        Domoticz.Debug("brightness_value_template: '" + brightness_value_template + "'")
                        if brightness_value_template in message:
                            Domoticz.Debug("message[brightness_value_template]: '" + str(message[brightness_value_template]) + "'")
                            payload = message[brightness_value_template]
                            brightness_scale = 255
                            if "brightness_scale" in configdict:
                                brightness_scale = configdict['brightness_scale']
                            sValue = payload * 100 / brightness_scale
                        else:
                            Domoticz.Debug("message[brightness_value_template]: '-'")
                    else:
                        Domoticz.Debug("unsupported template: '" + configdict['brightness_value_template'] + "'")
                else:
                    payload = int(message)
                    brightness_scale = 255
                    if "brightness_scale" in configdict:
                        brightness_scale = configdict['brightness_scale']
                    sValue = int(payload * 100 / brightness_scale)
                    Domoticz.Debug("sValue: '" + str(sValue) + "'")
                    updatedevice = True

            if "position_topic" in devicetopics:
                payload = message
                sValue = payload
                nValue = 0
                Domoticz.Log("sValue: '" + str(sValue) + "'")
                updatedevice = True

            if "rgb_state_topic" in devicetopics:
                Domoticz.Debug("Got rgb_state_topic")
                if "rgb_value_template" in configdict:
                    m = re.match(r"^{{value_json\.(.+)}}$", configdict['rgb_value_template'])
                    if m:
                        rgb_value_template = m.group(1)
                        Domoticz.Debug("rgb_value_template: '" + rgb_value_template + "'")
                        if rgb_value_template in message:
                            Domoticz.Debug("message[rgb_value_template]: '" + str(message[rgb_value_template]) + "'")
                            payload = message[rgb_value_template]
                            if len(payload)==6 or len(payload)==8 or len(payload)==10:
                                updatecolor = True
                                # TODO check contents of cw/ww and set mode accordingly
                                Color["m"] = 3 # RGB
                                Color["t"] = 0
                                Color["r"] = int(payload[0:2], 16)
                                Color["g"] = int(payload[2:4], 16)
                                Color["b"] = int(payload[4:6], 16)
                                Color["cw"] = 0
                                Color["ww"] = 0
                                Domoticz.Debug("Color: "+json.dumps(Color))
                        else:
                            Domoticz.Debug("message[rgb_value_template]: '-'")
                    else:
                        Domoticz.Debug("unsupported template: '" + configdict['rgb_value_template'] + "'")
                else:
                    #TODO: test
                    #payload = message
                    #brightness_scale = 255
                    #if "brightness_scale" in configdict:
                    #    brightness_scale = configdict['brightness_scale']
                    #sValue = payload * 100 / brightness_scale
                    Domoticz.Debug("sValue: '" + str(sValue) + "'")
            elif "color_temp_state_topic" in devicetopics:
                Domoticz.Debug("Got color_temp_state_topic")
                if "color_temp_value_template" in configdict:
                    m = re.match(r"^{{value_json\.(.+)}}$", configdict['color_temp_value_template'])
                    if m:
                        color_temp_value_template = m.group(1)
                        Domoticz.Debug("color_temp_value_template: '" + color_temp_value_template + "'")
                        if color_temp_value_template in message:
                            Domoticz.Debug("message[color_temp_value_template]: '" + str(message[color_temp_value_template]) + "'")
                            payload = message[color_temp_value_template]
                            updatecolor = True
                            Color["m"] = 2 # Color temperature
                            Color["t"] = int(255*(int(payload)-153)/(500-153))
                            Domoticz.Debug("Color: "+json.dumps(Color))
                        else:
                            Domoticz.Debug("message[color_temp_value_template]: '-'")
                    else:
                        Domoticz.Debug("unsupported template: '" + configdict['color_temp_value_template'] + "'")
                else:
                    #TODO: test
                    #payload = message
                    #brightness_scale = 255
                    #if "brightness_scale" in configdict:
                    #    brightness_scale = configdict['brightness_scale']
                    #sValue = payload * 100 / brightness_scale
                    Domoticz.Debug("sValue: '" + str(sValue) + "'")
        except (ValueError, KeyError) as e:
            pass

        if updatedevice:
            if updatecolor:
                # Do not update if we got Tasmota periodic state update and state has not changed
                if not isTeleTopic or nValue != device.nValue or sValue != device.sValue:
                    Domoticz.Log(self.deviceStr(self.getUnit(device)) + ": Topic: '" + str(topic) + " 'Setting nValue: " + str(device.nValue) + "->" + str(nValue) + ", sValue: '" + str(device.sValue) + "'->'" + str(sValue) + "', color: '" + device.Color + "'->'" + json.dumps(Color) + "'")
                    device.Update(nValue=nValue, sValue=str(sValue), Color=json.dumps(Color))
                    self.copyDevices()
            else:
                # Do not update if we got Tasmota periodic state update and state has not changed
                if not isTeleTopic or nValue != device.nValue or sValue != device.sValue:
                    Domoticz.Log(self.deviceStr(self.getUnit(device)) + ": Topic: '" + str(topic) + " 'Setting nValue: " + str(device.nValue) + "->" + str(nValue) + ", sValue: '" + str(device.sValue) + "'->'" + str(sValue) + "'")
                    device.Update(nValue=nValue, sValue=str(sValue))
                    self.copyDevices()

    def updateAvailability(self, device, topic, message):
        TimedOut=0
        updatedevice = False

        try:
            devicetopics=[]
            configdict = json.loads(device.Options['config'])
            for key, value in configdict.items():
                if value == topic:
                    devicetopics.append(key)
            if "availability_topic" in devicetopics:
                Domoticz.Debug("Got availability_topic")
                if "availability_template" in configdict:
                    m = re.match(r"^{{value_json\.(.+)}}$", configdict['availability_template'])
                    availability_template = m.group(1)
                    Domoticz.Debug("availability_template: '" + availability_template + "'")
                    if availability_template in message:
                        Domoticz.Debug("message[availability_template]: '" + message[availability_template] + "'")
                        payload = message[availability_template]
                        if payload == configdict["payload_available"]:
                            updatedevice = True
                            TimedOut = 0
                        if payload == configdict["payload_not_available"]:
                            updatedevice = True
                            TimedOut = 1
                        Domoticz.Debug("TimedOut: '" + str(TimedOut) + "'")
                    else:
                        Domoticz.Debug("message[availability_template]: '-'")
                else:
                    payload = message
                    if payload == configdict["payload_available"]:
                        updatedevice = True
                        TimedOut = 0
                    if payload == configdict["payload_not_available"]:
                        updatedevice = True
                        TimedOut = 1
                    Domoticz.Debug("TimedOut: '" + str(TimedOut) + "'")
        except (ValueError, KeyError) as e:
            pass

        if updatedevice:
            nValue = device.nValue
            sValue = device.sValue
            Domoticz.Log(self.deviceStr(self.getUnit(device)) + ": Setting TimedOut: '" + str(TimedOut) + "'")
            device.Update(nValue=nValue, sValue=sValue, TimedOut=TimedOut, SuppressTriggers=True)
            self.copyDevices()

    def updateTasmotaStatus(self, device, topic, message):
        #Domoticz.Debug("updateTasmotaStatus topic: '" + topic + "' message: '" + str(message) + "'")
        nValue = device.nValue
        sValue = device.sValue
        updatedevice = False
        Vcc = 0
        RSSI = 0

        try:
            devicetopics=[]
            configdict = json.loads(device.Options['config'])
            for key, value in configdict.items():
                if value == topic:
                    devicetopics.append(key)
            if "tasmota_tele_topic" in devicetopics:
                Domoticz.Debug("Got tasmota_tele_topic")
                if "Vcc" in message and self.options['updateVCC']:
                    Vcc = int(message["Vcc"]*10)
                    Domoticz.Debug("Set battery level to: " + str(Vcc) + " was:" + str(device.BatteryLevel))
                    updatedevice = True
                if "Wifi" in message and "RSSI" in message["Wifi"] and self.options['updateRSSI']:
                    RSSI = int(message["Wifi"]["RSSI"])
                    Domoticz.Debug("Set SignalLevel to: " + str(RSSI) + " was:" + str(device.SignalLevel))
                    updatedevice = True
            if updatedevice and (device.SignalLevel != RSSI or device.BatteryLevel != Vcc):
                Domoticz.Log(self.deviceStr(self.getUnit(device)) + ": Setting SignalLevel: '" + str(RSSI) + "', BatteryLevel: '" + str(Vcc) + "'")
                device.Update(nValue=nValue, sValue=sValue, SignalLevel=RSSI, BatteryLevel=Vcc, SuppressTriggers=True)
                self.copyDevices()
        except (ValueError, KeyError) as e:
            pass

    def updateTasmotaSettings(self, device, topic, message):
        Domoticz.Debug("updateTasmotaSettings " + self.deviceStr(self.getUnit(device)) + " topic: '" + topic + "' message: '" + str(message) + "'")
        nValue = device.nValue
        sValue = device.sValue
        updatedevice = False
        IPAddress = ""
        Description = ""

        try:
            devicetopics=[]
            configdict = json.loads(device.Options['config'])
            if topic.endswith('STATUS5'):
                if "StatusNET" in message and "IPAddress" in message["StatusNET"]:
                    IPAddress = message["StatusNET"]["IPAddress"]
                    cmnd_topic = re.sub(r"^tele\/", "cmnd/", configdict['tasmota_tele_topic']) # Replace tele with cmnd
                    cmnd_topic = re.sub(r"\/tele\/", "/cmnd/", cmnd_topic) # Replace tele with cmnd
                    cmnd_topic = re.sub(r"\/STATE\d?", "", cmnd_topic) # Remove '/STATE'
                    Description = "IP: " + IPAddress + ", Topic: " + cmnd_topic
                    updatedevice = True
            if updatedevice and (device.Description != Description):
                Domoticz.Log("updateTasmotaSettings updating description from: '" + device.Description + "' to: '" + Description + "'")
                device.Update(nValue=nValue, sValue=sValue, Description=Description, SuppressTriggers=True)
                self.copyDevices()
        except (ValueError, KeyError) as e:
            pass

global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onCommand(Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Color)

def onDeviceAdded(Unit):
    global _plugin
    _plugin.onDeviceAdded(Unit)

def onDeviceModified(Unit):
    global _plugin
    _plugin.onDeviceModified(Unit)

def onDeviceRemoved(Unit):
    global _plugin
    _plugin.onDeviceRemoved(Unit)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Log( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Log("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Log("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Log("Device LastLevel: " + str(Devices[x].LastLevel))
        Domoticz.Log("Device Color:     " + str(Devices[x].Color))
        Domoticz.Log("Device Options:   " + str(Devices[x].Options))
    return

def DumpMQTTMessageToLog(topic, rawmessage, prefix=''):
    message = rawmessage.decode('utf8','replace')
    message = str(message.encode('unicode_escape'))
    Domoticz.Log(prefix+topic+":"+message)
