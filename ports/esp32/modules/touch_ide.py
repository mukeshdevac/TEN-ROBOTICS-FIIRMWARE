"""
TEN Robotics - Native On-Device 3-Screen Touch IDE for ESP32-S3 & 3.5" ILI9488
Enables standalone, laptop-free coding directly on the 480x320 touch display.
"""

import time
import gc
import os
import sys

# Category & UI Colors (RGB565)
COLOR_MOTION  = 0x4CBF # Blue
COLOR_CONTROL = 0xFC00 # Orange
COLOR_SENSOR  = 0x07FF # Cyan
COLOR_DISPLAY = 0xA21F # Purple
COLOR_CYAN    = 0x07FF
COLOR_ORANGE  = 0xFD20
COLOR_GREEN   = 0x07E0
COLOR_RED     = 0xF800
COLOR_BG      = 0x10A2
COLOR_WHITE   = 0xFFFF
COLOR_BLACK   = 0x0000

# Pre-defined Block Templates (Matching Desktop React Blockly IDE)
BLOCK_CATEGORIES = ["MOTION", "CONTROL", "SENSORS", "DISPLAY"]

PALETTE_BLOCKS = {
    "MOTION": [
        {"label": "Motor 1 FWD 100", "code": "Motor(1).drive(100)"},
        {"label": "Motor 1 REV 100", "code": "Motor(1).drive(-100)"},
        {"label": "Motor 1 STOP",    "code": "Motor(1).drive(0)"},
        {"label": "Servo 1 Angle 90", "code": "Servo(1).angle(90)"},
        {"label": "Servo 1 Angle 180","code": "Servo(1).angle(180)"},
        {"label": "Servo 1 Center",   "code": "Servo(1).angle(90)"},
    ],
    "CONTROL": [
        {"label": "Sleep 1 Second",  "code": "time.sleep(1)"},
        {"label": "Sleep 500 ms",    "code": "time.sleep_ms(500)"},
        {"label": "Sleep 100 ms",    "code": "time.sleep_ms(100)"},
        {"label": "Repeat 5 Times",  "code": "for _ in range(5):"},
        {"label": "While True Loop", "code": "while True:"},
    ],
    "SENSORS": [
        {"label": "Read Sensor 1",   "code": "s1 = Sensor(1).read_pct()"},
        {"label": "Read Sensor 2",   "code": "s2 = Sensor(2).read_pct()"},
        {"label": "Read Distance",   "code": "dist = ten.read_ultrasonic()"},
    ],
    "DISPLAY": [
        {"label": "Emoji Smile",    "code": "display.emoji('smile')"},
        {"label": "Emoji Skull",    "code": "display.emoji('skull')"},
        {"label": "Emoji Heart",    "code": "display.emoji('heart')"},
        {"label": "Print Hello",    "code": "display.text('Hello TEN!')"},
        {"label": "Clear Screen",   "code": "display.clear()"},
    ]
}

