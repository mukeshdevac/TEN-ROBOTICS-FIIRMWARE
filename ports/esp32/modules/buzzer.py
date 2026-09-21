"""
TEN Robotics - Audio Buzzer Subsystem for ESP32 DevKit V1
Provides non-blocking and safe tone sequences on GPIO 33.
"""

import machine
import time
import hardware

class Buzzer:
    def __init__(self, pin_num=None):
        if pin_num is None:
            pin_num = getattr(hardware, 'BUZZER_PIN', 33)
        self.pin_num = pin_num
        self._pwm = None

    def _get_pwm(self):
        if not self._pwm:
            try:
                self._pwm = machine.PWM(machine.Pin(self.pin_num), freq=1000, duty=0)
            except Exception as e:
                print(f"Buzzer Init Error: {e}")
                self._pwm = None
        return self._pwm

    def tone(self, freq, duration_ms, duty=512):
        pwm = self._get_pwm()
        if not pwm:
            return
        try:
            if freq <= 0:
                pwm.duty(0)
            else:
                pwm.freq(int(freq))
                pwm.duty(int(duty))
            time.sleep_ms(duration_ms)
            pwm.duty(0)
        except Exception as e:
            print(f"Buzzer Tone Error: {e}")

    def play_startup(self):
        """Ascending startup sequence (C5, E5, G5, C6)."""
        notes = [(523, 80), (659, 80), (784, 80), (1046, 150)]
        for f, d in notes:
            self.tone(f, d)
            time.sleep_ms(20)

    def play_run(self):
        """High prompt dual-tone for program start (A5, A6)."""
        self.tone(880, 60)
        time.sleep_ms(30)
        self.tone(1760, 100)

    def play_stop(self):
        """Descending sequence for program stop (C6, G5, C5)."""
        notes = [(1046, 70), (784, 70), (523, 120)]
        for f, d in notes:
            self.tone(f, d)
            time.sleep_ms(20)

    def play_button(self):
        """Crisp 2000Hz click sound for button / touch presses."""
        self.tone(2000, 25, duty=256)

    def play_error(self):
        """Double low-pitch alert buzz for execution errors."""
        self.tone(220, 140, duty=768)
        time.sleep_ms(70)
        self.tone(220, 200, duty=768)

# Global Buzzer singleton instance
buzzer = Buzzer()
