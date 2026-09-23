"""
TEN Robotics - Native User Abstraction Library for ESP32 DevKit V1 (PCB V2)
Provides leak-free access to ESP32 DevKit V1 hardware, OLED Display, Stepper, Servos, Buzzer, I2C, Sensors, and Execution State.
Website: https://www.tenrobotics.in/
"""

import sys
import machine
import time
import hardware
from buzzer import buzzer

try:
    import store_manager
except ImportError:
    store_manager = None

try:
    import eyes
    sys.modules['ten_eyes'] = eyes
except Exception:
    pass

# Hardware Pin Map (mirrors hardware.py)
_MOTOR_PINS = {
    1: (hardware.M1_IN1, hardware.M1_IN2),
    2: (hardware.M2_IN1, hardware.M2_IN2),
    3: (hardware.M3_IN1, hardware.M3_IN2),
}

_OUTPUT_PINS = {
    1: hardware.OUT1,
    2: hardware.OUT2,
}

_SERVO_PINS  = {1: hardware.S1, 2: hardware.S2, 3: getattr(hardware, 'S3', 33)}
_SENSOR_PINS = {1: hardware.SN1, 2: hardware.SN2, 3: hardware.SN3, 4: hardware.SN4}

# ─────────────────────────────────────────────────────────────────────────────
# DC Motor Driver (Bidirectional via DRV8833)
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
            self._in1.duty(0)
            self._in2.duty(0)

    def stop(self):
        self.drive(0)

    def brake(self):
        if self._in1 and self._in2:
            self._in1.duty(1023)
            self._in2.duty(1023)

    def deinit(self):
        if self._in1:
            try: self._in1.deinit()
            except Exception: pass
        if self._in2:
            try: self._in2.deinit()
            except Exception: pass


# ─────────────────────────────────────────────────────────────────────────────
# Output Channel Driver (Single-direction OUT1, OUT2)
# ─────────────────────────────────────────────────────────────────────────────
class Output:
    def __init__(self, index: int):
        pin_num = _OUTPUT_PINS.get(index, _OUTPUT_PINS[1])
        try:
            self._pwm = machine.PWM(machine.Pin(pin_num), freq=1000)
        except Exception as e:
            print(f"Output {index} init failed: {e}")
            self._pwm = None

    def run(self, speed: int = 100):
        if not self._pwm:
            return
        speed = max(0, min(100, int(speed)))
        self._pwm.duty(int(speed / 100 * 1023))

    def stop(self):
        if self._pwm:
            self._pwm.duty(0)

    def deinit(self):
        if self._pwm:
            try: self._pwm.deinit()
            except Exception: pass


# ─────────────────────────────────────────────────────────────────────────────
# RC Servo Driver (180° Positional & 360° Continuous)
# ─────────────────────────────────────────────────────────────────────────────
class Servo:
    def __init__(self, index):
        pin_num = _SERVO_PINS.get(index, hardware.S1)
        self.curr_angle = 90
        try:
            self._pwm = machine.PWM(machine.Pin(pin_num), freq=50)
        except Exception as e:
            print(f"Servo {index} init failed: {e}")
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

    def sweep(self, start_deg=0, end_deg=180, step_deg=5, delay_ms=20):
        step_dir = step_deg if end_deg >= start_deg else -step_deg
        for a in range(start_deg, end_deg + (1 if step_dir > 0 else -1), step_dir):
            is_running()
            self.angle(a)
            time.sleep_ms(max(1, int(delay_ms)))

    def run_360(self, speed):
        if not self._pwm:
            return
        speed = max(-100, min(100, int(speed)))
        # Neutral: 1.5ms. CW: 1.0ms, CCW: 2.0ms
        ns = int(1_500_000 + (speed / 100.0) * 500_000)
        try:
            self._pwm.duty_ns(ns)
        except AttributeError:
            duty = int(1023 * ns / 20_000_000)
            self._pwm.duty(duty)

    def stop_360(self):
        self.run_360(0)

    def deinit(self):
        if self._pwm:
            try:
                self._pwm.duty(0)
                self._pwm.deinit()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# 4-Phase Stepper Motor Driver
