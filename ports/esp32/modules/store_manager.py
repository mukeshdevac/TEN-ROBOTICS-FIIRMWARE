"""
TEN Robotics - Store Manager & System Lifecycle for ESP32 DevKit V1 (PCB V2)
Integrates Audio Feedback, BLE UART, OLED / TFT Display, and Hardware Lifecycle.
"""

import select
import sys
import uos
import machine
import time
import os
import gc
import micropython
import hardware
from buzzer import buzzer

micropython.alloc_emergency_exception_buf(100)

class BLEStream:
    """Stream wrapper to route print() outputs over BLE Web Serial interface."""
    def __init__(self, manager):
        self.mgr = manager
        self.buffer = bytearray()

    def write(self, data):
        if not data:
            return len(data)
        # Send to standard UART stdout
        try:
            sys.stdout.buffer.write(data)
        except Exception:
            pass
        # Mirror to BLE if connected
        if self.mgr and hasattr(self.mgr, 'send_ble_data'):
            self.mgr.send_ble_data(data)
        return len(data)

    def read(self, n=1):
        return None

    def readinto(self, buf):
        return None


class StoreManager:
    def __init__(self):
        self.header_text     = "TEN ROBOTICS ESP32 V1"
        self.bt_status       = "DISC"
        self.connections     = set()
        self.prog_status     = "STOPPED" # STOPPED, RUNNING
        self.last_error      = None
        self._in_exec        = False
        self.pending_start   = False
        self.exec_start_ticks = 0
        self.is_uploading    = False
        self.last_power_telemetry = 0

        # Audio Startup Sound
        try:
            buzzer.play_startup()
        except Exception as e:
            print("Audio Init Warning:", e)

        # I2C Bus (GPIO 21 SDA, GPIO 22 SCL)
        print("MGR: Initializing I2C Bus (SDA=21, SCL=22)...")
        self.i2c = None
        try:
            self.i2c = machine.I2C(0, sda=machine.Pin(hardware.I2C_SDA), scl=machine.Pin(hardware.I2C_SCL), freq=400000)
            devices = [hex(d) for d in self.i2c.scan()]
            print("MGR: I2C Devices Found:", devices)
        except Exception as e:
            print("MGR: I2C Init Error:", e)

        # Display Initialization (OLED SSD1306/SH1106 or TFT)
        self.display = None
        if self.i2c:
            try:
                import ssd1306
                self.display = ssd1306.SSD1306_I2C(128, 64, self.i2c)
                self.display.fill(0)
                self.display.text("TEN ROBOTICS", 15, 10, 1)
                self.display.text("ESP32 V1 READY", 10, 30, 1)
                self.display.show()
                print("MGR: OLED 1.3\" Display Initialized.")
            except Exception as e:
                print("MGR: Display Init Warning:", e)

        # Touch IDE / UI Controller reference
        self.touch_ide = None
        self.touch = None

        # Setup Dupterm for BLE Print Mirroring
        try:
            self.ble_stream = BLEStream(self)
            uos.dupterm(self.ble_stream)
            print("MGR: BLE Dupterm Output Mirroring Active.")
        except Exception as e:
            print("MGR: Dupterm Init Warning:", e)

        # Serial Poller
        self._poller = select.poll()
        self._poller.register(sys.stdin, select.POLLIN)

    def start(self):
        print("MGR: System Started.")

    def poll_touch(self):
        pass

    def send_ble_data(self, data):
        """Send raw bytes over BLE TX characteristic if active."""
        pass

    def poll_serial(self):
        """Poll incoming serial & BLE commands."""
        events = self._poller.poll(0)
        if events:
            line = sys.stdin.readline().strip()
            if line == "START":
                self.start_prog()
            elif line == "STOP":
                self.stop_prog()

    def poll_power_telemetry(self):
        """Send periodic power telemetry (battery percentage/voltage) every 2s."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_power_telemetry) >= 2000:
            self.last_power_telemetry = now
            try:
                # Read VP / VM voltage sense pin
                adc = machine.ADC(machine.Pin(hardware.SN4))
                raw = adc.read()
                volts = round((raw / 4095.0) * 3.3 * 4.0, 2) # Voltage divider factor
                pct = max(0, min(100, int((volts - 6.0) / (8.4 - 6.0) * 100)))
                telemetry_str = f"POWER:{{\"v\":{volts},\"pct\":{pct}}}\n"
                if self.ble_stream:
                    self.ble_stream.write(telemetry_str.encode())
            except Exception:
                pass

    def start_prog(self):
        self.prog_status = "RUNNING"
        self.exec_start_ticks = time.ticks_ms()
        self._in_exec = True
        buzzer.play_run()
        print(f"MGR: Program Execution Started (Session {self.exec_start_ticks})")

    def stop_prog(self, err=None):
        self.prog_status = "STOPPED"
        self._in_exec = False
        self.last_error = str(err) if err else None
        buzzer.play_stop()
        print("MGR: Program Execution Stopped.")

        # Safety reset for motor PWM outputs
        for pin_num in [hardware.M1_IN1, hardware.M1_IN2, hardware.M2_IN1, hardware.M2_IN2, hardware.M3_IN1, hardware.M3_IN2, hardware.OUT1, hardware.OUT2]:
            try:
                p = machine.PWM(machine.Pin(pin_num))
                p.duty(0)
            except Exception:
                pass

        if self.display and not self.is_uploading:
            try:
                self.display.fill(0)
                self.display.text("TEN ROBOTICS", 15, 10, 1)
                self.display.text("STATUS: STOPPED", 5, 35, 1)
                self.display.show()
            except Exception:
                pass

# Global Singleton Manager instance
manager = StoreManager()

def start():
    if manager:
        manager.start()
