import time
from micropython import const

_REG_CONFIG = const(0x00)
_REG_SHUNTVOLTAGE = const(0x01)
_REG_BUSVOLTAGE = const(0x02)
_REG_POWER = const(0x03)
_REG_CURRENT = const(0x04)
_REG_CALIBRATION = const(0x05)

class INA219:
    def __init__(self, i2c, addr=0x40):
        self.i2c = i2c
        self.addr = addr
        self._cal_value = 0
        self.set_calibration_32V_2A()

    def _write_register(self, reg, value):
        buf = bytearray(3)
        buf[0] = reg
        buf[1] = (value >> 8) & 0xFF
        buf[2] = value & 0xFF
        self.i2c.writeto(self.addr, buf)

    def _read_register(self, reg):
        self.i2c.writeto(self.addr, bytearray([reg]))
        buf = self.i2c.readfrom(self.addr, 2)
        val = (buf[0] << 8) | buf[1]
        if val & 0x8000:
            val -= 0x10000
        return val

    def set_calibration_32V_2A(self):
        self._cal_value = 4096
        self._write_register(_REG_CALIBRATION, self._cal_value)
        # config for 32V, 2A, 12-bit ADC
        self._write_register(_REG_CONFIG, 0x399F)

    def get_bus_voltage_V(self):
        val = self._read_register(_REG_BUSVOLTAGE)
        return (val >> 3) * 0.004

    def get_shunt_voltage_mV(self):
        val = self._read_register(_REG_SHUNTVOLTAGE)
        return val * 0.01

    def get_current_mA(self):
        self._write_register(_REG_CALIBRATION, self._cal_value)
        val = self._read_register(_REG_CURRENT)
        return val / 10.0

    def get_power_mW(self):
        self._write_register(_REG_CALIBRATION, self._cal_value)
        val = self._read_register(_REG_POWER)
        return val * 2.0
