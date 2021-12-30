# Derived from https://stackoverflow.com/a/66480222

import argparse
import datetime
import struct
import uuid

from gi.repository import GLib
import paho.mqtt.client as mqtt
from pydbus import SystemBus

DEVICE_INTERFACE = 'org.bluez.Device1'

broker_address="10.2.1.30" 
client = mqtt.Client("ha-pi")
client.connect(broker_address)

def stop_scan():
    """Stop device discovery and quit event loop"""
    adapter.StopDiscovery()
    mainloop.quit()


def clean_beacons(remove_list):
    """
    BlueZ D-Bus API does not show duplicates. This is a
    workaround that removes devices that have been found
    during discovery
    """
    not_found = set()
    for rm_dev in remove_list:
        try:
            adapter.RemoveDevice(rm_dev)
        except GLib.Error as err:
            not_found.add(rm_dev)
    for lost in not_found:
        remove_list.remove(lost)


def on_iface_added(owner, path, iface, signal, interfaces_and_properties):
    """
    Event handler for D-Bus interface added.
    Test to see if it is a new Bluetooth device
    """
    iface_path, iface_props = interfaces_and_properties
    if DEVICE_INTERFACE in iface_props:
        on_device_found(iface_path, iface_props[DEVICE_INTERFACE])

def decode_temps(packet_value: int) -> float:
    """Decode potential negative temperatures."""
    # https://github.com/Thrilleratplay/GoveeWatcher/issues/2

    if packet_value & 0x800000:
        return float((packet_value ^ 0x800000) / -10000)
    return float(packet_value / 10000)


def hex_string(data):
        return "".join("{:02x} ".format(x) for x in data)


def on_device_found(device_path, device_props):
    """
    Handle new Bluetooth device being discover.
    If it is a beacon of type iBeacon, Eddystone, AltBeacon
    then process it
    """
    now = datetime.datetime.now()
    remove_list = set()
    address = device_props.get('Address')
    address_type = device_props.get('AddressType')
    name = device_props.get('Name')
    alias = device_props.get('Alias')
    paired = device_props.get('Paired')
    trusted = device_props.get('Trusted')
    rssi = device_props.get('RSSI')
    service_data = device_props.get('ServiceData')
    manufacturer_data = device_props.get('ManufacturerData')
    if manufacturer_data:
        if 60552 in manufacturer_data.keys() and address.casefold() == 'e3:37:3c:61:b4:0f':
            data = manufacturer_data[60552]
            temp, hum, batt = struct.unpack_from("<HHB", bytes(data)[1:])
            data = ",".join(["H5074", now.isoformat(), str(temp / 100), str(hum / 100), str(batt)])
            print(data)
            with open(f"/home/pi/temperatures-{now.date().isoformat()}.csv", "a") as fh:
                fh.write(data + "\n")
            client.publish("home/outside/h5074/temperature", temp / 100)
            client.publish("home/outside/h5074/humidity", hum / 100)
        elif 60552 in manufacturer_data.keys() and address.casefold() == 'a4:c1:38:e5:2f:38':
            data = manufacturer_data[60552]
            data = hex_string(data[1:4]).replace(" ", "")
            temp_hum = int(data, 16)
            temp = decode_temps(temp_hum)
            hum = temp_hum % 1000 / 10
            batt = int(manufacturer_data[60552][4])
            data = ",".join(["H5075", now.isoformat(), str(temp), str(hum), str(batt)])
            print(data)
            with open(f"/home/pi/temperatures-{now.date().isoformat()}.csv", "a") as fh:
                fh.write(data + "\n")
            client.publish("home/inside/h5075/temperature", temp)
            client.publish("home/inside/h5075/humidity", hum)

    remove_list.add(device_path)
    clean_beacons(remove_list)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--duration', type=int, default=0,
                        help='Duration of scan [0 for continuous]')
    args = parser.parse_args()
    bus = SystemBus()
    adapter = bus.get('org.bluez', '/org/bluez/hci0')

    bus.subscribe(iface='org.freedesktop.DBus.ObjectManager',
                  signal='InterfacesAdded',
                  signal_fired=on_iface_added)

    mainloop = GLib.MainLoop()


    if args.duration > 0:
        GLib.timeout_add_seconds(args.duration, stop_scan)
    adapter.SetDiscoveryFilter({'DuplicateData': GLib.Variant.new_boolean(False)})
    adapter.StartDiscovery()

    try:
        print('\n\tUse CTRL-C to stop discovery\n')
        mainloop.run()
    except KeyboardInterrupt:
        stop_scan()
