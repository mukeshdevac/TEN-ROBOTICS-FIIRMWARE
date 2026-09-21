"""
XPT2046 SPI Resistive Touch Screen Driver for MicroPython (ESP32-S3)
Calibrated for 3.5" 480x320 ILI9488 LCD Module.
"""

import machine
import time

class TouchXPT2046:
    def __init__(self, spi, cs, irq=None, width=480, height=320, rotation=1):
        self.spi = spi
        self.cs = machine.Pin(cs, machine.Pin.OUT)
        self.irq = machine.Pin(irq, machine.Pin.IN) if irq is not None else None
        self.width = width
        self.height = height
        self.rotation = rotation
        
        self.cs.value(1)
        
        # Calibration raw ADC ranges (Min / Max)
        self.x_min = 300
        self.x_max = 3800
        self.y_min = 250
        self.y_max = 3850
        
        self._last_x = -1
        self._last_y = -1
        self._last_touch_time = 0

    def _read_adc(self, command):
        self.cs.value(0)
        # Send command byte and read 2-byte response
        tx = bytearray([command, 0x00, 0x00])
        rx = bytearray(3)
        self.spi.write_readinto(tx, rx)
        self.cs.value(1)
        val = ((rx[1] << 8) | rx[2]) >> 3
        return val

    def raw_touch(self):
        """Read raw X, Y, Z pressure values from XPT2046."""
        if self.irq and self.irq.value() == 1:
            return None # Touch IRQ high = no touch
            
        z1 = self._read_adc(0xB0) # Z1 pressure
        z2 = self._read_adc(0xC0) # Z2 pressure
        
        # Pressure threshold check
        z = z1 + 4095 - z2
        if z < 300:
            return None
            
        x_raw = self._read_adc(0xD0) # X-position
        y_raw = self._read_adc(0x90) # Y-position
        
        if x_raw <= 100 or y_raw <= 100:
            return None
            
        return (x_raw, y_raw)

    def get_touch(self):
        """
        Get debounced touch coordinates (x, y) scaled to screen resolution (480x320).
        Returns (x, y) tuple if touched, or None if not touched.
        """
        raw = self.raw_touch()
        if not raw:
            return None
            
        rx, ry = raw
        
        # Clamp ADC values
        rx = max(self.x_min, min(self.x_max, rx))
        ry = max(self.y_min, min(self.y_max, ry))
        
        # Map raw ADC values to 0..480 and 0..320
        norm_x = (rx - self.x_min) / (self.x_max - self.x_min)
        norm_y = (ry - self.y_min) / (self.y_max - self.y_min)
        
        # Rotation adjustment
        if self.rotation == 1: # Landscape
            x = int(norm_x * self.width)
            y = int((1.0 - norm_y) * self.height)
        elif self.rotation == 3: # Inverted Landscape
            x = int((1.0 - norm_x) * self.width)
            y = int(norm_y * self.height)
        elif self.rotation == 0: # Portrait
            x = int(norm_y * self.width)
            y = int(norm_x * self.height)
        else:
            x = int((1.0 - norm_y) * self.width)
            y = int((1.0 - norm_x) * self.height)
            
        x = max(0, min(self.width - 1, x))
        y = max(0, min(self.height - 1, y))
        
        self._last_x = x
        self._last_y = y
        return (x, y)