# ─────────────────────────────────────────────────────────────────────────────
class Stepper:
    def __init__(self):
        self.pins = [
            machine.Pin(hardware.M3_IN1, machine.Pin.OUT),
            machine.Pin(hardware.M3_IN2, machine.Pin.OUT),
            machine.Pin(hardware.OUT1, machine.Pin.OUT),
            machine.Pin(hardware.OUT2, machine.Pin.OUT)
        ]
        self.seq = [
            [1, 0, 1, 0],
            [0, 1, 1, 0],
            [0, 1, 0, 1],
            [1, 0, 0, 1]
        ]
        self.idx = 0

    def step(self, steps, delay_ms=10):
        dir_val = 1 if steps > 0 else -1
        for _ in range(abs(int(steps))):
            is_running()
            self.idx = (self.idx + dir_val) % len(self.seq)
            for p, val in zip(self.pins, self.seq[self.idx]):
                p.value(val)
            time.sleep_ms(max(1, int(delay_ms)))

    def move_degrees(self, degrees, delay_ms=10):
        steps = int(float(degrees) * 200 / 360)
        self.step(steps, delay_ms)

    def release(self):
        for p in self.pins:
            try: p.value(0)
            except Exception: pass


# ─────────────────────────────────────────────────────────────────────────────
# Analog Sensor Driver (SN1, SN2, SN3, SN4)
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
# 32x32 Monochrome Bitmaps for Real Native Emojis
_EMOJI_BITMAPS = {
    'heart': b'\x00\x00\x00\x00\x00x\x1e\x00\x01\xfe\x7f\x80\x03\xff\xff\xc0\x07\xff\xff\xe0\x07\xff\xff\xe0\x07\xff\xff\xe0\x07\xff\xff\xe0\x07\xff\xff\xe0\x07\xff\xff\xe0\x07\xff\xff\xe0\x07\xff\xff\xe0\x03\xff\xff\xc0\x03\xff\xff\xc0\x01\xff\xff\x80\x01\xff\xff\x80\x00\xff\xff\x00\x00\x7f\xfe\x00\x00?\xfc\x00\x00\x1f\xf8\x00\x00\x0f\xf0\x00\x00\x03\xc0\x00\x00\x01\x80\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'smile': b'\x00\x00\x00\x00\x00\x0f\xe0\x00\x00\x7f\xfc\x00\x01\xf0\x1f\x00\x03\xc0\x07\x80\x07\x00\x01\xc0\x0e\x00\x00\xe0\x1c\x00\x00p\x18\x00\x0008 \x0880p\x1c\x180\xf8>\x18`p\x1c\x0c` \x08\x0c`\x00\x00\x0c`\x00\x00\x0c`\x00\x00\x0c`\x00\x00\x0c`\x00\x00\x0c0@\x00\x180`\x04\x1880\x0c8\x18\x1c80\x1c\x0f\xf0p\x0e\x00\x00\xe0\x07\x00\x01\xc0\x03\xc0\x07\x80\x01\xf0\x1f\x00\x00\x7f\xfc\x00\x00\x0f\xe0\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'cool': b'\x00\x00\x00\x00\x00\x0f\xe0\x00\x00\x7f\xfc\x00\x01\xf0\x1f\x00\x03\xc0\x07\x80\x07\x00\x01\xc0\x0e\x00\x00\xe0\x1c\x00\x00p\x18\x00\x000;\xfc\x7f\xb82|O\x982\xff\xdf\x98c\xff\xff\x8cc\xfc\x7f\x8cc\xfc\x7f\x8cc\xfc\x7f\x8c`\x00\x00\x0c`\x00\x00\x0c`\x00\x00\x0c0\x00\x00\x180\x00\x04\x188\x00\x088\x18\x1f\xf80\x1c\x00\x00p\x0e\x00\x00\xe0\x07\x00\x01\xc0\x03\xc0\x07\x80\x01\xf0\x1f\x00\x00\x7f\xfc\x00\x00\x0f\xe0\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'grin': b'\x00\x00\x00\x00\x00\x0f\xe0\x00\x00\x7f\xfc\x00\x01\xf0\x1f\x00\x03\xc0\x07\x80\x07\x00\x01\xc0\x0e\x00\x00\xe0\x1c\x00\x00p\x18\x00\x0009\x00 81\x881\x180\xd8\x1b\x18`p\x0e\x0c` \x04\x0c`\x00\x00\x0c`\x00\x00\x0c`\x00\x00\x0c`\x00\x00\x0ca\xff\xff\x0c0\xff\xff\x180\xff\xff\x188\x00\x008\x18\x7f\xfe0\x1c?\xfcp\x0e\x0f\xf0\xe0\x07\x00\x01\xc0\x03\xc0\x07\x80\x01\xf0\x1f\x00\x00\x7f\xfc\x00\x00\x0f\xe0\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'robot': b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x80\x00\x00\x01\x80\x00\x00\x01\x80\x00\x00\x01\x80\x00\x07\xff\xff\xe0\x07\xff\xff\xe0\x06\x00\x00`\x06\x00\x00`\x06\x00\x00`\x06|>`\x06|>`\x1e|>x\x1e|>x\x1e|>x\x1e\x00\x00x\x1e\x00\x00x\x1e\x00\x00x\x1e\x00\x00x\x06\x7f\xfe`\x06I"`\x06I"`\x06\x7f\xfe`\x06\x00\x00`\x06\x00\x00`\x07\xff\xff\xe0\x07\xff\xff\xe0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'cat': b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0f\xe0\x07\xf0\x07\xc0\x03\xe0\x03\x81\x01\xc0\x01\x1f\xf0\x80\x00\x7f\xfc\x00\x00\xff\xfe\x00\x01\xff\xff\x00\x03\xff\xff\x80\x03\xff\xff\x80\x07\x87\xc3\xc0\x07\xa7\xcb\xc0\x07\xa7\xcb\xc0\x07\x87\xc3\xc0?\xff\xff\xec\x0f\xfe\x7f\xf0\x07\xff\xff\xc0\x0f\xff\xff\xf07\xff\xff\xcc\x03\xff\xff\x80\x03\xff\xff\x80\x01\xff\xff\x00\x00\xff\xfe\x00\x00\x7f\xfc\x00\x00\x1f\xf0\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'skull': b'\x00\x00\x00\x00\x00\x01\x00\x00\x00\x1f\xf0\x00\x00\x7f\xfc\x00\x00\xff\xfe\x00\x01\xff\xff\x00\x03\xff\xff\x80\x03\xff\xff\x80\x07\xff\xff\xc0\x07\xff\xff\xc0\x07\x83\xc1\xc0\x07\x83\xc1\xc0\x0f\x83\xc1\xe0\x07\x83\xc1\xc0\x07\x83\xc1\xc0\x07\xff\xff\xc0\x07\xfe\x7f\xc0\x03\xfe\x7f\x80\x03\xff\xff\x80\x01\xff\xff\x00\x00\xff\xfe\x00\x00\x7f\xfc\x00\x00?\xfc\x00\x006\xdc\x00\x006\xdc\x00\x006\xdc\x00\x006\xdc\x00\x00?\xfc\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'sad': b'\x00\x00\x00\x00\x00\x0f\xe0\x00\x00\x7f\xfc\x00\x01\xf0\x1f\x00\x03\xc0\x07\x80\x07\x00\x01\xc0\x0e\x00\x00\xe0\x1c\x00\x00p\x18\x00\x0008 \x0880p\x1c\x180\xf8>\x18`p\x1c\x0c` \x08\x0c`\x00\x00\x8c`\x00\x01\xcc`\x00\x01\xcc`\x00\x00\x8c`\x00\x00\x0c0\x00\x00\x180\x0f\xf0\x188\x1c88\x180\x0c0\x1c`\x04p\x0e\x00\x00\xe0\x07\x00\x01\xc0\x03\xc0\x07\x80\x01\xf0\x1f\x00\x00\x7f\xfc\x00\x00\x0f\xe0\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'surprised': b'\x00\x00\x00\x00\x00\x0f\xe0\x00\x00\x7f\xfc\x00\x01\xf0\x1f\x00\x03\xc0\x07\x80\x07\x00\x01\xc0\x0e\x00\x00\xe0\x1c \x04p\x18\xf8\x1f08\xf8\x1f81\xfc?\x980\xf8\x1f\x18`\xf8\x1f\x0c` \x04\x0c`\x00\x00\x0c`\x00\x00\x0c`\x00\x00\x0c`\x01\x00\x0c`\x07\xc0\x0c0\x0f\xe0\x180\x0e\xe0\x188\x1ep8\x18\x0e\xe00\x1c\x0f\xe0p\x0e\x07\xc0\xe0\x07\x01\x01\xc0\x03\xc0\x07\x80\x01\xf0\x1f\x00\x00\x7f\xfc\x00\x00\x0f\xe0\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'angry': b'\x00\x00\x00\x00\x00\x0f\xe0\x00\x00\x7f\xfc\x00\x01\xf0\x1f\x00\x03\xc0\x07\x80\x07\x00\x01\xc0\x0e\x00\x00\xe0\x1c\x00\x00p\x19\x00\x00\xb09\x80\x01\xb80\xc0\x03\x180`\x06\x18`0\x0c\x0c`x\x1c\x0c`\xf8>\x0c`p\x1c\x0c` \x08\x0c`\x00\x00\x0c`\x00\x00\x0c0\x00\x00\x180\x00\x00\x188\x00\x008\x18 \x040\x1c?\xfcp\x0e?\xfc\xe0\x07\x00\x01\xc0\x03\xc0\x07\x80\x01\xf0\x1f\x00\x00\x7f\xfc\x00\x00\x0f\xe0\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'ghost': b'\x00\x00\x00\x00\x00\x01\x00\x00\x00\x1f\xf0\x00\x00\x7f\xfc\x00\x00\xff\xfe\x00\x01\xff\xff\x00\x03\xff\xff\x80\x03\xff\xff\x80\x07\xff\xff\xc0\x07\xff\xff\xc0\x07\xc7\xc7\xc0\x07\x83\x83\xc0\x0f\xa3\xa3\xf0\x0f\xa3\xa3\xf0\x0f\xc7\xc7\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0c\xf3\xcf0\x08\xe3\x8e0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'star': b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x80\x00\x00\x01\x80\x00\x00\x01\x80\x00\x00\x03\xc0\x00\x00\x03\xc0\x00\x00\x03\xc0\x00\x00\x07\xe0\x00\x00\x07\xe0\x00\x0f\xff\xff\xf0\x03\xff\xff\xc0\x01\xff\xff\x80\x00\xff\xff\x00\x00\x7f\xfe\x00\x00\x1f\xf8\x00\x00\x1f\xf8\x00\x00?\xfc\x00\x00?\xfc\x00\x00?\xfc\x00\x00|>\x00\x00x\x1e\x00\x00`\x06\x00\x00@\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'thumbs_up': b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\xf8\x00\x00\x01\xf8\x00\x00\x01\xf8\x00\x00\x01\xf8\x00\x00\x01\xf8\x00\x00\x01\xf8\x00\x00\x01\xf8\x00\x00\x01\xf8\x00\x00\x01\xf8\x00\x00\x01\xf8\x00\x00\x01\xff\xff\x00\x01\xff\xff\x00\x00?\xff\x00\x000\xff\x00\x00?\xff\x00\x00?\xff\x00\x000\xff\x00\x00?\xff\x00\x00?\xff\x00\x000\xff\x00\x03\xff\xff\x00\x03\xff\xff\x00\x03\xf0\x00\x00\x03\xf0\x00\x00\x03\xf0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'fire': b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\xf8\x00\x00\x01\xf8\x00\x00\x01\xf8\x00\x00\x1f\xf8\x00\x00\x1f\xf8\x00\x00\x1f\xff\x00\x00\x1f\xff\x00\x00\x1f\xff\x00\x00\x1f\xff\x00\x01\xff\xff\xc0\x01\xff\xff\xc0\x00\xff\xff\x80\x00\x7f\xff\x00\x00\x7f\xff\x00\x00<?\x00\x00<?\x00\x00\x1c?\x00\x00\x0c?\x00\x00\x0c?\x00\x00\x04?\x00\x00\x040\x00\x00\x00 \x00\x00\x01\xc0\x00\x00\x01\xc0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'music': b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\xe0\x00\x00\x0f\xe0\x00\x00\xff\xe0\x00\x07\xfe`\x00\x0f\xf0`\x00\x0f\x00`\x00\x0c\x00`\x00\x0c\x00`\x00\x0c\x00`\x00\x0c\x00`\x00\x0c\x00`\x00\x0c\x00`\x00\x0c\x02`\x00\x0c\x0f\xe0\x00\x0c\x1f\xe0\x00\x0c\x1f\xe0\x00L?\xe0\x01\xfc\x1f\xc0\x03\xfc\x1f\xc0\x03\xfc\x0f\x80\x07\xfc\x02\x00\x03\xf8\x00\x00\x03\xf8\x00\x00\x01\xf0\x00\x00\x00@\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'lightning': b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00@\x00\x00\x00\xc0\x00\x00\x01\xc0\x00\x00\x01\xc0\x00\x00\x03\xc0\x00\x00\x07\xc0\x00\x00\x0f\xc0\x00\x00\x1f\xc0\x00\x00\x1f\xc0\x00\x00?\xc0\x00\x00\x7f\xff\x80\x00\xff\xff\x00\x00\xff\xfe\x00\x00\x01\xfc\x00\x00\x01\xf8\x00\x00\x01\xf8\x00\x00\x03\xf0\x00\x00\x03\xe0\x00\x00\x03\xc0\x00\x00\x03\x80\x00\x00\x07\x00\x00\x00\x07\x00\x00\x00\x06\x00\x00\x00\x0c\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'alien': b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x07\xff\xff\xe0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xff\xff\xf0\x0f\xdf\xfb\xf0\x1f\x8f\xf1\xf8\x0f\x07\xe0\xf0\x0f\x07\xe0\xf0\x0e\x03\xc0p\x0f\x07\xe0\xf0\x0f\x07\xe0\xf0\x0f\x8f\xf1\xf0\x0f\xff\xff\xf0\x07\xfd\xbf\xe0\x07\xff\xff\xe0\x03\xff\xff\xc0\x03\xfe\x7f\xc0\x01\xff\xff\x80\x01\xff\xff\x80\x00\xff\xff\x00\x00\x7f\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'check': b'\x00\x00\x00\x00\x00\x01\x00\x00\x00?\xf8\x00\x00\xff\xfe\x00\x01\xff\xff\x00\x03\xff\xff\x80\x07\xff\xff\xc0\x0f\xff\xff\xe0\x1f\xff\xff\xd0\x1f\xff\xff\x90?\xff\xff\x18?\xff\xfe8?\xff\xfcx?\xff\xf8\xf8?\xff\xf1\xf8\x7f\xff\xe3\xfc?\x7f\xc7\xf8??\x8f\xf8?\x1f\x1f\xf8?\x8e?\xf8?\xc4\x7f\xf8\x1f\xe0\xff\xf0\x1f\xf1\xff\xf0\x0f\xfb\xff\xe0\x07\xff\xff\xc0\x03\xff\xff\x80\x01\xff\xff\x00\x00\xff\xfe\x00\x00?\xf8\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
}

