#!/usr/bin/env python3
"""
BLE UART Service for Raspberry Pi Zero W - Bridge to Direwolf
Implements BLE KISS TNC service for RadioMail and bridges to Direwolf's /tmp/kisstnc
No pairing required
"""

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib
import array
import os
import sys
import threading
import time
import subprocess

# RadioMail BLE KISS TNC UUIDs
UART_SERVICE_UUID = '00000001-ba2a-46c9-ae49-01b0961f68bb'
UART_RX_CHAR_UUID = '00000002-ba2a-46c9-ae49-01b0961f68bb'
UART_TX_CHAR_UUID = '00000003-ba2a-46c9-ae49-01b0961f68bb'

BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
GATT_DESC_IFACE = 'org.bluez.GattDescriptor1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'

# Direwolf KISS TNC path
KISSTNC_PATH = '/tmp/kisstnc'


class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'


class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.bluez.Error.NotSupported'


class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()
                descs = chrc.get_descriptors()
                for desc in descs:
                    response[desc.get_path()] = desc.get_properties()
        return response


class Service(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/service'

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(
                    self.get_characteristic_paths(),
                    signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self):
        result = []
        for chrc in self.characteristics:
            result.append(chrc.get_path())
        return result

    def get_characteristics(self):
        return self.characteristics


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.descriptors = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
                'Descriptors': dbus.Array(
                    self.get_descriptor_paths(),
                    signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_descriptor(self, descriptor):
        self.descriptors.append(descriptor)

    def get_descriptor_paths(self):
        result = []
        for desc in self.descriptors:
            result.append(desc.get_path())
        return result

    def get_descriptors(self):
        return self.descriptors

    @dbus.service.method(GATT_CHRC_IFACE,
                         in_signature='a{sv}',
                         out_signature='ay')
    def ReadValue(self, options):
        print('Default ReadValue called, returning error')
        raise NotSupportedException()

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        print('Default WriteValue called, returning error')
        raise NotSupportedException()

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        print('Default StartNotify called, returning error')
        raise NotSupportedException()

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        print('Default StopNotify called, returning error')
        raise NotSupportedException()

    @dbus.service.signal(DBUS_PROP_IFACE,
                         signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class Descriptor(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, characteristic):
        self.path = characteristic.path + '/desc' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.chrc = characteristic
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_DESC_IFACE: {
                'Characteristic': self.chrc.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(GATT_DESC_IFACE,
                         in_signature='a{sv}',
                         out_signature='ay')
    def ReadValue(self, options):
        print('Default ReadValue called, returning error')
        raise NotSupportedException()

    @dbus.service.method(GATT_DESC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        print('Default WriteValue called, returning error')
        raise NotSupportedException()


class DirewolfBridge:
    """Bridge between Direwolf KISS TNC and BLE UART"""
    def __init__(self, tx_characteristic, kisstnc_path=KISSTNC_PATH):
        self.tx_char = tx_characteristic
        self.kisstnc_path = kisstnc_path
        self.kiss_fd = None
        self.running = False
        self.read_thread = None
        
    def start(self):
        """Connect to Direwolf's KISS TNC"""
        # Wait for Direwolf to create the kisstnc link
        print(f'Waiting for Direwolf KISS TNC at {self.kisstnc_path}...')
        retry_count = 0
        while not os.path.exists(self.kisstnc_path) and retry_count < 30:
            time.sleep(1)
            retry_count += 1
            if retry_count % 5 == 0:
                print(f'Still waiting for {self.kisstnc_path}... ({retry_count}s)')
        
        if not os.path.exists(self.kisstnc_path):
            print(f'ERROR: {self.kisstnc_path} not found!')
            print('Please start Direwolf first with KISS enabled.')
            print('Example: direwolf -p -t 0')
            return False
        
        try:
            # Open the KISS TNC device
            self.kiss_fd = os.open(self.kisstnc_path, os.O_RDWR | os.O_NONBLOCK)
            print(f'\n=== Connected to Direwolf ===')
            print(f'KISS TNC: {self.kisstnc_path}')
            print(f'============================\n')
            
            # Start reading thread
            self.running = True
            self.read_thread = threading.Thread(target=self._read_from_direwolf, daemon=True)
            self.read_thread.start()
            return True
            
        except Exception as e:
            print(f'Error opening KISS TNC: {e}')
            return False
        
    def stop(self):
        """Stop bridge"""
        self.running = False
        if self.read_thread:
            self.read_thread.join(timeout=1)
        if self.kiss_fd is not None:
            os.close(self.kiss_fd)
            self.kiss_fd = None
            
    def _read_from_direwolf(self):
        """Read data from Direwolf and send via BLE"""
        while self.running:
            try:
                data = os.read(self.kiss_fd, 1024)
                if data:
                    print(f'Direwolf -> BLE: {len(data)} bytes')
                    self.tx_char.send_data(data)
            except OSError:
                # No data available (non-blocking read)
                pass
            except Exception as e:
                print(f'Error reading from Direwolf: {e}')
                if not self.running:
                    break
            
            # Small delay to prevent CPU spinning
            time.sleep(0.01)
    
    def write_to_direwolf(self, data):
        """Write data from BLE to Direwolf"""
        if self.kiss_fd is not None:
            try:
                os.write(self.kiss_fd, data)
                print(f'BLE -> Direwolf: {len(data)} bytes')
            except Exception as e:
                print(f'Error writing to Direwolf: {e}')


class UartService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, UART_SERVICE_UUID, True)
        self.tx_char = TxCharacteristic(bus, 0, self)
        self.rx_char = RxCharacteristic(bus, 1, self)
        self.add_characteristic(self.tx_char)
        self.add_characteristic(self.rx_char)
        
        # Create Direwolf bridge
        self.direwolf_bridge = DirewolfBridge(self.tx_char)
        
        # Link RX characteristic to bridge
        self.rx_char.set_direwolf_bridge(self.direwolf_bridge)


class TxCharacteristic(Characteristic):
    """
    TX Characteristic - sends data to the client via notifications
    """
    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index,
            UART_TX_CHAR_UUID,
            ['notify'],
            service)
        self.notifying = False

    def send_data(self, data):
        """Send data to connected client"""
        if not self.notifying:
            return
        
        # Convert string to byte array
        if isinstance(data, str):
            data = data.encode('utf-8')
        
        # Split large packets into smaller chunks (BLE MTU consideration)
        # Most BLE devices support 20-byte notifications by default
        chunk_size = 20
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i+chunk_size]
            value = []
            for byte in chunk:
                value.append(dbus.Byte(byte))
            self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])
            # Small delay between chunks to avoid overwhelming the BLE stack
            time.sleep(0.01)

    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        print('RadioMail connected - notifications enabled')

    def StopNotify(self):
        if not self.notifying:
            return
        self.notifying = False
        print('RadioMail disconnected - notifications disabled')


