from machine import Pin, I2C
import ssd1306
import time
import math
import random

class HighFidEyes:
    def __init__(self, oled):
        self.oled = oled
        self.width = 128
        self.height = 64
        
        # Center positions for eyes
        self.EXL = 35
        self.EXR = 95
        self.vpos = 32
        
        # Radii
        self.EYE_R = 14
        self.PUPIL_R = 5
        
        # State
        self.pupil_x = 0
        self.pupil_y = 0
        self.eye_scale_y = 1.0
        self.style = "normal" # normal, happy, sleep

    def _circle(self, x, y, r, c):
        if r <= 0:
            return
        if hasattr(self.oled, 'hline'):
            self.oled.hline(x-r, y, r*2, c)
            for i in range(1, r):
                a = int(math.sqrt(r*r - i*i))
                self.oled.hline(x-a, y+i, a*2, c)
                self.oled.hline(x-a, y-i, a*2, c)

    def _draw_eye(self, x, y, c):
        if not hasattr(self.oled, 'fill_rect'):
            return
        if self.style == "sleep":
            self.oled.fill_rect(x - self.EYE_R, y - 1, self.EYE_R*2, 2, 1)
            return

        r_y = int(self.EYE_R * self.eye_scale_y)
        if r_y > 0:
            self.oled.hline(x - self.EYE_R, y, self.EYE_R*2, 1)
            for i in range(1, r_y):
                a = int(math.sqrt(self.EYE_R*self.EYE_R - (i/self.eye_scale_y)**2))
                self.oled.hline(x-a, y+i, a*2, 1)
                self.oled.hline(x-a, y-i, a*2, 1)
        
        if self.eye_scale_y > 0.3:
            px = x + self.pupil_x
            py = y + self.pupil_y
            self._circle(px, py, self.PUPIL_R, 0)
            
        if self.style == "happy":
            self.oled.fill_rect(x - self.EYE_R, y + 2, self.EYE_R*2, self.EYE_R, 0)

    def render(self):
        if not self.oled:
            return
        # Guard against drawing over Upload Screen
        import store_manager
        if store_manager.manager and store_manager.manager.is_uploading:
            return
            
        try:
            self.oled.fill(0)
            self._draw_eye(self.EXL, self.vpos, 1)
            self._draw_eye(self.EXR, self.vpos, 1)
            if hasattr(self.oled, 'show'):
                self.oled.show()
        except Exception:
            pass

    def center_eyes(self):
        self.pupil_x = 0
        self.pupil_y = 0
        self.eye_scale_y = 1.0
        self.style = "normal"
        self.render()

    def blink(self, height=0.1):
        for s in [0.7, 0.4, 0.1, 0.4, 0.7, 1.0]:
            self.eye_scale_y = s
            self.render()
            time.sleep_ms(20)

    def sleep(self):
        self.style = "sleep"
        self.render()

    def wakeup(self):
        self.style = "normal"
        for s in [0.2, 0.5, 0.8, 1.0]:
            self.eye_scale_y = s
            self.render()
            time.sleep_ms(50)

    def happy_eye(self):
        self.style = "happy"
        self.render()

    def saccade(self, x, y):
        self.pupil_x = x
        self.pupil_y = y
        self.render()

    def move_big_eye(self, direction):
        target_x = 6 * direction
        steps = 4
        for i in range(steps + 1):
            self.pupil_x = (target_x * i) // steps
            self.render()
            time.sleep_ms(30)

    def move_right_big_eye(self):
        self.move_big_eye(1)

    def move_left_big_eye(self):
        self.move_big_eye(-1)

def get_eyes():
    try:
        from store_manager import manager
        if manager and manager.display:
            return HighFidEyes(manager.display)
    except Exception:
        pass
    i2c = I2C(0, sda=Pin(21), scl=Pin(22))
    try:
        import sh1106
        return HighFidEyes(sh1106.SH1106_I2C(128, 64, i2c))
    except Exception:
        import ssd1306
        return HighFidEyes(ssd1306.SSD1306_I2C(128, 64, i2c))