class DisplayWrapper:
    def __init__(self, display_obj):
        self.oled = display_obj

    def init(self):
        """Initializes display state for new scripts."""
        if store_manager and store_manager.manager and store_manager.manager.display:
            self.oled = store_manager.manager.display
        if self.oled:
            try:
                self.oled.fill(0)
                if hasattr(self.oled, 'show'):
                    self.oled.show()
            except Exception:
                pass

    def clear(self):
        if self.oled:
            try:
                self.oled.fill(0)
            except Exception:
                pass

    def show(self):
        if self.oled and hasattr(self.oled, 'show'):
            try:
                self.oled.show()
            except Exception:
                pass

    def print(self, msg, y=None, size=1, x=0, color=1):
        if self.oled:
            try:
                y_pos = 0 if y is None else int(y)
                self.oled.text(str(msg), int(x), y_pos, color)
            except Exception:
                pass

    def big_print(self, val, scale=4):
        if not self.oled:
            return
        try:
            self.oled.fill(0)
            s_val = str(val)
            self.oled.text(s_val, 32, 28, 1)
            self.show()
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

    def emoji(self, name, x=48, y=16):
        if not self.oled:
            return
        try:
            import framebuf
            key = str(name).lower()
            if key in _EMOJI_BITMAPS:
                fb = framebuf.FrameBuffer(bytearray(_EMOJI_BITMAPS[key]), 32, 32, framebuf.MONO_HLSB)
                self.oled.fill(0)
                self.oled.blit(fb, int(x), int(y))
            else:
                self.oled.fill(0)
                self.oled.text(f"[{name}]", 20, 28, 1)
            if hasattr(self.oled, 'show'):
                self.oled.show()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# I2C Helper Functions