class RxCharacteristic(Characteristic):
    """
    RX Characteristic - receives data from the client via write
    """
    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index,
            UART_RX_CHAR_UUID,
            ['write', 'write-without-response'],
            service)
        self.direwolf_bridge = None
        
    def set_direwolf_bridge(self, bridge):
        """Set the Direwolf bridge for forwarding data"""
        self.direwolf_bridge = bridge

    def WriteValue(self, value, options):
        # Convert byte array to bytes
        data = bytes(value)
        
        # Forward to Direwolf
        if self.direwolf_bridge:
            self.direwolf_bridge.write_to_direwolf(data)


class Advertisement(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/advertisement'

    def __init__(self, bus, index, advertising_type):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = None
        self.manufacturer_data = None
        self.solicit_uuids = None
        self.service_data = None
        self.local_name = 'RPi-KISS-TNC'
        self.include_tx_power = False
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = self.ad_type
        if self.service_uuids is not None:
            properties['ServiceUUIDs'] = dbus.Array(self.service_uuids,
                                                     signature='s')
        if self.solicit_uuids is not None:
            properties['SolicitUUIDs'] = dbus.Array(self.solicit_uuids,
                                                     signature='s')
        if self.manufacturer_data is not None:
            properties['ManufacturerData'] = dbus.Dictionary(
                self.manufacturer_data, signature='qv')
        if self.service_data is not None:
            properties['ServiceData'] = dbus.Dictionary(self.service_data,
                                                        signature='sv')
        if self.local_name is not None:
            properties['LocalName'] = dbus.String(self.local_name)
        if self.include_tx_power:
            properties['IncludeTxPower'] = dbus.Boolean(self.include_tx_power)
        return {LE_ADVERTISEMENT_IFACE: properties}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE,
                         in_signature='s',
                         out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]

    @dbus.service.method(LE_ADVERTISEMENT_IFACE,
                         in_signature='',
                         out_signature='')
    def Release(self):
        print(f'{self.path}: Released!')


