"""
TEN Robotics - Store Manager & System Lifecycle for ESP32 DevKit V1 (PCB V2)
Integrates Original Logo Boot Screen, 7-Page Multi-Screen UI, Always-On BLE with NUS & LOF,
Interactive Motor Tester, Live Sensor HUD, Closed-Loop Upload Engine, and Battery Telemetry.
Website: https://www.tenrobotics.in/
"""

import io
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

_MOTOR_PIN_MAP = [
    (hardware.M1_IN1, hardware.M1_IN2), # 0: M1 (Left)
    (hardware.M2_IN1, hardware.M2_IN2), # 1: M2 (Right)
    (hardware.M3_IN1, hardware.M3_IN2), # 2: M3 (Aux)
    (hardware.OUT1, hardware.OUT2),     # 3: OUT 1/2
]




class StoreManager:
    def __init__(self):
        self.header_text          = "TEN ROBOTICS ESP32 V1"
        self.bt_status            = "DISC"
        self.prog_status          = "STOPPED" # STOPPED, RUNNING
        self.last_error           = None
        self._in_exec             = False
        self.pending_start        = False
        self.exec_start_ticks     = 0
        self.is_uploading         = False
        self.last_power_telemetry = 0
        self.serial_active        = True

        # Multi-Page Display State (7 Pages Total)
        self.total_pages          = 7
        self.current_page         = 0
        self.last_ui_refresh      = 0
        self.last_volts           = 0.0
        self.last_pct             = 0
        self.last_ma              = 0.0
        self.dev_name             = "TEN_DEVKIT"

        # Protocol Buffers & Upload State
        self._serial_buf          = bytearray()
        self._ble_buf             = bytearray()
        self._wifi_buf            = bytearray()
        self._upload_file         = None
        self._upload_total_lines  = 0
        self._upload_current_line = 0
        self._upload_target_file  = "app.py"
        self._last_upload_ui_update = 0

        # Feature 1: Low Battery Alarm Configuration
        self.low_batt_alarm_enabled = True
        self.last_low_batt_beep     = 0

        # Feature 2: Interactive Motor Test
        self.motor_cursor           = 0  # 0: Motor Select (MTR), 1: Speed Select (SPD)
        self.motor_test_idx         = 0  # 0: M1, 1: M2, 2: M3, 3: OUT
        self.motor_test_speeds      = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, -10, -20, -30, -40, -50, -60, -70, -80, -90, -100]
        self.motor_test_spd_idx     = 5  # Default +60%
        self.motor_test_running     = False
        self.motor_test_start_ticks = 0
        self._active_motor_pwms     = []

        # Feature 3: Interactive Servo Test & Sweep (Page 4, S1=GPIO 18, S2=GPIO 19)
        self.servo_cursor            = 0  # 0: SRV (S1/S2), 1: FROM, 2: TO
        self.servo_idx               = 0  # 0: S1 (D18), 1: S2 (D19)
        self.servo_from              = 0
        self.servo_to                = 180
        self.servo_curr_angle        = 0.0
        self.servo_sweep_dir         = 1
        self.servo_sweep_running     = False
        self.servo_sweep_start_ticks = 0
        self._active_servo_pwm       = None
        self._active_servo_pin       = None

        # Feature 4: Live Sensor Test / HUD
        self.sensor_view_idx        = 0  # 0: ALL (S1..S3), 1: S1, 2: S2, 3: S3
        self.sensor_paused          = False

        # Physical Pushbutton State Machine (Clean non-blocking gesture detection)
        self.btn_screen = machine.Pin(hardware.BTN2, machine.Pin.IN, machine.Pin.PULL_UP)
        self.btn_start  = machine.Pin(hardware.BTN1, machine.Pin.IN, machine.Pin.PULL_UP)
        
        self.btn1_down              = False
        self.btn1_press_tick        = 0
        self.btn1_long_triggered    = False

        self.btn2_down              = False
        self.btn2_press_tick        = 0
        self.btn2_long_triggered    = False

        # I2C Bus & Display Initialization
        print("MGR: Initializing I2C Bus (SDA=21, SCL=22)...")
        self.i2c = None
        self.display = None
        self.ina219 = None

        try:
            self.i2c = machine.I2C(0, sda=machine.Pin(hardware.I2C_SDA), scl=machine.Pin(hardware.I2C_SCL), freq=400000)
            devices = self.i2c.scan()
            print("MGR: I2C Devices Found:", [hex(d) for d in devices])

            # INA219 Digital Power Monitor (0x40)
            if 0x40 in devices:
                try:
                    import ina219
                    self.ina219 = ina219.INA219(self.i2c, addr=0x40)
                    print("MGR: INA219 Power Monitor Initialized.")
                except Exception as e:
                    print("MGR: INA219 Init Warning:", e)

            # 1.3" OLED Display (SH1106 with SSD1306 fallback at 0x3C or 0x3D)
            oled_addr = next((d for d in [0x3C, 0x3D] if d in devices), None)
            if oled_addr:
                try:
                    import sh1106
                    self.display = sh1106.SH1106_I2C(128, 64, self.i2c, addr=oled_addr)
                    print(f"MGR: OLED 1.3\" Display (SH1106) Initialized at {hex(oled_addr)}.")
                except Exception as e:
                    try:
                        import ssd1306
                        self.display = ssd1306.SSD1306_I2C(128, 64, self.i2c, addr=oled_addr)
                        print(f"MGR: OLED Display (SSD1306) Initialized at {hex(oled_addr)}.")
                    except Exception as e2:
                        print("MGR: Display Init Error:", e2)
            else:
                print("MGR: OLED Display not found on I2C bus.")

        except Exception as e:
            print("MGR: I2C Init Error:", e)

        # Screensaver & Idle Timer (30 seconds)
        self.is_screensaver         = False
        self.last_activity_ticks    = time.ticks_ms()
        self.screensaver            = None
        try:
            import screensaver
            self.screensaver = screensaver.Screensaver(self.display)
            print("MGR: Screensaver Animation Engine Loaded.")
        except Exception as e:
            print("MGR: Screensaver Init Warning:", e)

        # Cyber Dinosaur Mascot Runner Mini-Game (7th Screen)
        self.runner_game = None
        try:
            import runner_game
            self.runner_game = runner_game.CyberRunnerGame(self.display)
            print("MGR: Cyber Runner Mini-Game Loaded.")
        except Exception as e:
            print("MGR: Runner Game Init Warning:", e)

        # Analog Sensor ADC Initializations (SN1, SN2, SN3)
        self.adc_s1 = None
        self.adc_s2 = None
        self.adc_s3 = None
        try:
            self.adc_s1 = machine.ADC(machine.Pin(hardware.SN1))
            self.adc_s1.atten(machine.ADC.ATTN_11DB)
            self.adc_s2 = machine.ADC(machine.Pin(hardware.SN2))
            self.adc_s2.atten(machine.ADC.ATTN_11DB)
            self.adc_s3 = machine.ADC(machine.Pin(hardware.SN3))
            self.adc_s3.atten(machine.ADC.ATTN_11DB)
        except Exception as e:
            print("MGR: Sensor ADC Init Warning:", e)

        # Show Original High-Fidelity TEN Robotics Splash Screen
        self.draw_logo()

        # Startup Chime Audio
        try:
            buzzer.play_startup()
        except Exception as e:
            print("Audio Init Warning:", e)

        # Hold boot logo for 1.2s for clean startup experience
        time.sleep_ms(1200)

        # Initialize Always-On Bluetooth (BLE) Manager
        self.ble_mgr = None
        try:
            import ble_manager
            self.ble_mgr = ble_manager.BLEManager(self)
            self.dev_name = self.ble_mgr.device_name
            self.bt_status = "ADV"
            print(f"MGR: Always-On Bluetooth Active ({self.dev_name}).")
        except Exception as e:
            print("MGR: BLE Init Warning:", e)

        # Initialize WiFi & WebSocket Server Engine
        self.wifi_mgr = None
        try:
            import wifi_manager
            self.wifi_mgr = wifi_manager.WiFiManager(self)
            print(f"MGR: WiFi WebSocket Server Active ({self.wifi_mgr.ip_address}:8266).")
        except Exception as e:
            print("MGR: WiFi Init Warning:", e)

        # Transition to initial interactive UI page
        self.render_active_page()

        # Serial Poller
        self._poller = select.poll()
        self._poller.register(sys.stdin, select.POLLIN)

    def draw_logo(self):
        """Render the official high-fidelity TEN Robotics logo splash screen."""
        if not self.display:
            return
        try:
            from logo import TEN_LOGO
            if hasattr(self.display, 'buffer'):
                self.display.buffer[:] = TEN_LOGO
            self.display.show()
        except Exception as e:
            try:
                self.display.fill(0)
                self.display.rect(2, 2, 124, 60, 1)
                self.display.text("TEN ROBOTICS", 16, 20, 1)
                self.display.text("ESP32 READY", 20, 38, 1)
                self.display.show()
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────────
    # Page Renderers
    # ─────────────────────────────────────────────────────────────────────────────

    def render_page_connection(self):
        """Page 0 (1/7: SYSTEM): Bluetooth, WiFi & Communication Status."""
        d = self.display
        if not d: return
        d.fill(0)
        d.fill_rect(0, 0, 128, 11, 1)
        d.text("1/7: SYSTEM", 20, 2, 0)

        d.text(f"BLE:{self.bt_status[:4]} {self.dev_name[11:15]}", 4, 16, 1)
        ip_s = self.wifi_mgr.ip_address if self.wifi_mgr else "192.168.4.1"
        d.text(f"IP :{ip_s}", 4, 30, 1)
        if self.prog_status == "RUNNING":
            st = "RUNNING"
        elif self.last_error == "NO CODE":
            st = "NO CODE"
        else:
            st = "READY"
        d.text(f"SYS:{st}", 4, 46, 1)
        d.show()

    def render_page_script(self):
        """Page 1 (2/7: PROGRAM): Existing Script & Execution Status."""
        d = self.display
        if not d: return
        d.fill(0)
        d.fill_rect(0, 0, 128, 11, 1)
        d.text("2/7: PROGRAM", 16, 2, 0)

        d.text("FILE: app.py", 6, 18, 1)
        try:
            fsize = os.stat("app.py")[6]
            size_str = f"{fsize} B"
        except Exception:
            size_str = "NONE"
            fsize = 0
        d.text(f"SIZE: {size_str[:9]}", 6, 33, 1)

        if self.prog_status == "RUNNING":
            elapsed = (time.ticks_diff(time.ticks_ms(), self.exec_start_ticks)) // 1000
            d.text(f"RUN : {elapsed}s", 6, 48, 1)
        elif self.last_error == "NO CODE" or fsize <= 0:
            d.text("STATUS: NO CODE", 6, 48, 1)
        elif self.last_error:
            err_s = str(self.last_error)[:8]
            d.text(f"ERR : {err_s}", 6, 48, 1)
        else:
            d.text("STATUS: READY", 6, 48, 1)

        d.show()

    def render_page_power(self):
        """Page 2 (3/7: BATTERY - 2S Li-ion): Power, Gauge & Low-Battery Alarm Setting."""
        d = self.display
        if not d: return
        d.fill(0)
        d.fill_rect(0, 0, 128, 11, 1)
        d.text("3/7: BATTERY (2S)", 4, 2, 0)

        d.text(f"PACK: {self.last_volts:.2f} V 2S", 6, 15, 1)
        if self.ina219:
            d.text(f"CURR: {int(self.last_ma)} mA", 6, 26, 1)
        else:
            d.text("CURR: N/A", 6, 26, 1)

        d.text("LOW BATT:", 6, 38, 1)
        if self.low_batt_alarm_enabled:
            d.fill_rect(82, 36, 40, 11, 1)
            d.text(" ON ", 86, 38, 0)
        else:
            d.rect(82, 36, 40, 11, 1)
            d.text(" OFF", 84, 38, 1)

        # Graphic Battery Bar
        d.rect(6, 51, 74, 10, 1)
        d.rect(80, 53, 3, 6, 1)
        fill_w = int((max(0, min(100, self.last_pct)) / 100.0) * 70)
        if fill_w > 0:
            d.fill_rect(8, 53, fill_w, 6, 1)
        pct_s = f"{self.last_pct}%"
        d.text(pct_s, 88, 52, 1)
        d.show()

    def render_page_motor_test(self):
        """Page 3 (4/7: MOTOR TEST): Interactive Hardware Motor Tester."""
        d = self.display
        if not d: return
        d.fill(0)
        d.fill_rect(0, 0, 128, 11, 1)
        d.text("4/7: MOTOR TEST", 4, 2, 0)

        mtr_names = ["M1 (LEFT)", "M2 (RIGHT)", "M3 (AUX)", "OUT (CH12)"]
        mtr_str = mtr_names[self.motor_test_idx]
        cur0 = "> " if self.motor_cursor == 0 else "  "
        d.text(f"{cur0}MTR:{mtr_str}", 4, 16, 1)

        spd_val = self.motor_test_speeds[self.motor_test_spd_idx]
        cur1 = "> " if self.motor_cursor == 1 else "  "
        dir_txt = "FWD" if spd_val > 0 else "REV"
        d.text(f"{cur1}SPD:{abs(spd_val):>3}% {dir_txt}", 4, 30, 1)

        if self.motor_test_running:
            d.fill_rect(4, 45, 120, 15, 1)
            dots = "." * ((time.ticks_ms() // 250) % 4)
            d.text(f"> RUNNING{dots:<3} <", 8, 49, 0)
        else:
            d.rect(4, 45, 120, 15, 1)
            d.text("    STOPPED    ", 8, 49, 1)

        d.show()

    def render_page_servo_test(self):
        """Page 4 (5/7: SERVO TEST): Interactive Servo Sweep Tester (Pins S1=18, S2=19)."""
        d = self.display
        if not d: return
        d.fill(0)
        d.fill_rect(0, 0, 128, 11, 1)
        d.text("5/7: SERVO TEST", 4, 2, 0)

        srv_name = "S1 (D18)" if self.servo_idx == 0 else "S2 (D19)"
        cur0 = "> " if self.servo_cursor == 0 else "  "
        d.text(f"{cur0}SRV:{srv_name}", 4, 15, 1)

        cur1 = "> " if self.servo_cursor == 1 else "  "
        d.text(f"{cur1}FROM: {self.servo_from:>3d} DEG", 4, 27, 1)

        cur2 = "> " if self.servo_cursor == 2 else "  "
        d.text(f"{cur2}TO  : {self.servo_to:>3d} DEG", 4, 39, 1)

        if self.servo_sweep_running:
            d.fill_rect(4, 51, 120, 12, 1)
            d.text(f"> SWEEP:{int(self.servo_curr_angle):>3d} <", 8, 53, 0)
        else:
            d.rect(4, 51, 120, 12, 1)
            d.text("    STOPPED    ", 8, 53, 1)

        d.show()

    def render_page_sensors(self):
        """Page 5 (6/7: SENSORS): Real-Time Live Analog Sensor Dashboard / HUD."""
        d = self.display
        if not d: return
        d.fill(0)
        d.fill_rect(0, 0, 128, 11, 1)
        mode_tag = "PAUSED" if self.sensor_paused else "LIVE"
        d.text(f"6/7: SENSORS ({mode_tag[:4]})", 4, 2, 0)

        if self.sensor_view_idx == 0:
            # Multi-Sensor Triple HUD (S1, S2, S3)
            readings = [
                ("S1", self.adc_s1.read() if self.adc_s1 else 0),
                ("S2", self.adc_s2.read() if self.adc_s2 else 0),
                ("S3", self.adc_s3.read() if self.adc_s3 else 0),
            ]
            y_offsets = [16, 30, 44]
            for i, (name, val) in enumerate(readings):
                y = y_offsets[i]
                d.text(name, 4, y, 1)
                d.rect(24, y, 54, 8, 1)
                bar_w = int((val / 4095.0) * 50)
                if bar_w > 0:
                    d.fill_rect(26, y + 2, bar_w, 4, 1)
                d.text(f"{val:>4}", 84, y, 1)
        else:
            # Single Sensor High-Precision Detail View
            s_num = self.sensor_view_idx
            adcs = [self.adc_s1, self.adc_s2, self.adc_s3]
            adc = adcs[s_num - 1]
            raw = adc.read() if adc else 0
            volts = round((raw / 4095.0) * 3.3, 2)
            pct = int((raw / 4095.0) * 100)

            d.text(f"PORT: SENSOR {s_num}", 6, 16, 1)
            d.text(f"RAW : {raw} / 4095", 6, 28, 1)
            d.text(f"VOLT: {volts:.2f} V", 6, 40, 1)

            # Horizontal Percentage Bar
            d.rect(6, 52, 72, 9, 1)
            bar_w = int((pct / 100.0) * 68)
            if bar_w > 0:
                d.fill_rect(8, 54, bar_w, 5, 1)
            d.text(f"{pct}%", 84, 53, 1)

        d.show()

    def render_active_page(self):
        """Render the currently active interactive page."""
        if not self.display or self.is_uploading or self._in_exec:
            return
        try:
            if self.current_page == 0:
                self.render_page_connection()
            elif self.current_page == 1:
                self.render_page_script()
            elif self.current_page == 2:
                self.render_page_power()
            elif self.current_page == 3:
                self.render_page_motor_test()
            elif self.current_page == 4:
                self.render_page_servo_test()
            elif self.current_page == 5:
                self.render_page_sensors()
            elif self.current_page == 6:
                if self.runner_game:
                    self.runner_game.update()
        except Exception as e:
            print("MGR: Render page error:", e)

    # ─────────────────────────────────────────────────────────────────────────────
    # Motor Test Driver Control
    # ─────────────────────────────────────────────────────────────────────────────

    def _apply_motor_test(self, idx, speed):
        self._stop_all_motors()
        if speed == 0:
            return
        pins = _MOTOR_PIN_MAP[idx]
        duty = int(abs(speed) / 100 * 1023)
        try:
            p1 = machine.PWM(machine.Pin(pins[0]), freq=1000)
            p2 = machine.PWM(machine.Pin(pins[1]), freq=1000)
            if speed > 0:
                p1.duty(duty)
                p2.duty(0)
            else:
                p1.duty(0)
                p2.duty(duty)
            self._active_motor_pwms = [p1, p2]
        except Exception as e:
            print("MGR: Motor test drive error:", e)

    def _stop_all_motors(self):
        if hasattr(self, '_active_motor_pwms') and self._active_motor_pwms:
            for p in self._active_motor_pwms:
                try:
                    p.duty(0)
                    p.deinit()
                except Exception:
                    pass
            self._active_motor_pwms = []
        for pin_num in [hardware.M1_IN1, hardware.M1_IN2, hardware.M2_IN1, hardware.M2_IN2, hardware.M3_IN1, hardware.M3_IN2, hardware.OUT1, hardware.OUT2]:
            try:
                machine.Pin(pin_num, machine.Pin.OUT).value(0)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────────
    # Interactive Button Handlers & Screensaver Wakeup
    # ─────────────────────────────────────────────────────────────────────────────

    def record_activity(self):
        """Record user activity to prevent or wake from screensaver."""
        self.last_activity_ticks = time.ticks_ms()
        if self.is_screensaver:
            self.wake_from_screensaver()

    def wake_from_screensaver(self):
        """Instant wake-up from screensaver on any interaction."""
        self.is_screensaver = False
        self.last_activity_ticks = time.ticks_ms()
        self.btn1_down = False
        self.btn2_down = False
        self.btn1_long_triggered = True  # Consume click on release
        self.btn2_long_triggered = True  # Consume click on release
        buzzer.tone(1200, 30)
        self.render_active_page()

    def _set_servo_angle(self, pin_num, deg):
        """Set 50Hz PWM angle (0 to 180 deg) on specified servo pin."""
        deg = max(0, min(180, int(deg)))
        ns = int(1_000_000 + (deg / 180) * 1_000_000)
        try:
            if not hasattr(self, '_active_servo_pwm') or self._active_servo_pwm is None or self._active_servo_pin != pin_num:
                self._stop_servo()
                self._active_servo_pwm = machine.PWM(machine.Pin(pin_num), freq=50)
                self._active_servo_pin = pin_num
            try:
                self._active_servo_pwm.duty_ns(ns)
            except AttributeError:
                duty = int(1023 * ns / 20_000_000)
                self._active_servo_pwm.duty(duty)
        except Exception as e:
            print("MGR: Servo drive error:", e)

    def _stop_servo(self):
        """Safely release PWM resources on servo pin."""
        if hasattr(self, '_active_servo_pwm') and self._active_servo_pwm:
            try:
                self._active_servo_pwm.duty(0)
                self._active_servo_pwm.deinit()
            except Exception:
                pass
            self._active_servo_pwm = None
            self._active_servo_pin = None

    def handle_btn2_long_press(self):
        """BTN2 Long Press (>500ms): Scroll cursor on Motor & Servo pages."""
        if self._in_exec or self.is_uploading:
            return
        if self.current_page == 3: # MOTOR TEST page
            self.motor_cursor = 1 if self.motor_cursor == 0 else 0
            buzzer.tone(1400, 35)
            self.render_active_page()
        elif self.current_page == 4: # SERVO TEST page
            self.servo_cursor = (self.servo_cursor + 1) % 3
            buzzer.tone(1400, 35)
            self.render_active_page()

    def handle_btn2_page_cycle(self):
        """BTN2: Cycle to Next Page."""
        # Safety: Stop any running motor test when switching pages
        if self.motor_test_running:
            self.motor_test_running = False
            self._stop_all_motors()

        # Safety: Stop any running servo sweep when switching pages
        if self.servo_sweep_running:
            self.servo_sweep_running = False
            self._stop_servo()

        self.current_page = (self.current_page + 1) % self.total_pages
        buzzer.play_button()
        self.render_active_page()

    def handle_btn1_short_click(self):
        """BTN1 Short Click: Contextual Action per Page (Instant, no double-click delay)."""
        if self._in_exec or self.is_uploading:
            return

        # Page 0: System -> Refresh / chime
        if self.current_page == 0:
            buzzer.play_button()
            self.render_active_page()

        # Page 1: Program -> Start / Stop Script
        elif self.current_page == 1:
            if self.prog_status == "RUNNING":
                self.stop_prog()
            else:
                self.start_prog()

        # Page 2: Battery -> Toggle Low Battery Alarm
        elif self.current_page == 2:
            self.low_batt_alarm_enabled = not self.low_batt_alarm_enabled
            if self.low_batt_alarm_enabled:
                buzzer.tone(1200, 50)
            else:
                buzzer.tone(600, 50)
            self.render_active_page()

        # Page 3: Motor Test -> Run / Stop Selected Motor
        elif self.current_page == 3:
            self.motor_test_running = not self.motor_test_running
            if self.motor_test_running:
                self.motor_test_start_ticks = time.ticks_ms()
                buzzer.play_run()
                spd = self.motor_test_speeds[self.motor_test_spd_idx]
                self._apply_motor_test(self.motor_test_idx, spd)
            else:
                buzzer.play_stop()
                self._stop_all_motors()
            self.render_active_page()

        # Page 4: Servo Test -> Run / Stop Sweep
        elif self.current_page == 4:
            self.servo_sweep_running = not self.servo_sweep_running
            if self.servo_sweep_running:
                self.servo_sweep_start_ticks = time.ticks_ms()
                self.servo_curr_angle = float(self.servo_from)
                self.servo_sweep_dir = 1
                buzzer.play_run()
            else:
                self._stop_servo()
                buzzer.play_stop()
            self.render_active_page()

        # Page 5: Sensors -> Pause / Resume Sampling
        elif self.current_page == 5:
            self.sensor_paused = not self.sensor_paused
            buzzer.play_button()
            self.render_active_page()

        # Page 6: Cyber Runner Game -> Jump / Restart
        elif self.current_page == 6:
            if self.runner_game:
                self.runner_game.on_btn1_action()

    def handle_btn1_long_press(self):
        """BTN1 Long Press (>500ms): Contextual Option Configuration."""
        if self._in_exec or self.is_uploading:
            return

        # Page 2: Battery -> Toggle Low Battery Alarm
        if self.current_page == 2:
            self.low_batt_alarm_enabled = not self.low_batt_alarm_enabled
            if self.low_batt_alarm_enabled:
                buzzer.tone(1400, 40)
            else:
                buzzer.tone(700, 40)
            self.render_active_page()

        # Page 3: Motor Test
        elif self.current_page == 3:
            if self.motor_cursor == 0:
                self.motor_test_idx = (self.motor_test_idx + 1) % len(_MOTOR_PIN_MAP)
                buzzer.tone(1600, 35)
                if self.motor_test_running:
                    spd = self.motor_test_speeds[self.motor_test_spd_idx]
                    self._apply_motor_test(self.motor_test_idx, spd)
            else:
                self.motor_test_spd_idx = (self.motor_test_spd_idx + 1) % len(self.motor_test_speeds)
                spd = self.motor_test_speeds[self.motor_test_spd_idx]
                buzzer.tone(900 + abs(spd) * 8, 35)
                if self.motor_test_running:
                    self._apply_motor_test(self.motor_test_idx, spd)
            self.render_active_page()

        # Page 4: Servo Test
        elif self.current_page == 4:
            if self.servo_cursor == 0:
                self.servo_idx = 1 if self.servo_idx == 0 else 0
                buzzer.tone(1500, 35)
            elif self.servo_cursor == 1:
                self.servo_from = (self.servo_from + 10) % 190
                buzzer.tone(900 + self.servo_from * 5, 30)
                pin = hardware.S1 if self.servo_idx == 0 else hardware.S2
                self._set_servo_angle(pin, self.servo_from)
            elif self.servo_cursor == 2:
                self.servo_to = (self.servo_to + 10) % 190
                buzzer.tone(900 + self.servo_to * 5, 30)
                pin = hardware.S1 if self.servo_idx == 0 else hardware.S2
                self._set_servo_angle(pin, self.servo_to)
            self.render_active_page()

        # Page 5: Sensors
        elif self.current_page == 5:
            self.sensor_view_idx = (self.sensor_view_idx + 1) % 4
            buzzer.tone(1800, 40)
            self.render_active_page()

    def poll_buttons(self):
        """High-responsiveness physical button polling state machine."""
        now = time.ticks_ms()

        # If screensaver is active, any button press wakes up immediately
        if self.is_screensaver:
            btn1_val = self.btn_start.value()
            btn2_val = self.btn_screen.value()
            if btn1_val == 0 or btn2_val == 0:
                self.wake_from_screensaver()
                return

        # BTN2: Page Switch & Scroll Button (Active Low, GPIO 17)
        btn2_val = self.btn_screen.value()
        if btn2_val == 0:
            self.last_activity_ticks = now
            if not self.btn2_down:
                self.btn2_down = True
                self.btn2_press_tick = now
                self.btn2_long_triggered = False
            else:
                if not self.btn2_long_triggered and time.ticks_diff(now, self.btn2_press_tick) > 500:
                    self.btn2_long_triggered = True
                    self.handle_btn2_long_press()
        else:
            if self.btn2_down:
                self.btn2_down = False
                if not self.btn2_long_triggered:
                    dur = time.ticks_diff(now, self.btn2_press_tick)
                    if dur > 40:
                        self.handle_btn2_page_cycle()

        # BTN1: Contextual Action Button (Active Low, GPIO 16)
        if not self._in_exec and not self.is_uploading:
            btn1_val = self.btn_start.value()
            if btn1_val == 0:
                self.last_activity_ticks = now
                if not self.btn1_down:
                    self.btn1_down = True
                    self.btn1_press_tick = now
                    self.btn1_long_triggered = False
                else:
                    if not self.btn1_long_triggered and time.ticks_diff(now, self.btn1_press_tick) > 500:
                        self.btn1_long_triggered = True
                        self.handle_btn1_long_press()
            else:
                if self.btn1_down:
                    self.btn1_down = False
                    if not self.btn1_long_triggered:
                        dur = time.ticks_diff(now, self.btn1_press_tick)
                        if dur > 40:
                            self.handle_btn1_short_click()

    def poll_ui(self):
        """Dynamic UI refresh rate according to state."""
        now = time.ticks_ms()

        game_active = (self.current_page == 6 and self.runner_game and self.runner_game.state == "PLAYING")
        if self.motor_test_running or self.servo_sweep_running or self._in_exec or self.is_uploading or self.prog_status == "RUNNING" or game_active:
            self.last_activity_ticks = now

        # Idle timeout for screensaver (30 seconds)
        if not self.is_screensaver and not self._in_exec and not self.is_uploading and self.prog_status != "RUNNING" and not self.motor_test_running and not self.servo_sweep_running and not game_active:
            if time.ticks_diff(now, self.last_activity_ticks) >= 30000:
                self.is_screensaver = True
                if self.screensaver:
                    self.screensaver.start_random()

        if self.is_screensaver:
            if self.screensaver and time.ticks_diff(now, self.last_ui_refresh) >= 60:
                self.last_ui_refresh = now
                self.screensaver.update()
            return

        # Motor auto-stop timeout
        if self.motor_test_running:
            if time.ticks_diff(now, self.motor_test_start_ticks) > 15000:
                self.motor_test_running = False
                self._stop_all_motors()
                buzzer.play_stop()
                self.render_active_page()

        # Servo sweep update
        if self.servo_sweep_running:
            if time.ticks_diff(now, self.servo_sweep_start_ticks) > 30000:
                self.servo_sweep_running = False
                self._stop_servo()
                buzzer.play_stop()
                self.render_active_page()
            else:
                step_amt = 4 if self.servo_to >= self.servo_from else -4
                self.servo_curr_angle += (step_amt * self.servo_sweep_dir)
                low = min(self.servo_from, self.servo_to)
                high = max(self.servo_from, self.servo_to)
                if self.servo_curr_angle >= high:
                    self.servo_curr_angle = float(high)
                    self.servo_sweep_dir = -1
                elif self.servo_curr_angle <= low:
                    self.servo_curr_angle = float(low)
                    self.servo_sweep_dir = 1
                
                pin = hardware.S1 if self.servo_idx == 0 else hardware.S2
                self._set_servo_angle(pin, int(self.servo_curr_angle))

        is_fast_page = (self.current_page == 5 and not self.sensor_paused) or self.motor_test_running or self.servo_sweep_running or (self.current_page == 6)
        refresh_rate = 50 if self.current_page == 6 else (30 if self.servo_sweep_running else (150 if is_fast_page else 500))

        if time.ticks_diff(now, self.last_ui_refresh) >= refresh_rate:
            self.last_ui_refresh = now
            if not self._in_exec and not self.is_uploading:
                self.render_active_page()

    def start(self):
        print("MGR: System Started.")

    def write_out(self, data):
        """Sends data out over BLE, WiFi WebSocket, and USB Serial."""
        if not data:
            return
        payload = data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")
        text = payload.decode("utf-8", "ignore")
        if self.wifi_mgr:
            try:
                self.wifi_mgr.send_broadcast(payload)
            except Exception:
                pass
        if self.ble_mgr and getattr(self.ble_mgr, 'is_connected', False):
            try:
                self.ble_mgr.send_console(payload)
            except Exception:
                pass
        if getattr(self, 'serial_active', True):
            try:
                sys.stdout.write(text)
            except Exception:
                pass

    def send_ble_data(self, data):
        """Send raw console bytes over BLE characteristic."""
        if self.ble_mgr:
            try:
                self.ble_mgr.send_console(data)
            except Exception:
                pass

    def ingest_data(self, data_chunk, source="SERIAL"):
        """Central parser for lines/commands coming from Serial, BLE, or WiFi."""
        if source == "BLE":
            buf = self._ble_buf
        elif source == "WIFI":
            buf = self._wifi_buf
        else:
            buf = self._serial_buf

        if len(buf) > 8192:
            buf[:] = bytearray()
        buf.extend(data_chunk)

        if b'\n' not in buf:
            return

        parts = buf.split(b'\n')
        buf[:] = parts.pop()

        for line_bytes in parts:
            try:
                line_str = line_bytes.decode("utf-8").rstrip("\r")
            except Exception:
                line_str = ""

            self._process_command_or_line(line_str, line_bytes)

    def _process_command_or_line(self, line_str, raw_bytes):
        cmd = line_str.strip()

        # Handle Protocol Control Commands
        if cmd == "CLEAR":
            if self._upload_file:
                try: self._upload_file.close()
                except Exception: pass
                self._upload_file = None
            self.is_uploading = False
            self.write_out("STATUS:READY\n")
            self.render_active_page()

        elif cmd == "STOP":
            self.stop_prog()
            self.write_out("STATUS:STOPPED\n")

        elif cmd == "START" or cmd == "RUN":
            self.start_prog()
            self.write_out("STATUS:RUNNING\n")

        elif cmd == "SYNC":
            self.write_out(f"STATUS:{self.prog_status}\n")
            self.poll_power_telemetry(force=True)

        elif cmd == "SERIAL_ON":
            self.serial_active = True
            self.write_out("SERIAL:ON\n")

        elif cmd == "PAGE":
            self.handle_btn2_page_cycle()

        elif cmd.startswith("BEGIN_UPLOAD"):
            # Format: BEGIN_UPLOAD:total_lines:filename
            parts = cmd.split(":")
            total_lines = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            filename = parts[2] if len(parts) > 2 and parts[2] else "app.py"

            self._upload_total_lines = total_lines
            self._upload_current_line = 0
            self._upload_target_file = filename
            self.is_uploading = True

            if self._upload_file:
                try: self._upload_file.close()
                except Exception: pass

            try:
                self._upload_file = open(filename, "w")
            except Exception as e:
                print(f"MGR: Upload open error: {e}")
                self.write_out("UPLOAD:ERR\n")
                return

            # Respond immediately to client so handshake succeeds with zero latency
            self.write_out("UPLOAD:READY\n")

            if self.display:
                try:
                    d = self.display
                    d.fill(0)
                    d.fill_rect(0, 0, 128, 12, 1)
                    d.text("DOWNLOADING", 18, 2, 0)
                    d.text(f"FILE: {filename[:10]}", 6, 22, 1)
                    d.text("0%", 56, 38, 1)
                    d.rect(14, 52, 100, 8, 1)
                    d.show()
                except Exception:
                    pass

        elif self.is_uploading and self._upload_file:
            # Write line of code to target file
            try:
                self._upload_file.write(line_str + "\n")
                self._upload_current_line += 1

                pct = 100
                if self._upload_total_lines > 0:
                    pct = min(100, int((self._upload_current_line / self._upload_total_lines) * 100))

                now = time.ticks_ms()
                is_done = (self._upload_total_lines > 0 and self._upload_current_line >= self._upload_total_lines)

                # Throttle display refresh to at most once per 200ms or on completion
                if self.display and (time.ticks_diff(now, self._last_upload_ui_update) >= 200 or is_done):
                    self._last_upload_ui_update = now
                    try:
                        d = self.display
                        d.fill(0)
                        d.fill_rect(0, 0, 128, 12, 1)
                        d.text("DOWNLOADING", 18, 2, 0)
                        pct_s = f"{pct}%"
                        px = max(0, (128 - len(pct_s) * 8) // 2)
                        d.text(pct_s, px, 24, 1)
                        d.text(f"{self._upload_current_line}/{self._upload_total_lines}", 36, 38, 1)
                        d.rect(14, 52, 100, 8, 1)
                        fill_w = int(pct * 96 / 100)
                        if fill_w > 0:
                            d.fill_rect(16, 54, fill_w, 4, 1)
                        d.show()
                    except Exception:
                        pass

                self.write_out("UPLOAD:OK\n")

                if is_done:
                    self._upload_file.close()
                    self._upload_file = None
                    self.is_uploading = False
                    self.write_out("UPLOAD:DONE\n")
                    buzzer.tone(1500, 60)
                    self.render_active_page()

            except Exception as e:
                print(f"MGR: Upload write error: {e}")
                self.write_out("UPLOAD:ERR\n")

    def poll_serial(self):
        """Poll incoming serial stream and WiFi socket without blocking."""
        if self.wifi_mgr:
            try:
                self.wifi_mgr.poll()
            except Exception:
                pass
        events = self._poller.poll(0)
        if events:
            self.record_activity()
            try:
                chunk = sys.stdin.read(1)
                while chunk:
                    self.ingest_data(chunk.encode("utf-8"), source="SERIAL")
                    if not self._poller.poll(0):
                        break
                    chunk = sys.stdin.read(1)
            except Exception:
                pass

    def poll_power_telemetry(self, force=False):
        """Read voltage/current, update live stats, low-battery alert, and broadcast telemetry."""
        if self.is_uploading and not force:
            return
        now = time.ticks_ms()
        if force or time.ticks_diff(now, self.last_power_telemetry) >= 2000:
            self.last_power_telemetry = now
            try:
                if self.ina219:
                    volts = round(self.ina219.get_bus_voltage_V(), 2)
                    current_ma = round(self.ina219.get_current_mA(), 1)
                    power_w = round(volts * (current_ma / 1000.0), 2)
                else:
                    adc = machine.ADC(machine.Pin(hardware.SN4))
                    raw = adc.read()
                    volts = round((raw / 4095.0) * 3.3 * 4.0, 2)
                    current_ma = 0.0
                    power_w = 0.0

                # 2S Li-ion Battery Calibration: 6.0V (0%) to 8.4V (100%)
                pct = max(0, min(100, int((volts - 6.0) / (8.4 - 6.0) * 100)))

                self.last_volts = volts
                self.last_pct   = pct
                self.last_ma    = current_ma

                # Low-Battery Warning Alarm for 2S Li-ion:
                if self.low_batt_alarm_enabled and 4.5 < volts < 6.8:
                    if time.ticks_diff(now, self.last_low_batt_beep) > 12000:
                        self.last_low_batt_beep = now
                        buzzer.tone(440, 50)
                        time.sleep_ms(30)
                        buzzer.tone(440, 50)

                # Send Dual Telemetry format for universal App compatibility
                telemetry_json = f"POWER:{{\"v\":{volts},\"pct\":{pct},\"ma\":{current_ma},\"p\":{power_w}}}\n"
                telemetry_raw  = f"POWER:V={volts},I={current_ma},P={power_w},B={pct}\n"
                
                self.write_out(telemetry_json)
                self.write_out(telemetry_raw)
            except Exception:
                pass

    def start_prog(self):
        """Safely starts script execution, with zero-freeze guard if app.py is missing."""
        if self.is_uploading:
            return

        try:
            fsize = os.stat("app.py")[6]
        except Exception:
            fsize = 0

        if fsize <= 0:
            print("MGR: Start aborted — app.py not found or empty!")
            self.prog_status = "STOPPED"
            self._in_exec = False
            self.last_error = "NO CODE"
            buzzer.play_error()
            self.write_out("ERR:No code uploaded in app.py\n")
            self.write_out("STATUS:STOPPED\n")
            self.render_active_page()
            return

        self.prog_status = "RUNNING"
        self.exec_start_ticks = time.ticks_ms()
        self._in_exec = True
        buzzer.play_run()
        self.write_out("STATUS:RUNNING\n")
        print(f"MGR: Program Execution Started (Session {self.exec_start_ticks})")
        self.render_active_page()

    def stop_prog(self, err=None):
        self.prog_status = "STOPPED"
        self._in_exec = False
        self.last_error = str(err) if err else None
        buzzer.play_stop()
        self.write_out("STATUS:STOPPED\n")
        print("MGR: Program Execution Stopped.")

        # Safety reset for motor and output pins
        self._stop_all_motors()
        self._stop_servo()

        # Return to currently active page
        if self.display and not self.is_uploading:
            self.render_active_page()

# Global Singleton Manager instance
manager = StoreManager()

def start():
    if manager:
        manager.start()