# ─────────────────────────────────────────────────────────────────────────────
def _get_i2c():
    if store_manager and store_manager.manager and store_manager.manager.i2c:
        return store_manager.manager.i2c
    try:
        return machine.I2C(0, sda=machine.Pin(hardware.I2C_SDA), scl=machine.Pin(hardware.I2C_SCL), freq=400000)
    except Exception:
        return None

def i2c_scan():
    i2c = _get_i2c()
    return i2c.scan() if i2c else []

def i2c_read(addr, reg, nbytes=1):
    try:
        i2c = _get_i2c()
        if not i2c: return 0
        data = i2c.readfrom_mem(int(addr), int(reg), int(nbytes))
        val = 0
        for b in data:
            val = (val << 8) | b
        return val
    except Exception:
        return 0

def i2c_write(addr, reg, val):
    try:
        i2c = _get_i2c()
        if i2c:
            i2c.writeto_mem(int(addr), int(reg), bytes([int(val) & 0xFF]))
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Power & Telemetry Helpers
# ─────────────────────────────────────────────────────────────────────────────
def battery_pct():
    if store_manager and store_manager.manager:
        return store_manager.manager.last_pct
    return 100

def voltage():
    if store_manager and store_manager.manager:
        return store_manager.manager.last_volts
    return 7.4

