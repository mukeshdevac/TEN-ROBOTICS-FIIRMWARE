"""
TEN Robotics - Native User Abstraction Library for ESP32 DevKit V1 (PCB V2)
Provides leak-free access to ESP32 DevKit V1 hardware, OLED / TFT Display, Buzzer, and execution state.
"""

import machine
import time
import hardware
from buzzer import buzzer

try:
    import store_manager
except ImportError:
    store_manager = None

# Hardware Pin Map (mirrors hardware.py)
_MOTOR_PINS = {
    1: (hardware.M1_IN1, hardware.M1_IN2),
    2: (hardware.M2_IN1, hardware.M2_IN2),
    3: (hardware.M3_IN1, hardware.M3_IN2),
    4: (hardware.OUT1, hardware.OUT2),
}
_SERVO_PINS  = {1: hardware.S1, 2: hardware.S2}
_SENSOR_PINS = {1: hardware.SN1, 2: hardware.SN2, 3: hardware.SN3, 4: hardware.SN4}

# ─────────────────────────────────────────────────────────────────────────────
# DC Motor Driver
# ─────────────────────────────────────────────────────────────────────────────
class Motor:
    def __init__(self, index):
        pins = _MOTOR_PINS.get(index, _MOTOR_PINS[1])
        try:
            self._in1 = machine.PWM(machine.Pin(pins[0]), freq=1000)
            self._in2 = machine.PWM(machine.Pin(pins[1]), freq=1000)
        except Exception as e:
            print(f"Motor {index} init failed: {e}")
            self._in1 = self._in2 = None

    def drive(self, speed):
        if not self._in1:
            return
        speed = max(-100, min(100, int(speed)))
        duty  = int(abs(speed) / 100 * 1023)
        if speed > 0:
            self._in1.duty(duty)
            self._in2.duty(0)
        elif speed < 0:
            self._in1.duty(0)
            self._in2.duty(duty)
        else:
            self._in1.duty(0)
            self._in2.duty(0)


# ─────────────────────────────────────────────────────────────────────────────
# RC Servo Driver
# ─────────────────────────────────────────────────────────────────────────────
class Servo:
    def __init__(self, index):
        pin_num = _SERVO_PINS.get(index, hardware.S1)
        try:
            self._pwm = machine.PWM(machine.Pin(pin_num), freq=50)
        except Exception as e:
            print(f"Servo {index} init failed: {e}")
            self._pwm = None

    def angle(self, deg):
        if not self._pwm:
            return
        deg = max(0, min(180, int(deg)))
        ns = int(1_000_000 + (deg / 180) * 1_000_000)
        try:
            self._pwm.duty_ns(ns)
        except AttributeError:
            duty = int(1023 * ns / 20_000_000)
            self._pwm.duty(duty)


# ─────────────────────────────────────────────────────────────────────────────
# Analog Sensor Driver
# ─────────────────────────────────────────────────────────────────────────────
class Sensor:
    def __init__(self, index):
        pin_num = _SENSOR_PINS.get(index, hardware.SN1)
        try:
            self._adc = machine.ADC(machine.Pin(pin_num))
            self._adc.atten(machine.ADC.ATTN_11DB)
        except Exception as e:
            print(f"Sensor {index} init failed: {e}")
            self._adc = None

    def read(self):
        if not self._adc:
            return 0
        try:
            return self._adc.read()
        except Exception:
            return 0

    def read_pct(self):
        return int(self.read() * 100 / 4095)


# ─────────────────────────────────────────────────────────────────────────────
# OLED Display Wrapper
# ─────────────────────────────────────────────────────────────────────────────
class DisplayWrapper:
    def __init__(self, display_obj):
        self.oled = display_obj

    def clear(self):
        if self.oled:
            try:
                self.oled.fill(0)
                if hasattr(self.oled, 'show'):
                    self.oled.show()
            except Exception:
                pass

    def text(self, msg, x=0, y=0, color=1):
        if self.oled:
            try:
                self.oled.text(str(msg), x, y, color)
                if hasattr(self.oled, 'show'):
                    self.oled.show()
            except Exception:
                pass

    def emoji(self, name):
        if not self.oled:
            return
        try:
            self.oled.fill(0)
            if name == 'smile':
                self.oled.text(":-)", 45, 25, 1)
            elif name == 'heart':
                self.oled.text("<3", 50, 25, 1)
            else:
                self.oled.text(f"[{name}]", 30, 25, 1)
            if hasattr(self.oled, 'show'):
                self.oled.show()
        except Exception:
            pass


# Physical Button Pins
_btn_start = machine.Pin(hardware.BTN1, machine.Pin.IN, machine.Pin.PULL_UP)
_btn_screen = machine.Pin(hardware.BTN2, machine.Pin.IN, machine.Pin.PULL_UP)

# Initialize global references
if store_manager and store_manager.manager:
    display = DisplayWrapper(store_manager.manager.display)
else:
    display = DisplayWrapper(None)

def is_running():
    """Polls Physical Button (GPIO 16) & serial to safely interrupt execution."""
    # 1. Physical Start/Stop Button check (Active Low)
    if _btn_start.value() == 0:
        buzzer.play_stop()
        raise KeyboardInterrupt("STOPPED_BY_PHYSICAL_BUTTON")
        
    # 2. Store Manager check
    if store_manager and store_manager.manager:
        mgr = store_manager.manager
        if mgr.prog_status != "RUNNING" or not mgr._in_exec:
            buzzer.play_stop()
            raise KeyboardInterrupt("STOPPED_BY_USER")
    return True

def start():
    """Initializes runtime references for user scripts."""
    global display
    if store_manager and store_manager.manager:
        display.oled = store_manager.manager.display

def delay(ms):
    """Interruptible sleep — checks physical stop button and status every 10ms."""
    start_t = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start_t) < ms:
        is_running()
        time.sleep_ms(10)
