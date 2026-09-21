"""
ILI9488 3.5" 480x320 SPI TFT LCD Driver for MicroPython (ESP32-S3)
Optimized for high-speed SPI rendering and on-device Touch IDE UI.
"""

import machine
import time
import ustruct

# Color definitions (RGB565)
BLACK   = 0x0000
WHITE   = 0xFFFF
RED     = 0xF800
GREEN   = 0x07E0
BLUE    = 0x001F
CYAN    = 0x07FF
MAGENTA = 0xF81F
YELLOW  = 0xFFE0
ORANGE  = 0xFD20
GRAY    = 0x8410
DARK_GRAY = 0x2104
PANEL_BG = 0x10A2
BLOCK_BLUE = 0x4CBF
BLOCK_GREEN = 0x5E05
BLOCK_ORANGE = 0xFC00
BLOCK_PURPLE = 0xA21F
BLOCK_DARK = 0x18E3

def color565(r, g, b):
    """Convert 8-bit RGB components to 16-bit RGB565 format."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

class ILI9488:
    def __init__(self, spi, cs, dc, rst=None, bl=None, width=480, height=320, rotation=1):
        self.spi = spi
        self.cs = machine.Pin(cs, machine.Pin.OUT)
        self.dc = machine.Pin(dc, machine.Pin.OUT)
        self.rst = machine.Pin(rst, machine.Pin.OUT) if rst is not None else None
        self.bl = machine.Pin(bl, machine.Pin.OUT) if bl is not None else None
        
        self.width = width
        self.height = height
        self.rotation = rotation
        
        if self.bl:
            try:
                self.bl_pwm = machine.PWM(self.bl, freq=1000, duty=1023)
            except Exception:
                self.bl.value(1)

        self.cs.value(1)
        self.dc.value(1)
        self.reset()
        self.init_display()
        self.set_rotation(rotation)
        self.fill(BLACK)

    def _write_cmd(self, cmd):
        self.dc.value(0)
        self.cs.value(0)
        self.spi.write(bytearray([cmd]))
        self.cs.value(1)

    def _write_data(self, data):
        self.dc.value(1)
        self.cs.value(0)
        if isinstance(data, int):
            self.spi.write(bytearray([data]))
        else:
            self.spi.write(data)
        self.cs.value(1)

    def reset(self):
        if self.rst:
            self.rst.value(1)
            time.sleep_ms(10)
            self.rst.value(0)
            time.sleep_ms(20)
            self.rst.value(1)
            time.sleep_ms(120)

    def init_display(self):
        # ILI9488 Initialisation Commands
        self._write_cmd(0xE0) # Positive Gamma Control
        self._write_data(bytearray([0x00, 0x03, 0x09, 0x08, 0x16, 0x0A, 0x3F, 0x78, 0x4C, 0x09, 0x0A, 0x08, 0x16, 0x1A, 0x0F]))

        self._write_cmd(0XE1) # Negative Gamma Control
        self._write_data(bytearray([0x00, 0x16, 0x19, 0x03, 0x0F, 0x05, 0x32, 0x45, 0x46, 0x04, 0x0E, 0x0D, 0x35, 0x37, 0x0F]))

        self._write_cmd(0xC0) # Power Control 1
        self._write_data(bytearray([0x17, 0x15]))

        self._write_cmd(0xC1) # Power Control 2
        self._write_data(bytearray([0x41]))

        self._write_cmd(0xC5) # VCOM Control
        self._write_data(bytearray([0x00, 0x12, 0x80]))

        self._write_cmd(0x36) # Memory Access Control
        self._write_data(bytearray([0x48])) # Default landscape

        self._write_cmd(0x3A) # Interface Pixel Format (16-bit RGB565)
        self._write_data(bytearray([0x55]))

        self._write_cmd(0xB0) # Interface Mode Control
        self._write_data(bytearray([0x00]))

        self._write_cmd(0xB1) # Frame Rate Control
        self._write_data(bytearray([0xA0]))

        self._write_cmd(0xB4) # Display Inversion Control
        self._write_data(bytearray([0x02]))

        self._write_cmd(0xB6) # Display Function Control
        self._write_data(bytearray([0x02, 0x02, 0x3B]))

        self._write_cmd(0xE9) # Set Image Function
        self._write_data(bytearray([0x00]))

        self._write_cmd(0xF7) # Adjust Control
        self._write_data(bytearray([0xA9, 0x51, 0x2C, 0x82]))

        self._write_cmd(0x11) # Sleep Out
        time.sleep_ms(120)

        self._write_cmd(0x29) # Display On
        time.sleep_ms(20)

    def set_rotation(self, m):
        self.rotation = m % 4
        self._write_cmd(0x36)
        if self.rotation == 0:   # Portrait
            self._write_data(0x48)
            self.width, self.height = 320, 480
        elif self.rotation == 1: # Landscape
            self._write_data(0x28)
            self.width, self.height = 480, 320
        elif self.rotation == 2: # Inverted Portrait
            self._write_data(0x88)
            self.width, self.height = 320, 480
        elif self.rotation == 3: # Inverted Landscape
            self._write_data(0xE8)
            self.width, self.height = 480, 320

    def set_window(self, x0, y0, x1, y1):
        self._write_cmd(0x2A) # Column Address Set
        self._write_data(bytearray([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF]))
        self._write_cmd(0x2B) # Page Address Set
        self._write_data(bytearray([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF]))
        self._write_cmd(0x2C) # Memory Write

    def fill(self, color):
        self.fill_rect(0, 0, self.width, self.height, color)

    def fill_rect(self, x, y, w, h, color):
        x = max(0, min(x, self.width - 1))
        y = max(0, min(y, self.height - 1))
        w = max(1, min(w, self.width - x))
        h = max(1, min(h, self.height - y))

        self.set_window(x, y, x + w - 1, y + h - 1)
        hi = (color >> 8) & 0xFF
        lo = color & 0xFF
        chunk_size = 512
        buf = bytearray([hi, lo] * chunk_size)
        
        total_pixels = w * h
        self.dc.value(1)
        self.cs.value(0)
        while total_pixels > 0:
            count = min(total_pixels, chunk_size)
            self.spi.write(buf[:count * 2])
            total_pixels -= count
        self.cs.value(1)

    def rect(self, x, y, w, h, color):
        self.fill_rect(x, y, w, 1, color)
        self.fill_rect(x, y + h - 1, w, 1, color)
        self.fill_rect(x, y, 1, h, color)
        self.fill_rect(x + w - 1, y, 1, h, color)

    def draw_button(self, x, y, w, h, text, bg_color=PANEL_BG, fg_color=WHITE, border_color=CYAN, scale=2):
        self.fill_rect(x, y, w, h, bg_color)
        self.rect(x, y, w, h, border_color)
        # Center text inside button
        text_len = len(text) * 8 * scale
        text_h = 8 * scale
        tx = x + (w - text_len) // 2
        ty = y + (h - text_h) // 2
        self.text(text, max(x + 2, tx), max(y + 2, ty), fg_color, scale=scale)

    def char(self, c, x, y, color=WHITE, scale=1):
        """Draw 8x8 standard ASCII character with scaling."""
        from font8x8 import FONT8X8
        if ord(c) < 32 or ord(c) > 127:
            c = '?'
        glyph = FONT8X8[ord(c) - 32]
        for row in range(8):
            byte = glyph[row]
            for col in range(8):
                if (byte >> col) & 0x01:
                    if scale == 1:
                        self.fill_rect(x + col, y + row, 1, 1, color)
                    else:
                        self.fill_rect(x + col * scale, y + row * scale, scale, scale, color)

    def text(self, string, x, y, color=WHITE, scale=1):
        cur_x = x
        for c in string:
            if c == '\n':
                y += 10 * scale
                cur_x = x
                continue
            self.char(c, cur_x, y, color, scale)
            cur_x += 8 * scale