def current():
    if store_manager and store_manager.manager:
        return store_manager.manager.last_ma
    return 0.0

def power():
    if store_manager and store_manager.manager:
        return round(store_manager.manager.last_volts * (store_manager.manager.last_ma / 1000.0), 2)
    return 0.0

def uptime():
    return time.ticks_ms() // 1000


# ─────────────────────────────────────────────────────────────────────────────
# Ultrasonic Distance Sensor Helper
# ─────────────────────────────────────────────────────────────────────────────
def read_ultrasonic(trig_pin, echo_pin):
    try:
        t = machine.Pin(int(trig_pin), machine.Pin.OUT)
        e = machine.Pin(int(echo_pin), machine.Pin.IN)
        t.value(0)
        time.sleep_us(2)
        t.value(1)
        time.sleep_us(10)
        t.value(0)
        pulse = machine.time_pulse_us(e, 1, 30000)
        if pulse > 0:
            return round(pulse / 58.0, 1)
    except Exception:
        pass
    return 999.0


# Physical Button Pins
_btn_start = machine.Pin(hardware.BTN1, machine.Pin.IN, machine.Pin.PULL_UP)
_btn_screen = machine.Pin(hardware.BTN2, machine.Pin.IN, machine.Pin.PULL_UP)

# Initialize global references
if store_manager and store_manager.manager:
    display = DisplayWrapper(store_manager.manager.display)
