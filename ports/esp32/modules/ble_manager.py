"""
TEN Robotics DevKit V1 BLE Manager & GATT Protocol Handler
Auto-starts on boot for instant Web Bluetooth pairing, Nordic UART Service (NUS),
closed-loop chunked upload, and real-time console/telemetry streaming.
Website: https://www.tenrobotics.in/
"""

import json
import struct
import time
import machine
import ubinascii
import os
import gc
from buzzer import buzzer

try:
    import bluetooth
    from micropython import const
except ImportError:
    bluetooth = None
    const = lambda x: x

# Standard Nordic UART Service (NUS) UUIDs (universal Web Bluetooth support)
NUS_SERVICE_UUID = bluetooth.UUID("6e400001-b5a3-f393-e0a9-e50e24dcca9e") if bluetooth else None
NUS_CHAR_RX      = bluetooth.UUID("6e400002-b5a3-f393-e0a9-e50e24dcca9e") if bluetooth else None # Write
NUS_CHAR_TX      = bluetooth.UUID("6e400003-b5a3-f393-e0a9-e50e24dcca9e") if bluetooth else None # Notify / Read

# Custom LOF Service & Characteristic UUIDs
LOF_SERVICE_UUID       = bluetooth.UUID("4c4f4600-7469-7461-6e00-000000000001") if bluetooth else None
UUID_CHAR_CONTROL      = bluetooth.UUID("4c4f4601-7469-7461-6e00-000000000001") if bluetooth else None
UUID_CHAR_PROGRAM_DATA = bluetooth.UUID("4c4f4602-7469-7461-6e00-000000000001") if bluetooth else None
UUID_CHAR_STATUS       = bluetooth.UUID("4c4f4603-7469-7461-6e00-000000000001") if bluetooth else None
UUID_CHAR_CONSOLE      = bluetooth.UUID("4c4f4604-7469-7461-6e00-000000000001") if bluetooth else None
UUID_CHAR_DEVICE_INFO  = bluetooth.UUID("4c4f4605-7469-7461-6e00-000000000001") if bluetooth else None

_IRQ_CENTRAL_CONNECT    = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE        = const(3)

_FLAG_READ          = const(0x0002)
_FLAG_WRITE_NO_RESP = const(0x0004)
_FLAG_WRITE         = const(0x0008)
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

def create_adv_payload(name, service_uuid=None):
    """Creates strictly compliant GAP adv payload (<=31 bytes) and scan resp (<=31 bytes)."""
    # 1. Primary Advertising Packet (max 31 bytes)
    payload = bytearray()
    payload.extend(b"\x02\x01\x06") # 3 bytes: Flags (General Discoverable, BR/EDR not supported)

    # Complete Local Name
    n_bytes = name.encode("utf-8")
    payload.append(len(n_bytes) + 1)
    payload.append(0x09) # Complete Local Name
    payload.extend(n_bytes)

    # 2. Scan Response Packet (max 31 bytes)
    resp = bytearray()
    if service_uuid:
        b = bytes(service_uuid)
        resp.append(len(b) + 1)
        resp.append(0x07) # 128-bit Service UUID
        resp.extend(b)

    return payload, resp


import io
import uos

class BLEStream(io.IOBase):
    """Native MicroPython stream wrapper for uos.dupterm to route all stdout over BLE."""
    def __init__(self, ble_mgr):
        self.ble_mgr = ble_mgr

    def write(self, buf):
        if not buf:
            return 0
        if self.ble_mgr and self.ble_mgr.conn_handle is not None:
            try:
                self.ble_mgr.send_console(buf)
            except Exception:
                pass
        return len(buf)

    def readinto(self, buf):
        return None

    def ioctl(self, req, arg):
        if req == 4:  # MP_STREAM_POLL
            return 2  # MP_STREAM_POLL_WR
        return 0

