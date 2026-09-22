"""
TEN Robotics DevKit V1 BLE Manager - Nordic UART Service (NUS)
Enables instant Web Bluetooth discovery, full-duplex UART streaming,
live print/console output, upload protocol, and status synchronization.
Website: https://www.tenrobotics.in/
"""

import time
import machine
import os
import gc
from buzzer import buzzer

try:
    import bluetooth
    from micropython import const
except ImportError:
    bluetooth = None
    const = lambda x: x

# Standard Nordic UART Service (NUS) UUIDs (matches Web Bluetooth NUS)
NUS_SERVICE_UUID = bluetooth.UUID("6e400001-b5a3-f393-e0a9-e50e24dcca9e") if bluetooth else None
NUS_RX_CHAR_UUID = bluetooth.UUID("6e400002-b5a3-f393-e0a9-e50e24dcca9e") if bluetooth else None
NUS_TX_CHAR_UUID = bluetooth.UUID("6e400003-b5a3-f393-e0a9-e50e24dcca9e") if bluetooth else None

_IRQ_CENTRAL_CONNECT    = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE        = const(3)

_FLAG_WRITE         = const(0x0008)
_FLAG_WRITE_NO_RESP = const(0x0004)
_FLAG_NOTIFY        = const(0x0010)

def get_mac_suffix():
    """Returns 4 uppercase hex chars from the ESP32 unique ID."""
    try:
        raw = machine.unique_id()
        return f"{raw[-2]:02X}{raw[-1]:02X}"
    except Exception:
        return "V100"

def get_device_name():
    """Returns official TEN Robotics GAP name, e.g. 'TEN_DEVKIT_CA64'."""
    return f"TEN_DEVKIT_{get_mac_suffix()}"

def create_adv_payload(name, services=None):
    """Creates GAP advertising and scan response payloads for standard Web Bluetooth discovery."""
    payload = bytearray()
    payload.extend(b"\x02\x01\x06")  # Flags: General discoverable, no BR/EDR

    # Complete Local Name (0x09)
    name_bytes = name.encode("utf-8")
    payload.append(len(name_bytes) + 1)
    payload.append(0x09)
    payload.extend(name_bytes)

    # Scan Response: 128-bit Complete Service UUIDs (0x07)
    resp = bytearray()
    if services:
        for s in services:
            b = bytes(s)
            resp.append(len(b) + 1)
            resp.append(0x07)
            resp.extend(b)

    return payload, resp


class BLEManager:
    def __init__(self, store_mgr=None):
        self.mgr = store_mgr
        self.ble = None
        self.conn_handle = None
        self.is_connected = False
        self.handle_rx = None
        self.handle_tx = None

        self._rx_buffer = ""
        self.device_name = get_device_name()

        if bluetooth is not None:
            try:
                self.ble = bluetooth.BLE()
                self.ble.active(True)
                self.ble.irq(self._irq_handler)
                self._register_services()
                self.start_advertising()
            except Exception as e:
                print(f"[BLE] Startup error: {e}")

    def _register_services(self):
        service = (
            NUS_SERVICE_UUID,
            (
                (NUS_TX_CHAR_UUID, _FLAG_NOTIFY),
                (NUS_RX_CHAR_UUID, _FLAG_WRITE | _FLAG_WRITE_NO_RESP),
            ),
        )
        ((self.handle_tx, self.handle_rx),) = self.ble.gatts_register_services((service,))

        try:
            # Increase RX buffer size for fast multi-line and code chunk writes
            self.ble.gatts_set_buffer(self.handle_rx, 512, True)
            self.ble.gatts_set_buffer(self.handle_tx, 512, True)
        except Exception:
            pass

    def start_advertising(self):
        if not self.ble:
            return
        adv_payload, resp_payload = create_adv_payload(self.device_name, services=[NUS_SERVICE_UUID])
        try:
            # 100ms advertising interval (160 * 0.625ms = 100,000 us)
            self.ble.gap_advertise(100_000, adv_data=adv_payload, resp_data=resp_payload, connectable=True)
            print(f"[BLE] NUS Advertising active as: {self.device_name}")
            if self.mgr:
                self.mgr.bt_status = "ADV"
        except Exception as e:
            print(f"[BLE] Advertise error: {e}")

    def _irq_handler(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            self.conn_handle = conn_handle
            self.is_connected = True
            print(f"[BLE] Connected! Handle: {conn_handle}")
            buzzer.tone(1800, 40)
            if self.mgr:
                self.mgr.bt_status = "CONN"
                self.mgr.render_active_page()
                # Send immediate connection handshake and status
                self.send_console(f"STATUS:{self.mgr.prog_status}\n")

        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _ = data
            self.conn_handle = None
            self.is_connected = False
            self._rx_buffer = ""
            print("[BLE] Disconnected. Restarting advertising...")
            if self.mgr:
                self.mgr.bt_status = "ADV"
                if self.mgr.is_uploading:
                    self.mgr.is_uploading = False
                self.mgr.render_active_page()
            self.start_advertising()

        elif event == _IRQ_GATTS_WRITE:
            conn_handle, value_handle = data
            if value_handle == self.handle_rx:
                raw = self.ble.gatts_read(self.handle_rx)
                self._handle_rx_data(raw)

    def _handle_rx_data(self, raw_bytes):
        """Processes incoming UART bytes from the Web Bluetooth RX characteristic."""
        try:
            text = bytes(raw_bytes).decode("utf-8")
        except Exception:
            try:
                text = bytes(raw_bytes).decode("latin-1")
            except Exception:
                return

        self._rx_buffer += text

        # Extract complete newline-terminated lines
        while "\n" in self._rx_buffer:
            line, self._rx_buffer = self._rx_buffer.split("\n", 1)
            line = line.strip("\r")
            if self.mgr:
                self.mgr.record_activity()
                self.mgr.process_line(line)

    def send_console(self, text):
        """Sends text or bytes over the NUS TX characteristic notifications to the App."""
        if not self.ble or self.conn_handle is None or not self.handle_tx:
            return
        try:
            payload = text.encode("utf-8") if isinstance(text, str) else text
            # Transmit in safe 20-byte or 64-byte fragments for BLE packet stability
            chunk_size = 20
            for i in range(0, len(payload), chunk_size):
                chunk = payload[i:i + chunk_size]
                self.ble.gatts_notify(self.conn_handle, self.handle_tx, chunk)
                # Brief yield if sending large payloads
                if len(payload) > 64:
                    time.sleep_ms(5)
        except Exception:
            pass

    def stop(self):
        """Deactivates BLE."""
        if self.ble:
            try:
                if self.conn_handle is not None:
                    self.ble.gap_disconnect(self.conn_handle)
                self.ble.active(False)
            except Exception:
                pass
