"""
TEN Robotics - Native User Abstraction Library for ESP32 DevKit V1 (PCB V2)
Provides hardware drivers for Motors, Servos, Stepper, Outputs, Sensors,
I2C devices, OLED Display, Buzzer, Battery Telemetry, and Cooperative Abort.
Website: https://www.tenrobotics.in/
"""

import machine
import time
import math
import hardware
from buzzer import buzzer

try:
    import store_manager
except ImportError:
    store_manager = None

# Hardware Pin Mappings
_MOTOR_PINS = {
    1: (hardware.M1_IN1, hardware.M1_IN2),
    2: (hardware.M2_IN1, hardware.M2_IN2),
    3: (hardware.M3_IN1, hardware.M3_IN2),
    4: (hardware.OUT1, hardware.OUT2),
}
_SERVO_PINS  = {1: hardware.S1, 2: hardware.S2, 3: hardware.BUZZER_PIN}
_OUTPUT_PINS = {1: hardware.OUT1, 2: hardware.OUT2}
_SENSOR_PINS = {1: hardware.SN1, 2: hardware.SN2, 3: hardware.SN3, 4: hardware.SN4}

# Global shared I2C bus (SDA=21, SCL=22)
_shared_i2c = None

def get_i2c():
    global _shared_i2c
    if _shared_i2c is None:
        try:
            _shared_i2c = machine.I2C(0, sda=machine.Pin(hardware.I2C_SDA), scl=machine.Pin(hardware.I2C_SCL), freq=400000)
        except Exception:
            try:
                _shared_i2c = machine.SoftI2C(sda=machine.Pin(hardware.I2C_SDA), scl=machine.Pin(hardware.I2C_SCL))
            except Exception:
                pass
    return _shared_i2c


# ─────────────────────────────────────────────────────────────────────────────
# DC Motor Driver (DRV8833 Dual H-Bridge)
# ─────────────────────────────────────────────────────────────────────────────
class Motor:
    def __init__(self, index):
        self.index = index
        pins = _MOTOR_PINS.get(index, _MOTOR_PINS[1])
        try:
            self._in1 = machine.PWM(machine.Pin(pins[0]), freq=1000)
            self._in2 = machine.PWM(machine.Pin(pins[1]), freq=1000)
        except Exception as e:
            print(f"Motor {index} init error: {e}")
            self._in1 = self._in2 = None

    def drive(self, speed):
        if not self._in1 or not self._in2:
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
            self.stop()

    def stop(self):
        if self._in1 and self._in2:
            self._in1.duty(0)
            self._in2.duty(0)

    def forward(self, speed=100):
        self.drive(abs(speed))

    def backward(self, speed=100):
        self.drive(-abs(speed))


# ─────────────────────────────────────────────────────────────────────────────
# Single-Direction Outputs (OUT1 / OUT2)
# ─────────────────────────────────────────────────────────────────────────────
class Output:
    def __init__(self, index):
        pin_num = _OUTPUT_PINS.get(index, hardware.OUT1)
        try:
            self._pwm = machine.PWM(machine.Pin(pin_num), freq=1000)
        except Exception:
            self._pwm = None

    def run(self, speed):
        if not self._pwm:
            return
        speed = max(0, min(100, int(speed)))
        self._pwm.duty(int(speed * 1023 / 100))

    def stop(self):
        if self._pwm:
            self._pwm.duty(0)

    def set(self, val):
        self.run(100 if val else 0)


# ─────────────────────────────────────────────────────────────────────────────
# RC Servo Driver (180° Positional & 360° Continuous)
# ─────────────────────────────────────────────────────────────────────────────
class Servo:
    def __init__(self, index):
        self.index = index
        self.curr_angle = 90
        pin_num = _SERVO_PINS.get(index, hardware.S1)
        try:
            self._pwm = machine.PWM(machine.Pin(pin_num), freq=50)
        except Exception as e:
            print(f"Servo {index} init error: {e}")
            self._pwm = None

    def angle(self, deg):
        if not self._pwm:
            return
        deg = max(0, min(180, int(deg)))
        self.curr_angle = deg
        ns = int(1_000_000 + (deg / 180) * 1_000_000)
        try:
            self._pwm.duty_ns(ns)
        except AttributeError:
            duty = int(1023 * ns / 20_000_000)
            self._pwm.duty(duty)

    def center(self):
        self.angle(90)

    def step(self, delta):
        self.angle(self.curr_angle + delta)

    def sweep(self, start, end, step_deg=5, delay_ms=20):
        step_deg = max(1, abs(step_deg))
        direction = 1 if end >= start else -1
        for a in range(start, end + direction, direction * step_deg):
            if not is_running():
                break
            self.angle(a)
            time.sleep_ms(delay_ms)

    def speed(self, spd, direction="CW"):
        """For 360° continuous servos: 0-100 speed in CW or CCW direction."""
        if not self._pwm:
            return
        spd = max(0, min(100, int(spd)))
        if spd == 0 or direction == "STOP":
            self.angle(90)
        elif direction == "CW":
            self.angle(int(90 + (spd / 100.0) * 90))
        else:
            self.angle(int(90 - (spd / 100.0) * 90))


