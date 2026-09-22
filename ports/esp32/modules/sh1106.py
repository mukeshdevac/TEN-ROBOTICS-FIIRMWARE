# MicroPython SH1106 OLED driver (1.3" I2C OLED with 2-pixel column offset)
from micropython import const
import framebuf

# Register definitions
_SET_CONTRAST = const(0x81)
_SET_NORM_INV = const(0xA6)
_SET_DISP = const(0xAE)
_SET_SCAN_DIR = const(0xC0)
_SET_SEG_REMAP = const(0xA0)
_LOW_COLUMN_ADDRESS = const(0x00)
_HIGH_COLUMN_ADDRESS = const(0x10)
_SET_PAGE_ADDRESS = const(0xB0)

class SH1106(framebuf.FrameBuffer):
    def __init__(self, width, height, external_vcc=False):
        self.width = width
        self.height = height
        self.external_vcc = external_vcc
        self.pages = self.height // 8
        self.buffer = bytearray(self.pages * self.width)
        super().__init__(self.buffer, self.width, self.height, framebuf.MONO_VLSB)
        self.init_display()

    def init_display(self):
        for cmd in (
            _SET_DISP | 0x00,  # Display off
            0xD5, 0x80,        # Set display clock divide ratio/oscillator frequency
            0xA8, self.height - 1, # Multiplex ratio
            0xD3, 0x00,        # Display offset = 0
            0x40,              # Start line = 0
            0xAD, 0x8A if self.external_vcc else 0x8B, # DC-DC control mode (Charge pump on)
            _SET_SEG_REMAP | 0x01, # Column 127 mapped to SEG0
            _SET_SCAN_DIR | 0x08,  # Scan from COM[N-1] to COM0 (flipped vertically)
            0xDA, 0x12,        # COM pins hardware configuration
            0x81, 0xFF,        # Contrast control
            0xD9, 0x1F if self.external_vcc else 0x22, # Pre-charge period
            0xDB, 0x40,        # VCOM deselect level
            0xA4,              # Entire display on (output follows RAM)
            _SET_NORM_INV,     # Normal display
            _SET_DISP | 0x01,  # Display on
        ):
            self.write_cmd(cmd)
        self.fill(0)
        self.show()

    def poweroff(self):
        self.write_cmd(_SET_DISP | 0x00)

    def poweron(self):
        self.write_cmd(_SET_DISP | 0x01)

    def contrast(self, contrast):
        self.write_cmd(_SET_CONTRAST)
        self.write_cmd(contrast & 0xFF)

    def invert(self, invert):
        self.write_cmd(_SET_NORM_INV | (invert & 1))

    def show(self):
        for page in range(self.pages):
            self.write_cmd(_SET_PAGE_ADDRESS | page)
            self.write_cmd(_LOW_COLUMN_ADDRESS | 2) # SH1106 column offset: 2
            self.write_cmd(_HIGH_COLUMN_ADDRESS | 0)
            start = self.width * page
            self.write_data(self.buffer[start:start + self.width])


class SH1106_I2C(SH1106):
    def __init__(self, width, height, i2c, addr=0x3C, external_vcc=False):
        self.i2c = i2c
        self.addr = addr
        self.temp = bytearray(2)
        self.write_buf = bytearray(width + 1)
        self.write_buf[0] = 0x40 # Control byte for data stream
        super().__init__(width, height, external_vcc)

    def write_cmd(self, cmd):
        self.temp[0] = 0x80 # Co=1, D/C#=0 (Command)
        self.temp[1] = cmd
        self.i2c.writeto(self.addr, self.temp)

    def write_data(self, buf):
        self.write_buf[1:] = buf
        self.i2c.writeto(self.addr, self.write_buf)