else:
    display = DisplayWrapper(None)

def stop_all():
    """Immediately stops all motors, PWM channels, and servos."""
    if store_manager and store_manager.manager:
        store_manager.manager._stop_all_motors()
        store_manager.manager._stop_servo()

def is_running():
    """Polls Physical Buttons, Serial, BLE & WiFi to safely interrupt execution and keep the OS responsive."""
    if _btn_start.value() == 0:
        buzzer.play_stop()
        stop_all()
        if store_manager and store_manager.manager:
            store_manager.manager.stop_prog("STOPPED_BY_BUTTON")
        raise KeyboardInterrupt("STOPPED_BY_PHYSICAL_BUTTON")
        
    if store_manager and store_manager.manager:
        mgr = store_manager.manager
        mgr.poll_serial()
        mgr.poll_power_telemetry()
        if mgr.prog_status != "RUNNING" or not mgr._in_exec or mgr.is_uploading:
            buzzer.play_stop()
            stop_all()
            raise KeyboardInterrupt("STOPPED_BY_USER")
    return True

def start():
    """Initializes runtime references for user scripts."""
    global display
    if store_manager and store_manager.manager:
        display.oled = store_manager.manager.display

def delay(ms):
    """Interruptible sleep — actively polls communication and status every 10ms."""
    start_t = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start_t) < ms:
        is_running()
        rem = ms - time.ticks_diff(time.ticks_ms(), start_t)
        time.sleep_ms(min(10, max(1, rem)))

def broadcast(val):
    """Broadcasts sensor value or numerical telemetry to the App HUD and Serial Monitor."""
    if store_manager and store_manager.manager:
        store_manager.manager.write_out(f"SENSOR:{val}\n")
    else:
        print(f"SENSOR:{val}")

def log(msg):
    """Sends log text to App Serial Monitor across BLE, WiFi, and Serial."""
    if store_manager and store_manager.manager:
        store_manager.manager.write_out(f"{msg}\n")
    else:
        print(msg)