# ─────────────────────────────────────────────────────────────────────────────
# 4-Wire Stepper Motor Driver (M3_IN1, M3_IN2, OUT1, OUT2)
# ─────────────────────────────────────────────────────────────────────────────
class Stepper:
    _STEPS = [
        (1, 0, 1, 0),
        (0, 1, 1, 0),
        (0, 1, 0, 1),
        (1, 0, 0, 1),
    ]

    def __init__(self):
        try:
            self._p1 = machine.Pin(hardware.M3_IN1, machine.Pin.OUT)
            self._p2 = machine.Pin(hardware.M3_IN2, machine.Pin.OUT)
            self._p3 = machine.Pin(hardware.OUT1, machine.Pin.OUT)
            self._p4 = machine.Pin(hardware.OUT2, machine.Pin.OUT)
            self.release()
        except Exception as e:
            print("Stepper init error:", e)
            self._p1 = self._p2 = self._p3 = self._p4 = None

    def step(self, steps, delay_ms=10):
        if not self._p1:
            return
        delay_ms = max(1, int(delay_ms))
        direction = 1 if steps >= 0 else -1
        total = abs(int(steps))
        for i in range(total):
            if not is_running():
                break
            s = self._STEPS[(i * direction) % 4]
            self._p1.value(s[0])
            self._p2.value(s[1])
            self._p3.value(s[2])
            self._p4.value(s[3])
            time.sleep_ms(delay_ms)

    def move_degrees(self, degrees, delay_ms=10):
        # Standard 1.8° per step (200 steps per 360° revolution)
        steps = int(degrees / 1.8)
        self.step(steps, delay_ms)

    def release(self):
        if self._p1:
            self._p1.value(0)
            self._p2.value(0)
            self._p3.value(0)
            self._p4.value(0)


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
            print(f"Sensor {index} init error: {e}")
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
# OLED Display Wrapper (Clean formatting & auto-scroll)
# ─────────────────────────────────────────────────────────────────────────────
class DisplayWrapper:
    def __init__(self, display_obj):
        self.oled = display_obj
        self._cursor_y = 0

    def clear(self):
        if self.oled:
            try:
                self.oled.fill(0)
                self._cursor_y = 0
            except Exception:
                pass

    def show(self):
        if self.oled and hasattr(self.oled, 'show'):
            try:
                self.oled.show()
            except Exception:
                pass

    def text(self, msg, x=0, y=0, color=1):
        if self.oled:
            try:
                self.oled.text(str(msg), int(x), int(y), int(color))
            except Exception:
                pass

    def print(self, msg, y=None, size=1):
        if not self.oled:
            return
        try:
            msg_str = str(msg)
            if y is not None:
                py = int(y)
            else:
                py = self._cursor_y
                self._cursor_y = (self._cursor_y + 10) % 60
            self.oled.fill_rect(0, py, 128, 10, 0)
            self.oled.text(msg_str, 0, py, 1)
        except Exception:
            pass

    def big_print(self, val, scale=6):
        if not self.oled:
            return
        try:
            self.oled.fill(0)
            self.oled.text(str(val), 20, 24, 1)
            self.show()
        except Exception:
            pass

    def emoji(self, name):
        if not self.oled:
            return
        try:
            self.oled.fill(0)
            if name == 'smile':
                self.oled.text(":-)", 48, 26, 1)
            elif name == 'heart':
                self.oled.text("<3", 52, 26, 1)
            else:
                self.oled.text(f"[{name}]", 30, 26, 1)
            self.show()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# I2C Protocol Utilities
# ─────────────────────────────────────────────────────────────────────────────
def i2c_scan():
    i2c = get_i2c()
    return i2c.scan() if i2c else []

def i2c_read(addr, reg, nbytes=1):
    i2c = get_i2c()
    if not i2c:
        return 0
    try:
        data = i2c.readfrom_mem(addr, reg, nbytes)
        if nbytes == 1:
            return data[0]
        elif nbytes == 2:
            return (data[0] << 8) | data[1]
        return list(data)
    except Exception:
        return 0

def i2c_write(addr, reg, value):
    i2c = get_i2c()
    if not i2c:
        return
    try:
        val_bytes = bytes([value]) if isinstance(value, int) else bytes(value)
        i2c.writeto_mem(addr, reg, val_bytes)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Power Telemetry Helpers (Syncs with DevKit INA219 / ADC)
# ─────────────────────────────────────────────────────────────────────────────
def battery_pct():
    if store_manager and store_manager.manager:
        return store_manager.manager.last_pct
    return 80

def voltage():
    if store_manager and store_manager.manager:
        return store_manager.manager.last_volts
    return 7.4

def current():
    if store_manager and store_manager.manager:
        return store_manager.manager.last_ma
    return 0.0

def power():
    return round(abs(voltage() * current()), 1)


# ─────────────────────────────────────────────────────────────────────────────
# Cooperative Execution & Physical Button Polling
# ─────────────────────────────────────────────────────────────────────────────
_btn_start = machine.Pin(hardware.BTN1, machine.Pin.IN, machine.Pin.PULL_UP)
_btn_screen = machine.Pin(hardware.BTN2, machine.Pin.IN, machine.Pin.PULL_UP)

# Global display reference for user scripts
if store_manager and store_manager.manager:
    display = DisplayWrapper(store_manager.manager.display)
else:
    display = DisplayWrapper(None)

def is_running():
    """Polls Physical Button (GPIO 16) & StoreManager to safely interrupt execution."""
    # 1. Physical Start/Stop Button check (Active Low)
    if _btn_start.value() == 0 or _btn_screen.value() == 0:
        buzzer.play_stop()
        raise KeyboardInterrupt("STOPPED_BY_PHYSICAL_BUTTON")

    # 2. Store Manager status check
    if store_manager and store_manager.manager:
        mgr = store_manager.manager
        if mgr.prog_status != "RUNNING" or not mgr._in_exec:
            buzzer.play_stop()
            raise KeyboardInterrupt("STOPPED_BY_USER")
    return True

def start():
    """Initializes runtime references before app.py exec."""
    global display
    if store_manager and store_manager.manager:
        display.oled = store_manager.manager.display

def delay(ms):
    """Interruptible sleep — checks physical stop button and status every 10ms."""
    start_t = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start_t) < ms:
        is_running()
        time.sleep_ms(10)
