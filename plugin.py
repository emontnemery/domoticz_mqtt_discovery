#           MQTT discovery plugin
#
"""
<plugin key="MQTTDiscovery" name="MQTT discovery" version="0.0.2">
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

        <param field="Mode3" label="New devices added as" width="75px">
            <options>
                <option label="Unused" value="0"/>
                <option label="Used" value="1"  default="true" />
            </options>
        </param>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="Verbose" value="Verbose"/>
                <option label="True" value="Debug"/>
                <option label="False" value="Normal"  default="true" />
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
from datetime import datetime
from itertools import count, filterfalse
import json
import re

class MqttClient:
    Address = ""
    Port = ""
    mqttConn = None
    isConnected = False
    mqttConnectedCb = None
    mqttDisconnectedCb = None
    mqttPublishCb = None

    def __init__(self, destination, port, mqttConnectedCb, mqttDisconnectedCb, mqttPublishCb):
        Domoticz.Debug("MqttClient::__init__")
        self.Address = destination
        self.Port = port
        self.mqttConnectedCb = mqttConnectedCb
        self.mqttDisconnectedCb = mqttDisconnectedCb
        self.mqttPublishCb = mqttPublishCb
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
            self.mqttConn.Send({'Verb': 'CONNECT'})

    def Ping(self):
        Domoticz.Debug("MqttClient::Ping")
        if (self.mqttConn == None or not self.isConnected):
            self.Open()
        else:
            self.mqttConn.Send({'Verb': 'PING'})

    def Publish(self, topic, payload):
        Domoticz.Debug("MqttClient::Publish" + topic + " (" + payload + ")")
        if (self.mqttConn == None or not self.isConnected):
            self.Open()
        else:
            self.mqttConn.Send({'Verb': 'PUBLISH', 'Topic': topic, 'Payload': bytearray(payload, 'utf-8')})

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
        Domoticz.Debug("MqttClient::Close")
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
        Domoticz.Debug("MqttClient::onMessage called for connection: '"+Connection.Name+"' type:'"+Data['Verb']+"' topic:'"+topic+"' payload:'" + payloadStr + "'")

        if Data['Verb'] == "CONNACK":
            self.isConnected = True
            if self.mqttConnectedCb != None:
                self.mqttConnectedCb()

        if Data['Verb'] == "SUBACK":
            pass
            # (Re)subscribed, refresh device info
            # TODO: Add specific code to poll tasmota devices
            #for key,Device in Devices.items():
            #    if ("Topic" in Device.Options):
            #        self.refreshConfiguration(Device.Options["Topic"])

        if Data['Verb'] == "PUBLISH":
            message = ""
            try:
                message = json.loads(Data['Payload'].decode('utf8'))
            except ValueError:
                message = Data['Payload'].decode('utf8')
            if self.mqttPublishCb != None:
                self.mqttPublishCb(topic, message)

class BasePlugin:
    mqttClient = None
    mqttserveraddress = ""
    mqttserverport = ""
    nextDev = 0

    def onStart(self):
        if Parameters["Mode6"] != "Normal":
            DumpConfigToLog()
            Domoticz.Debugging(1)
        #Domoticz.Heartbeat(int(Parameters["Mode3"]))
        Domoticz.Heartbeat(10)

        # Connect to MQTT server
        self.mqttserveraddress = Parameters["Address"].replace(" ", "")
        self.mqttserverport = Parameters["Port"].replace(" ", "")
        self.discoverytopic = Parameters["Mode2"]
        self.prefixpos = 0
        self.topicpos = 0
        self.ignoredtopics = Parameters["Mode4"].split(',')
        self.discoverytopiclist = self.discoverytopic.split('/')
        self.mqttClient = MqttClient(self.mqttserveraddress, self.mqttserverport, self.onMQTTConnected, self.onMQTTDisconnected, self.onMQTTPublish)

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

    def onMQTTPublish(self, topic, message):
        topiclist = topic.split('/')
        if Parameters["Mode6"] == "Verbose":
            DumpMQTTMessageToLog(topiclist, message)

        if topic in self.ignoredtopics:
            Domoticz.Debug("Topic: '"+topic+"' included in ignored topics, message ignored")
            return

        if topic.startswith(self.discoverytopic):
            # TODO: Offset with length of self.discoverytopiclist
            devicetype = topiclist[1]
            devicename = topiclist[2]
            action = topiclist[3]
            if action == 'config' and ('command_topic' in message or 'state_topic' in message):
                self.updateDeviceSettings(devicename, devicetype, message)
        else:
            matchingDevices = self.getDevices(topic=topic)
            for device in matchingDevices:
                # Try to update switch state
                self.updateSwitch(device, topic, message)

                # Try to update availability
                self.updateAvailability(device, topic, message)
                # TODO: Availability does nothing for switches.. Can a device be disabled in Domoticz to indicate it is offline?

                # TODO: Try to update sensor
                #self.updateSensor(device, topic, message)

                # TODO: Try to update binary sensor
                #self.updateBinarySensor(device, topic, message)

                # TODO: Try to update tasmota status
                self.updateTasmotaStatus(device, topic, message)


    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug("onCommand Unit: "+str(Unit)+", Command: '"+str(Command)+"', Level: "+str(Level)+", Hue:"+str(Hue));
        iUnit = -1
        for Device in Devices:
            if (Device == Unit):
                iUnit = Device

        if (iUnit > 0):
            Domoticz.Debug("Device found: "+str(iUnit));
            try:
                configdict = json.loads(Devices[iUnit].Options['config'])
                if Command == "Set Brightness" or Command == "Set Level" or (Command == "On" and Level > 0):
                    self.mqttClient.Publish(configdict["brightness_command_topic"],str(Level))
                elif Command == "On":
                    self.mqttClient.Publish(configdict["command_topic"],configdict["payload_on"])
                elif Command == "Off":
                    self.mqttClient.Publish(configdict["command_topic"],configdict["payload_off"])
                #elif Command == "Set Color":
                #    self.mqttClient.Publish(configdict["rgb_command_topic"],"#"+str(Level)) # TODO: Domoticz hue to RGB(WW)
                elif Command == "Set Kelvin Level":
                    self.mqttClient.Publish(configdict["color_temp_command_topic"],str(Level*(500-153)/100+153))
            except (ValueError, KeyError, TypeError) as e:
                Domoticz.Error("getTopics: Error: " + str(e))
        else:
            Domoticz.Debug("Device not found, ignoring command");

    def onDeviceAdded(self, Unit):
        Domoticz.Debug("onDeviceAdded Unit: "+str(Unit));

    def onDeviceModified(self, Unit):
        Domoticz.Debug("onDeviceModified Unit: "+str(Unit));

    def onDeviceRemoved(self, Unit):
        Domoticz.Debug("onDeviceRemoved Unit: "+str(Unit));

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
        self.mqttClient.Publish("tasmota/"+Topic+"/cmnd/Status",'11')
        # Refresh sensor configuration
        self.mqttClient.Publish("tasmota/"+Topic+"/cmnd/Status",'10')
        # Refresh IP configuration
        self.mqttClient.Publish("tasmota/"+Topic+"/cmnd/Status",'5')

    # Returns list of topics to subscribe to
    def getTopics(self):
        topics = set()
        for key,Device in Devices.items():
            #Domoticz.Debug("getTopics: '" + str(Device.Options) +"'")
            try:
                configdict = json.loads(Device.Options['config'])
                #Domoticz.Debug("getTopics: '" + str(configdict) +"'")
                for key, value in configdict.items():
                    #Domoticz.Debug("getTopics: key:'" + key +"' value: '" + value + "'")
                    try:
                        if key.endswith('_topic'):
                            topics.add(value)
                    except (TypeError) as e:
                        Domoticz.Debug("getTopics: Error: " + str(e))
                        pass
            except (ValueError, KeyError, TypeError) as e:
                Domoticz.Debug("getTopics: Error: " + str(e))
                pass
        topics.add(self.discoverytopic+'/#')
        Domoticz.Debug("getTopics: '" + str(topics) +"'")
        return list(topics)

    # Returns list of matching devices
    def getDevices(self, key='', configkey='', value='', config='', topic='', type='', channel=''):
        Domoticz.Debug("getDevices key: '" + key + "' configkey: '" + configkey + "' value: '" + value + "' config: '" + config + "' topic: '" + topic + "'")
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

        Domoticz.Debug("Creating device with unit: " + str(iUnit));

        Options = {'config':json.dumps(config),'devicename':devicename}
        #DeviceName = topic+' - '+type
        DeviceName = config['name']
        Used = 0
        try:
            Used=int(Parameters["Mode3"])
        except (ValueError, KeyError) as e:
            pass
        Domoticz.Device(Name=DeviceName, Unit=iUnit, TypeName=TypeName, Switchtype=switchTypeDomoticz, Options=Options, Used=Used).Create()

    def makeDeviceRaw(self, devicename, Type, Subtype, switchTypeDomoticz, config):
        iUnit = next(filterfalse(set(Devices).__contains__, count(1))) # First unused 'Unit'

        Domoticz.Debug("Creating device with unit: " + str(iUnit));

        Options = {'config':json.dumps(config),'devicename':devicename}
        #DeviceName = topic+' - '+type
        DeviceName = config['name']
        Used = 0
        try:
            Used=int(Parameters["Mode3"])
        except (ValueError, KeyError) as e:
            pass
        Domoticz.Device(Name=DeviceName, Unit=iUnit, Type=Type, Subtype=Subtype, Switchtype=switchTypeDomoticz, Options=Options, Used=Used).Create()

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
        # TODO: Something smarter
        try:
            if "/cmnd/" in config["command_topic"] and "/POWER" in config["command_topic"] and "/tele/" in config["availability_topic"] and "/LWT" in config["availability_topic"]:
                isTasmota = True

            Domoticz.Debug("isTasmota: " + str(isTasmota))
            if isTasmota:
                statetopic = config["availability_topic"].replace("/LWT", "/STATE")
                Domoticz.Debug("statetopic: " + statetopic)
                config['tasmota_tele_topic'] = statetopic
        except (ValueError, KeyError) as e:
            pass

    def updateDeviceSettings(self, devicename, devicetype, config):
        Domoticz.Debug("updateDeviceSettings devicename: '" + devicename + "' devicetype: '" + devicetype + "' config: '" + str(config) + "'")

        TypeName = ''
        Type = 0
        Subtype = 0
        switchTypeDomoticz = 0 # OnOff
        if devicetype == 'switch':
            Domoticz.Debug("devicetype == 'switch'")
            TypeName = 'Switch'
            Type = 0xf4        # pTypeGeneralSwitch
            Subtype = 0x49     # sSwitchGeneralSwitch
        if devicetype == 'light':
            Domoticz.Debug("devicetype == 'light'")
            switchTypeDomoticz = 7 # Dimmer
            rgbww = 0
            if 'color_temp_command_topic' in config:
                rgbww = 2
            if 'rgb_command_topic' in config:
                rgbww = rgbww + 3
            if rgbww == 2:     # WW
                Type = 0xf1    # pTypeLimitlessLights
                Subtype = 0x03 # sTypeLimitlessWhite, maybe not correct..
            elif rgbww == 3:   # RGB
                Type = 0xf1    # pTypeLimitlessLights
                Subtype = 0x02 # sTypeLimitlessRGB
            elif rgbww == 4:   # RGBW TODO: Can't be detected..
                Type = 0xf1    # pTypeLimitlessLights
                Subtype = 0x01 # sTypeLimitlessRGBW
            elif rgbww == 5:   # RGBWW
                Type = 0xf1    # pTypeLimitlessLights
                Subtype = 0x04 # sTypeLimitlessRGBWW
            else:
                TypeName = 'Switch'
                Type = 0xf4    # pTypeGeneralSwitch
                Subtype = 0x49 # sSwitchGeneralSwitch

        matchingDevices = self.getDevices(key='devicename', value=devicename)
        if len(matchingDevices) == 0:
            Domoticz.Debug("updateDeviceSettings: Did not find device with key='devicename', value = '" +  devicename + "'")
            # Unknown device
            Domoticz.Debug("updateDeviceSettings: TypeName: '" + TypeName + "' Type: " + str(Type))
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
            if Type != 0 and (device.Type != Type or device.SubType != Subtype or device.SwitchType != switchTypeDomoticz or oldconfigdict != config):
                Domoticz.Debug("----------------- updateDeviceSettings: Device settings not matching, updating Type, SubType, Switchtype and Options['config']")
                Domoticz.Debug("updateDeviceSettings: device.Type: " + str(device.Type) + "->" + str(Type) + ", device.SubType: " + str(device.SubType) + "->" + str(Subtype) +
                               ", device.SwitchType: " + str(device.SwitchType) + "->" + str(switchTypeDomoticz) +
                               ", device.Options['config']: " + str(oldconfigdict) + " -> " + str(config))
                nValue = device.nValue
                sValue = device.sValue
                Options = dict(device.Options)
                Options['config'] = json.dumps(config)
                device.Update(nValue=nValue, sValue=sValue, Type=Type, Subtype=Subtype, Switchtype=switchTypeDomoticz, Options=Options)

    def updateSwitch(self, device, topic, message):
        #Domoticz.Debug("updateSwitch topic: '" + topic + "' switchNo: " + str(switchNo) + " key: '" + key + "' message: '" + str(message) + "'")
        nValue = device.nValue #0
        sValue = device.sValue #-1
        updatedevice = False

        try:
            devicetopics=[]
            configdict = json.loads(device.Options['config'])
            for key, value in configdict.items():
                if value == topic:
                    devicetopics.append(key)
            if ("state_topic" in devicetopics
                or "tasmota_tele_topic" in devicetopics): # Switch status is present in Tasmota tele/STAT message
                Domoticz.Debug("Got state_topic")
                if "value_template" in configdict:
                    m = re.match(r"^{{value_json\.(.+)}}$", configdict['value_template'])
                    value_template = m.group(1)
                    Domoticz.Debug("value_template: '" + value_template + "'")
                    if value_template in message:
                        Domoticz.Debug("message[value_template]: '" + message[value_template] + "'")
                        payload = message[value_template]
                        if payload == configdict["payload_off"]:
                            updatedevice = True
                            nValue = 0
                        if payload == configdict["payload_on"]:
                            updatedevice = True
                            nValue = 1
                    else:
                        Domoticz.Debug("message[value_template]: '-'")
                else:
                    #TODO: test
                    payload = message
                    if payload == configdict["payload_off"]:
                        updatedevice = True
                        nValue = 0
                    if payload == configdict["payload_on"]:
                        updatedevice = True
                        nValue = 1
                    Domoticz.Debug("nValue: '" + str(nValue) + "'")
            if "brightness_state_topic" in devicetopics:
                Domoticz.Debug("Got brightness_state_topic")
                if "brightness_value_template" in configdict:
                    m = re.match(r"^{{value_json\.(.+)}}$", configdict['brightness_value_template'])
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
                    #TODO: test
                    payload = message
                    brightness_scale = 255
                    if "brightness_scale" in configdict:
                        brightness_scale = configdict['brightness_scale']
                    sValue = payload * 100 / brightness_scale

                    Domoticz.Debug("sValue: '" + str(sValue) + "'")

        except (ValueError, KeyError) as e:
            pass

        if updatedevice:
            device.Update(nValue=nValue, sValue=str(sValue))

    def updateAvailability(self, device, topic, message):
        #Not working for switches, only for sensors?
        #Domoticz.Debug("updateAvailability topic: '" + topic + "' message: '" + str(message) + "'")
        TimedOut=0
        updatedevice = False

        try:
            devicetopics=[]
            configdict = json.loads(device.Options['config'])
            for key, value in configdict.items():
                if value == topic:
                    devicetopics.append(key)
            if "availability_topic" in devicetopics:
                Domoticz.Debug("Got state_topic")
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
            device.Update(nValue=nValue, sValue=sValue, TimedOut=TimedOut)

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
                if "Vcc" in message:
                    Vcc = int(message["Vcc"]*10)
                    Domoticz.Debug("Set battery level to: " + str(Vcc))
                    updatedevice = True
                if "Wifi" in message and "RSSI" in message["Wifi"]:
                    RSSI = int(message["Wifi"]["RSSI"])
                    Domoticz.Debug("Set SignalLevel to: " + str(RSSI))
                    updatedevice = True
            if updatedevice:
                device.Update(nValue=nValue, sValue=sValue, SignalLevel=RSSI, BatteryLevel=Vcc)
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

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

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
        Domoticz.Log("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Log("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Log("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Log("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Log("Device LastLevel: " + str(Devices[x].LastLevel))
        Domoticz.Log("Device Options:   " + str(Devices[x].Options))
    return

def DumpMQTTMessageToLog(topic, message):
    #Domoticz.Log(topic+":"+message)
    Domoticz.Log('/'.join(topic))