class TouchIDE:
    def __init__(self, tft, touch, store_mgr=None):
        self.tft = tft
        self.touch = touch
        self.mgr = store_mgr
        self.current_screen = 0 # 0 = Home, 1 = Touch IDE, 2 = Execution Live Monitor
        
        self.active_category = "MOTION"
        self.user_code_lines = [
            "Motor(1).drive(100)",
            "time.sleep(1)",
            "Motor(1).drive(0)",
            "display.emoji('smile')"
        ]
        self.selected_line_idx = len(self.user_code_lines) - 1
        self.last_touch_time = 0
        self.stop_requested = False

    def draw_home_screen(self):
        """Screen 0: Home Dashboard & Mode Selection."""
        self.tft.fill(0x0842) # Deep Dark
        # Header Banner
        self.tft.fill_rect(0, 0, 480, 45, 0x18C6)
        self.tft.text("TE[O]N ROBOTICS - ESP32-S3 (N16R8)", 15, 12, COLOR_WHITE, scale=2)
        self.tft.fill_rect(0, 45, 480, 2, COLOR_CYAN)

        # Status Cards
        # Card 1: RAM/PSRAM
        self.tft.fill_rect(20, 60, 215, 75, COLOR_BG)
        self.tft.rect(20, 60, 215, 75, COLOR_CYAN)
        self.tft.text("PSRAM & HEAP", 30, 70, COLOR_CYAN, scale=1)
        psram_free = gc.mem_free() / 1024
        self.tft.text(f"FREE: {psram_free:.1f} KB", 30, 95, COLOR_WHITE, scale=2)

        # Card 2: CPU & SYSTEM
        self.tft.fill_rect(245, 60, 215, 75, COLOR_BG)
        self.tft.rect(245, 60, 215, 75, COLOR_GREEN)
        self.tft.text("CPU & HARDWARE", 255, 70, COLOR_GREEN, scale=1)
        self.tft.text("240MHz / 16MB", 255, 95, COLOR_WHITE, scale=2)

        # Main Navigation Touch Cards
        # Button 1: Standalone Touch IDE
        self.tft.draw_button(20, 150, 440, 48, "💻 ON-DEVICE TOUCH IDE", bg_color=0x0208, fg_color=COLOR_WHITE, border_color=COLOR_CYAN, scale=2)

        # Button 2: Wireless Sync Mode (BLE / Web IDE)
        self.tft.draw_button(20, 208, 440, 48, "📲 WIRELESS BLE SYNC MODE", bg_color=0x0208, fg_color=COLOR_WHITE, border_color=COLOR_ORANGE, scale=2)

        # Button 3: Run Saved Script Directly
        self.tft.draw_button(20, 266, 440, 44, "▶️ RUN SAVED SCRIPT (app.py)", bg_color=0x03E0, fg_color=COLOR_WHITE, border_color=COLOR_GREEN, scale=2)

    def draw_ide_screen(self):
        """Screen 1: Visual Touch Blockly & Code Builder IDE."""
        self.tft.fill(COLOR_BLACK)
        
        # 1. Top Category Bar (y: 0..35)
        cat_w = 480 // len(BLOCK_CATEGORIES)
        for i, cat in enumerate(BLOCK_CATEGORIES):
            x = i * cat_w
            bg = COLOR_CYAN if cat == self.active_category else COLOR_BG
            fg = COLOR_BLACK if cat == self.active_category else COLOR_WHITE
            self.tft.fill_rect(x, 0, cat_w - 2, 35, bg)
            self.tft.text(cat, x + 10, 10, fg, scale=1)

        # 2. Left Palette Panel (x: 0..170, y: 38..270)
        self.tft.fill_rect(0, 38, 170, 232, 0x1084)
        self.tft.rect(0, 38, 170, 232, COLOR_CYAN)
        self.tft.text("BLOCK PALETTE", 10, 45, COLOR_CYAN, scale=1)
        
        blocks = PALETTE_BLOCKS.get(self.active_category, [])
        for idx, blk in enumerate(blocks[:5]):
            by = 65 + idx * 38
            self.tft.draw_button(5, by, 160, 34, blk["label"][:14], bg_color=0x2104, fg_color=COLOR_WHITE, border_color=COLOR_WHITE, scale=1)

        # 3. Right Code Canvas (x: 175..475, y: 38..270)
        self.tft.fill_rect(175, 38, 300, 232, COLOR_BG)
        self.tft.rect(175, 38, 300, 232, COLOR_GREEN)
        self.tft.text("CODE WORKSPACE (app.py)", 185, 45, COLOR_GREEN, scale=1)

        for line_i, code_str in enumerate(self.user_code_lines[-8:]):
            ly = 65 + line_i * 24
            is_sel = (line_i == self.selected_line_idx)
            color = COLOR_GREEN if is_sel else COLOR_WHITE
            prefix = "> " if is_sel else f"{line_i+1}: "
            self.tft.text(f"{prefix}{code_str[:22]}", 185, ly, color, scale=1)

        # 4. Bottom Toolbar (y: 275..318)
        self.tft.draw_button(5, 275, 90, 40, "🏠 Home", bg_color=COLOR_BG, fg_color=COLOR_WHITE, border_color=COLOR_CYAN, scale=1)
        self.tft.draw_button(100, 275, 90, 40, "🗑️ Del", bg_color=COLOR_BG, fg_color=COLOR_WHITE, border_color=COLOR_RED, scale=1)
        self.tft.draw_button(195, 275, 90, 40, "💾 Save", bg_color=COLOR_BG, fg_color=COLOR_WHITE, border_color=COLOR_ORANGE, scale=1)
        self.tft.draw_button(290, 275, 185, 40, "▶️ RUN CODE", bg_color=0x0400, fg_color=COLOR_WHITE, border_color=COLOR_GREEN, scale=2)

    def draw_execution_screen(self):
        """Screen 2: Live Execution Monitor with PERSISTENT RED TOUCH STOP BUTTON."""
        self.tft.fill(COLOR_BLACK)
        
        # Live Execution Header
        self.tft.fill_rect(0, 0, 480, 45, 0x0208)
        self.tft.text("STATUS: EXECUTING CODE...", 15, 12, COLOR_GREEN, scale=2)
        self.tft.fill_rect(0, 45, 480, 2, COLOR_GREEN)

        # Live Graphic / Avatar Area
        self.tft.fill_rect(20, 60, 440, 160, COLOR_BG)
        self.tft.rect(20, 60, 440, 160, COLOR_CYAN)
        
        # Animated Emoji Eyes inside Monitor Box
        self.tft.fill_rect(160, 100, 50, 50, COLOR_CYAN)
        self.tft.fill_rect(270, 100, 50, 50, COLOR_CYAN)
        self.tft.fill_rect(175, 115, 20, 20, COLOR_BLACK)
        self.tft.fill_rect(285, 115, 20, 20, COLOR_BLACK)
        self.tft.text("ROBOT ACTIVE", 170, 175, COLOR_WHITE, scale=2)

        # PERSISTENT RED TOUCH STOP BUTTON (y: 235..310)
        self.draw_persistent_stop_button()

    def draw_persistent_stop_button(self):
        """Render prominent Red Touch STOP Button."""
        self.tft.fill_rect(20, 235, 440, 75, COLOR_RED)
        self.tft.rect(20, 235, 440, 75, COLOR_WHITE)
        self.tft.text("⏹️ TOUCH TO STOP CODE", 65, 260, COLOR_WHITE, scale=3)

    def save_script(self):
        """Save student workspace code lines to app.py on Flash FS."""
        try:
            with open("app.py", "w") as f:
                f.write("import machine, time, ten\n")
                f.write("from ten import Motor, Servo, Sensor, display\n\n")
                for line in self.user_code_lines:
                    f.write(line + "\n")
            print("IDE: app.py saved successfully.")
        except Exception as e:
            print("IDE: Save failed:", e)

    def handle_touch_event(self, touch_pos):
        """Process touch input depending on active screen."""
        if not touch_pos:
            return
        x, y = touch_pos
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_touch_time) < 250:
            return # Debounce 250ms
        self.last_touch_time = now

        # Screen 0: Home Dashboard
        if self.current_screen == 0:
            if 20 <= x <= 460 and 150 <= y <= 198:
                self.current_screen = 1 # Open Touch IDE
                self.draw_ide_screen()
            elif 20 <= x <= 460 and 208 <= y <= 256:
                if self.mgr: self.mgr.bt_status = "PAIRING"
                self.tft.draw_button(20, 208, 440, 48, "BLE PAIRING ACTIVE...", bg_color=COLOR_ORANGE, fg_color=COLOR_WHITE, scale=2)
            elif 20 <= x <= 460 and 266 <= y <= 310:
                self.current_screen = 2 # Start Execution
                self.draw_execution_screen()
                if self.mgr: self.mgr.pending_start = True

        # Screen 1: Touch IDE Builder
        elif self.current_screen == 1:
            # Top Category Tabs
            if y < 35:
                cat_w = 480 // len(BLOCK_CATEGORIES)
                cat_idx = x // cat_w
                if cat_idx < len(BLOCK_CATEGORIES):
                    self.active_category = BLOCK_CATEGORIES[cat_idx]
                    self.draw_ide_screen()
            # Block Palette Taps (Left Panel)
            elif 0 <= x <= 170 and 65 <= y <= 260:
                block_idx = (y - 65) // 38
                blocks = PALETTE_BLOCKS.get(self.active_category, [])
                if block_idx < len(blocks):
                    selected_code = blocks[block_idx]["code"]
                    self.user_code_lines.append(selected_code)
                    self.selected_line_idx = len(self.user_code_lines) - 1
                    self.draw_ide_screen()
            # Bottom Toolbar Taps
            elif y >= 275:
                if 5 <= x <= 95: # Home
                    self.current_screen = 0
                    self.draw_home_screen()
                elif 100 <= x <= 190: # Delete
                    if self.user_code_lines:
                        self.user_code_lines.pop()
                        self.selected_line_idx = max(0, len(self.user_code_lines) - 1)
                        self.draw_ide_screen()
                elif 195 <= x <= 285: # Save
                    self.save_script()
                    self.tft.draw_button(195, 275, 90, 40, "SAVED!", bg_color=COLOR_GREEN, fg_color=COLOR_WHITE, scale=1)
                elif 290 <= x <= 475: # Run Code
                    self.save_script()
                    self.current_screen = 2
                    self.draw_execution_screen()
                    if self.mgr: self.mgr.pending_start = True

        # Screen 2: Execution & Live Monitor
        elif self.current_screen == 2:
            # Check Touch on Persistent RED STOP Button (y: 235..310)
            if 20 <= x <= 460 and 235 <= y <= 310:
                print("IDE: TOUCH STOP TRIGGERED BY USER!")
                self.stop_requested = True
                if self.mgr:
                    self.mgr.stop_prog()
                self.current_screen = 0
                self.draw_home_screen()

    def check_stop_touch(self):
        """Called inside script execution loop to detect instant Touch STOP."""
        if not self.touch:
            return False
        pos = self.touch.get_touch()
        if pos:
            x, y = pos
            if 20 <= x <= 460 and 235 <= y <= 310:
                print("IDE: EMERGENCY TOUCH STOP PRESSED!")
                self.stop_requested = True
                return True
        return False