class BLEManager:
    def __init__(self, store_mgr=None):
        self.mgr = store_mgr
        self.ble = None
        self.conn_handle = None
        self.is_connected = False
        self.stream = BLEStream(self)
        
        # NUS Handles
        self.handle_nus_rx = None
        self.handle_nus_tx = None
        
        # LOF Handles
        self.handle_ctrl = None
        self.handle_prog_data = None
        self.handle_status = None
        self.handle_console = None
        self.handle_dev_info = None

        self._control_buffer = ""
        self._nus_rx_buffer = bytearray()
        self.device_name = get_device_name()
        
        # Upload tracking
        self.upload_file = None
        self.upload_expected = 0
        self.upload_received = 0

        # Pre-allocated closures for micropython.schedule (zero heap allocation during BLE IRQs)
        self._sched_nus_rx = lambda raw: self._handle_nus_rx(raw)
        self._sched_ctrl_write = lambda raw: self._handle_control(raw)
        self._sched_prog_data_write = lambda raw: self._handle_prog_data(raw)
        self._sched_start_adv = lambda _: self.start_advertising()

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
        # 1. Nordic UART Service
        nus_service = (
            NUS_SERVICE_UUID,
            (
                (NUS_CHAR_TX, _FLAG_NOTIFY | _FLAG_READ),
                (NUS_CHAR_RX, _FLAG_WRITE | _FLAG_WRITE_NO_RESP),
            ),
        )

        # 2. LOF Service
        lof_service = (
            LOF_SERVICE_UUID,
            (
                (UUID_CHAR_CONTROL, _FLAG_WRITE | _FLAG_NOTIFY),
                (UUID_CHAR_PROGRAM_DATA, _FLAG_WRITE | _FLAG_WRITE_NO_RESP),
                (UUID_CHAR_STATUS, _FLAG_READ | _FLAG_NOTIFY),
                (UUID_CHAR_CONSOLE, _FLAG_NOTIFY),
                (UUID_CHAR_DEVICE_INFO, _FLAG_READ),
            ),
        )

        ((self.handle_nus_tx, self.handle_nus_rx), (self.handle_ctrl, self.handle_prog_data, self.handle_status, self.handle_console, self.handle_dev_info)) = self.ble.gatts_register_services((nus_service, lof_service))

        try:
            self.ble.gatts_set_buffer(self.handle_nus_rx, 1024, True)
            self.ble.gatts_set_buffer(self.handle_nus_tx, 1024, True)
            self.ble.gatts_set_buffer(self.handle_ctrl, 512, True)
            self.ble.gatts_set_buffer(self.handle_prog_data, 512, True)
        except Exception:
            pass

        self.update_device_info()

    def start_advertising(self):
        if not self.ble:
            return
        adv_payload, resp_payload = create_adv_payload(self.device_name, service_uuid=NUS_SERVICE_UUID)
        try:
            # 62.5ms standard advertising interval (100000 us = 100ms) for high reliability
            self.ble.gap_advertise(62500, adv_data=adv_payload, resp_data=resp_payload, connectable=True)
            print(f"[BLE] Advertising active as: {self.device_name} (Payload={len(adv_payload)}B, Resp={len(resp_payload)}B)")
            if self.mgr:
                self.mgr.bt_status = "ADV"
        except Exception as e:
            print(f"[BLE] Advertise error: {e}")

    def _irq_handler(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            self.conn_handle = conn_handle
            self.is_connected = True
            try:
                dupterm_fn = getattr(uos, "dupterm", None) or getattr(sys, "dupterm", None)
                if dupterm_fn:
                    success = False
                    for i in range(3):
                        try:
                            dupterm_fn(self.stream, i)
                            success = True
                            break
                        except Exception:
                            pass
                    if not success:
                        dupterm_fn(self.stream)
            except Exception as e:
                print(f"[BLE] Dupterm attach warning: {e}")
            print(f"[BLE] Connected! Handle: {conn_handle}")
            if self.mgr:
                self.mgr.bt_status = "CONN"
                self.mgr.record_activity()
                self.mgr.render_active_page()
                self.mgr.write_out("STATUS:READY\n")

        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _ = data
            self.conn_handle = None
            self.is_connected = False
            try:
                for i in range(3):
                    try:
                        uos.dupterm(None, i)
                    except Exception:
                        pass
                uos.dupterm(None)
            except Exception:
                pass
            print(f"[BLE] Disconnected. Re-starting advertising...")
            if self.upload_file:
                try:
                    self.upload_file.close()
                except Exception:
                    pass
                self.upload_file = None
            if self.mgr:
                self.mgr.bt_status = "ADV"
                self.mgr.is_uploading = False
                self.mgr.render_active_page()
            import micropython
            if micropython and hasattr(micropython, "schedule"):
                try:
                    micropython.schedule(self._sched_start_adv, 0)
                except Exception:
                    self.start_advertising()
            else:
                self.start_advertising()

        elif event == _IRQ_GATTS_WRITE:
            conn_handle, value_handle = data
            import micropython
            if value_handle == self.handle_nus_rx:
                raw = self.ble.gatts_read(self.handle_nus_rx)
                if micropython and hasattr(micropython, "schedule"):
                    try:
                        micropython.schedule(self._sched_nus_rx, raw)
                    except Exception:
                        self._handle_nus_rx(raw)
                else:
                    self._handle_nus_rx(raw)
            elif value_handle == self.handle_ctrl:
                raw = self.ble.gatts_read(self.handle_ctrl)
                if micropython and hasattr(micropython, "schedule"):
                    try:
                        micropython.schedule(self._sched_ctrl_write, raw)
                    except Exception:
                        self._handle_control(raw)
                else:
                    self._handle_control(raw)
            elif value_handle == self.handle_prog_data:
                raw = self.ble.gatts_read(self.handle_prog_data)
                if micropython and hasattr(micropython, "schedule"):
                    try:
                        micropython.schedule(self._sched_prog_data_write, raw)
                    except Exception:
                        self._handle_prog_data(raw)
                else:
                    self._handle_prog_data(raw)

    def _handle_nus_rx(self, raw_bytes):
        """Processes incoming data on Nordic UART RX stream."""
        if not raw_bytes:
            return
        if self.mgr:
            self.mgr.record_activity()
            self.mgr.ingest_data(raw_bytes, source="BLE")

    def _handle_control(self, raw_bytes):
        try:
            chunk_str = bytes(raw_bytes).decode("utf-8")
            self._control_buffer += chunk_str

            try:
                msg = json.loads(self._control_buffer)
                self._control_buffer = ""
            except Exception:
                if len(self._control_buffer) > 512:
                    self._control_buffer = ""
                return

            cmd = msg.get("cmd", "").upper()
            print(f"[BLE-CMD] {cmd}")

            if cmd == "STATUS":
                st = self.mgr.prog_status if self.mgr else "STOPPED"
                self.send_status({"status": st})

            elif cmd in ("CONNECT", "HELLO"):
                self.send_status({"status": "CONNECTED_READY"})

            elif cmd in ("RUN", "START"):
                try:
                    fsize = os.stat("app.py")[6]
                except Exception:
                    fsize = 0

                if fsize <= 0:
                    if self.mgr:
                        self.mgr.last_error = "NO CODE"
                        buzzer.play_error()
                        self.mgr.render_active_page()
                    self.send_status({"status": "NO_PROGRAM", "message": "No program found (app.py empty)"})
                else:
                    if self.mgr:
                        self.mgr.start_prog()
                    self.send_status({"status": "RUNNING"})

            elif cmd == "STOP":
                if self.mgr:
                    self.mgr.stop_prog()
                self.send_status({"status": "STOPPED"})

            elif cmd == "RESET":
                self.send_status({"status": "RESETTING"})
                machine.reset()

            elif cmd == "PROGRAM":
                filename = msg.get("filename", "app.py")
                size = msg.get("size", 0)
                self.upload_expected = size
                self.upload_received = 0
                if self.upload_file:
                    try: self.upload_file.close()
                    except Exception: pass
                self.upload_file = open(filename, "wb")
                if self.mgr:
                    self.mgr.is_uploading = True
                    if self.mgr.display:
                        try:
                            d = self.mgr.display
                            d.fill(0)
                            d.fill_rect(0, 0, 128, 12, 1)
                            d.text("DOWNLOADING", 20, 2, 0)
                            d.text("WRITING SCRIPT", 8, 22, 1)
                            d.text("0%", 56, 38, 1)
                            d.show()
                        except Exception: pass
                self.send_status({"status": "READY_FOR_DATA"})

            elif cmd == "CHUNK":
                b64 = msg.get("data", "")
                if b64 and self.upload_file:
                    chunk_bytes = ubinascii.a2b_base64(b64)
                    self.upload_file.write(chunk_bytes)
                    self.upload_received += len(chunk_bytes)
                    
                    pct = int(self.upload_received * 100 / max(1, self.upload_expected))
                    if self.mgr and self.mgr.display:
                        try:
                            d = self.mgr.display
                            d.fill(0)
                            d.fill_rect(0, 0, 128, 12, 1)
                            d.text("DOWNLOADING", 20, 2, 0)
                            pct_s = f"{pct}%"
                            px = max(0, (128 - len(pct_s) * 8) // 2)
                            d.text(pct_s, px, 24, 1)
                            d.rect(14, 44, 100, 8, 1)
                            fill_w = int(pct * 96 / 100)
                            if fill_w > 0:
                                d.fill_rect(16, 46, fill_w, 4, 1)
                            d.show()
                        except Exception: pass

                    if self.upload_received >= self.upload_expected:
                        self.upload_file.close()
                        self.upload_file = None
                        if self.mgr:
                            self.mgr.is_uploading = False
                            self.mgr.render_active_page()
                        self.send_status({"status": "PROGRAM_SAVED"})

        except Exception as e:
            print(f"[BLE] Control error: {e}")

    def _handle_prog_data(self, raw_bytes):
        if not self.upload_file or len(raw_bytes) < 2:
            return
        data = raw_bytes[2:] # Strip 2-byte seq prefix
        self.upload_file.write(data)
        self.upload_received += len(data)

        pct = int(self.upload_received * 100 / max(1, self.upload_expected))
        if self.mgr and self.mgr.display:
            try:
                d = self.mgr.display
                d.fill(0)
                d.fill_rect(0, 0, 128, 12, 1)
                d.text("DOWNLOADING", 20, 2, 0)
                pct_s = f"{pct}%"
                px = max(0, (128 - len(pct_s) * 8) // 2)
                d.text(pct_s, px, 24, 1)
                d.rect(14, 44, 100, 8, 1)
                fill_w = int(pct * 96 / 100)
                if fill_w > 0:
                    d.fill_rect(16, 46, fill_w, 4, 1)
                d.show()
            except Exception: pass

        if self.upload_received >= self.upload_expected:
            try: self.upload_file.close()
            except Exception: pass
            self.upload_file = None
            if self.mgr:
                self.mgr.is_uploading = False
                self.mgr.render_active_page()
            self.send_status({"status": "PROGRAM_SAVED"})

    def send_status(self, resp_dict):
        payload = json.dumps(resp_dict).encode("utf-8")
        if self.ble and self.conn_handle is not None:
            try:
                if self.handle_ctrl:
                    self.ble.gatts_notify(self.conn_handle, self.handle_ctrl, payload)
                if self.handle_status:
                    self.ble.gatts_write(self.handle_status, payload)
                    self.ble.gatts_notify(self.conn_handle, self.handle_status, payload)
            except Exception:
                pass

    def send_console(self, text):
        """Sends data bytes reliably over Nordic UART TX characteristic and LOF console characteristic."""
        if not self.ble or self.conn_handle is None:
            return
        try:
            payload = text if isinstance(text, (bytes, bytearray)) else str(text).encode("utf-8")
            for i in range(0, len(payload), 20):
                chunk = payload[i:i+20]
                if self.handle_nus_tx:
                    for _ in range(6):
                        try:
                            self.ble.gatts_notify(self.conn_handle, self.handle_nus_tx, chunk)
                            break
                        except Exception:
                            time.sleep_ms(3)
                if self.handle_console:
                    for _ in range(6):
                        try:
                            self.ble.gatts_notify(self.conn_handle, self.handle_console, chunk)
                            break
                        except Exception:
                            time.sleep_ms(3)
        except Exception:
            pass

    def update_device_info(self):
        if not self.ble or not self.handle_dev_info:
            return
        mac_s = get_mac_suffix()
        info = {
            "product": "TEN ROBOTICS ESP32 DEVKIT V1",
            "device_name": self.device_name,
            "ble_mac": mac_s,
            "device_id": mac_s,
            "flash_mb": 4,
            "psram_mb": 0,
            "firmware": "2.0.0",
            "url": "https://www.tenrobotics.in/",
            "state": "CONNECTED_IDLE",
            "free_ram": gc.mem_free()
        }
        try:
            self.ble.gatts_write(self.handle_dev_info, json.dumps(info).encode("utf-8"))
        except Exception:
            pass