class UartAdvertisement(Advertisement):
    def __init__(self, bus, index):
        Advertisement.__init__(self, bus, index, 'peripheral')
        self.add_service_uuid(UART_SERVICE_UUID)
        self.add_local_name('RPi-KISS-TNC')
        self.include_tx_power = True

    def add_service_uuid(self, uuid):
        if not self.service_uuids:
            self.service_uuids = []
        self.service_uuids.append(uuid)

    def add_local_name(self, name):
        self.local_name = dbus.String(name)


def configure_bluetooth_no_pairing():
    """Configure Bluetooth to not require pairing"""
    try:
        # Set pairable off
        subprocess.run(['bluetoothctl', 'pairable', 'off'], 
                      capture_output=True, timeout=5)
        print('Bluetooth pairing disabled')
    except Exception as e:
        print(f'Warning: Could not disable pairing via bluetoothctl: {e}')


def register_app_cb():
    print('GATT application registered')


def register_app_error_cb(error):
    print(f'Failed to register application: {error}')
    mainloop.quit()


def register_ad_cb():
    print('Advertisement registered')


def register_ad_error_cb(error):
    print(f'Failed to register advertisement: {error}')
    mainloop.quit()


def find_adapter(bus):
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'),
                                DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()

    for o, props in objects.items():
        if GATT_MANAGER_IFACE in props.keys():
            return o

    return None


def set_adapter_properties(bus, adapter_path):
    """Set adapter properties to disable pairing"""
    try:
        adapter = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, adapter_path),
            DBUS_PROP_IFACE
        )
        
        # Set pairable to false
        adapter.Set('org.bluez.Adapter1', 'Pairable', dbus.Boolean(False))
        print('Adapter set to non-pairable mode')
        
    except Exception as e:
        print(f'Warning: Could not set adapter properties: {e}')


def main():
    global mainloop

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SystemBus()

    adapter = find_adapter(bus)
    if not adapter:
        print('BLE adapter not found')
        return

    print(f'Using adapter: {adapter}')

    # Disable pairing requirements
    configure_bluetooth_no_pairing()
    set_adapter_properties(bus, adapter)

    # Create application
    app = Application(bus)
    uart_service = UartService(bus, 0)
    app.add_service(uart_service)

    # Register GATT application
    service_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter),
        GATT_MANAGER_IFACE)
    
    service_manager.RegisterApplication(app.get_path(), {},
                                        reply_handler=register_app_cb,
                                        error_handler=register_app_error_cb)

    # Register advertisement
    ad_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter),
                                 LE_ADVERTISING_MANAGER_IFACE)
    
    advertisement = UartAdvertisement(bus, 0)
    ad_manager.RegisterAdvertisement(advertisement.get_path(), {},
                                     reply_handler=register_ad_cb,
                                     error_handler=register_ad_error_cb)

    # Connect to Direwolf
    if not uart_service.direwolf_bridge.start():
        print('Failed to connect to Direwolf. Exiting.')
        return

    mainloop = GLib.MainLoop()
    
    print('\n=== BLE KISS TNC Bridge Running ===')
    print('Device name: RPi-KISS-TNC')
    print('Pairing: DISABLED - devices can connect directly')
    print('Ready for RadioMail connection')
    print('Press Ctrl+C to quit\n')
    
    try:
        mainloop.run()
    except KeyboardInterrupt:
        print('\nShutting down...')
        uart_service.direwolf_bridge.stop()


if __name__ == '__main__':
    main()

