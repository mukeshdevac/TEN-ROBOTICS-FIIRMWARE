"""
TEN Robotics ESP32 DevKit V1 - Mascot Robot Screensaver & Animation Library
Dedicated to the iconic TEN Robotics Robot Mascot between 'TE' and 'N'
(with horns on head, expressive eyes, heart panel, arms, and stepping legs).

5 Dynamic Mascot Animations:
  0: Waving Mascot Greeting (raising hand, waving, blinking eyes)
  1: Dancing & Stepping Mascot (stepping feet, swinging arms, head sway)
  2: Horn Radio Wave Broadcast (concentric telemetry transmission arcs from horns)
  3: Jumping Mascot Leap (crouch, leap above logo with victory arms, soft landing)
  4: Rover Mascot Walk (mascot walks across entire OLED display, pauses & waves)
"""

import time
import math
try:
    import urandom as random
except ImportError:
    import random

from logo import TEN_LOGO


class Screensaver:
    def __init__(self, display):
        self.display = display
        self.width = 128
        self.height = 64
        self.anim_idx = 0
        self.anim_count = 5
        self.frame = 0
        self.anim_start_tick = 0

        # Walking rover mascot state (Anim 4)
        self.rover_x = 10.0
        self.rover_dir = 1
        self.rover_state = "walk" # walk, wave
        self.rover_wait = 0

    def start_random(self):
        """Pick a new random mascot animation upon entering screensaver."""
        self.anim_idx = random.randint(0, self.anim_count - 1)
        self.frame = 0
        self.anim_start_tick = time.ticks_ms()
        self.rover_x = 10.0
        self.rover_dir = 1
        self.rover_state = "walk"

    def update(self):
        """Render the next frame of the active mascot animation."""
        if not self.display:
            return

        now = time.ticks_ms()
        # Automatically cycle to another random mascot animation every 14 seconds
        if time.ticks_diff(now, self.anim_start_tick) > 14000:
            new_idx = random.randint(0, self.anim_count - 1)
            if new_idx == self.anim_idx:
                new_idx = (new_idx + 1) % self.anim_count
            self.anim_idx = new_idx
            self.frame = 0
            self.anim_start_tick = now
            self.rover_x = 10.0
            self.rover_dir = 1
            self.rover_state = "walk"

        self.frame += 1

        try:
            if self.anim_idx == 0:
                self._anim_mascot_wave()
            elif self.anim_idx == 1:
                self._anim_mascot_dance()
            elif self.anim_idx == 2:
                self._anim_mascot_radio_horns()
            elif self.anim_idx == 3:
                self._anim_mascot_jumping_joy()
            elif self.anim_idx == 4:
                self._anim_mascot_walker_rover()
        except Exception as e:
            print("Screensaver render error:", e)

    # ─────────────────────────────────────────────────────────────────────────
    # Core Robot Mascot Drawing Engine
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_mascot(self, ox, oy, arm_l_mode=0, arm_r_mode=0, leg_mode=0, eye_mode=0, horn_wave=0):
        """
        Renders the official TEN Robotics Mascot at origin (ox, oy).
        ox, oy is the top-left of the mascot (normally 73, 16).
        """
        d = self.display

        # 1. Horns / Antenna on head
        # Left horn
        d.pixel(ox + 5, oy, 1)
        d.pixel(ox + 6, oy, 1)
        d.pixel(ox + 6, oy + 1, 1)
        d.pixel(ox + 7, oy + 1, 1)
        d.pixel(ox + 7, oy + 2, 1)
        # Right horn
        d.pixel(ox + 16, oy, 1)
        d.pixel(ox + 15, oy + 1, 1)
        d.pixel(ox + 16, oy + 1, 1)
        d.pixel(ox + 14, oy + 2, 1)
        d.pixel(ox + 15, oy + 2, 1)

        # Horn radio telemetry signal arcs
        if horn_wave > 0:
            hw = horn_wave % 4
            if hw >= 1:
                d.pixel(ox + 4, oy - 2, 1)
                d.pixel(ox + 17, oy - 2, 1)
            if hw >= 2:
                d.pixel(ox + 3, oy - 4, 1)
                d.pixel(ox + 18, oy - 4, 1)
                d.pixel(ox + 2, oy - 3, 1)
                d.pixel(ox + 19, oy - 3, 1)
            if hw >= 3:
                d.pixel(ox + 1, oy - 6, 1)
                d.pixel(ox + 20, oy - 6, 1)
                d.pixel(ox + 5, oy - 6, 1)
                d.pixel(ox + 16, oy - 6, 1)

        # 2. Head Box (12x7 pixels)
        d.fill_rect(ox + 5, oy + 3, 12, 7, 1)
        # Face Cutout (8x3 pixels)
        d.fill_rect(ox + 7, oy + 5, 8, 3, 0)

        # Eyes inside face
        if eye_mode == 1:
            # Blink (closed eyes)
            d.hline(ox + 7, oy + 6, 8, 1)
        elif eye_mode == 2:
            # Looking left
            d.pixel(ox + 7, oy + 6, 1)
            d.pixel(ox + 12, oy + 6, 1)
        elif eye_mode == 3:
            # Looking right
            d.pixel(ox + 9, oy + 6, 1)
            d.pixel(ox + 14, oy + 6, 1)
        else:
            # Normal centered eyes
            d.pixel(ox + 8, oy + 6, 1)
            d.pixel(ox + 13, oy + 6, 1)

        # 3. Body / Torso (12x8 pixels)
        d.fill_rect(ox + 5, oy + 11, 12, 8, 1)
        # Chest Heart Panel
        pulse = (self.frame // 6) % 2
        c_val = 0 if pulse == 0 else 1
        d.pixel(ox + 7, oy + 13, c_val)
        d.pixel(ox + 9, oy + 13, c_val)
        d.pixel(ox + 8, oy + 14, c_val)

        # 4. Left Arm
        if arm_l_mode == 0:
            # Normal resting arm
            d.fill_rect(ox + 2, oy + 12, 2, 7, 1)
        elif arm_l_mode == 1:
            # Arm raised / waving left
            d.line(ox + 5, oy + 12, ox + 1, oy + 6, 1)
            d.line(ox + 5, oy + 13, ox + 1, oy + 7, 1)
            d.fill_rect(ox, oy + 4, 3, 3, 1)
        elif arm_l_mode == 2:
            # Arm swing forward
            d.fill_rect(ox + 1, oy + 14, 3, 5, 1)

        # 5. Right Arm
        if arm_r_mode == 0:
            # Normal resting arm
            d.fill_rect(ox + 18, oy + 12, 2, 7, 1)
        elif arm_r_mode == 1:
            # Arm waving up-right
            for i in range(5):
                d.pixel(ox + 16 + i, oy + 12 - i, 1)
                d.pixel(ox + 17 + i, oy + 12 - i, 1)
            d.fill_rect(ox + 20, oy + 7, 3, 3, 1)
        elif arm_r_mode == 2:
            # Arm straight up wave
            d.fill_rect(ox + 17, oy + 5, 2, 8, 1)
            d.fill_rect(ox + 16, oy + 3, 4, 3, 1)
        elif arm_r_mode == 3:
            # Arm waving tilted inward
            for i in range(5):
                d.pixel(ox + 16 + (i // 2), oy + 12 - i, 1)
                d.pixel(ox + 17 + (i // 2), oy + 12 - i, 1)
            d.fill_rect(ox + 18, oy + 6, 3, 3, 1)
        elif arm_r_mode == 4:
            # Victory both arms high
            d.line(ox + 16, oy + 12, ox + 21, oy + 5, 1)
            d.line(ox + 16, oy + 13, ox + 21, oy + 6, 1)
            d.fill_rect(ox + 20, oy + 3, 3, 3, 1)

        # 6. Legs & Feet
        if leg_mode == 0:
            # Both feet planted
            d.fill_rect(ox + 7, oy + 20, 3, 4, 1)
            d.fill_rect(ox + 6, oy + 22, 4, 2, 1)
            d.fill_rect(ox + 13, oy + 20, 3, 4, 1)
            d.fill_rect(ox + 13, oy + 22, 4, 2, 1)
        elif leg_mode == 1:
            # Left leg stepping up, right foot grounded
            d.fill_rect(ox + 7, oy + 20, 3, 2, 1)
            d.fill_rect(ox + 6, oy + 21, 4, 2, 1)
            d.fill_rect(ox + 13, oy + 20, 3, 4, 1)
            d.fill_rect(ox + 13, oy + 22, 4, 2, 1)
        elif leg_mode == 2:
            # Right leg stepping up, left foot grounded
            d.fill_rect(ox + 7, oy + 20, 3, 4, 1)
            d.fill_rect(ox + 6, oy + 22, 4, 2, 1)
            d.fill_rect(ox + 13, oy + 20, 3, 2, 1)
            d.fill_rect(ox + 13, oy + 21, 4, 2, 1)
        elif leg_mode == 3:
            # Crouch / jumping bent knees
            d.fill_rect(ox + 6, oy + 20, 4, 2, 1)
            d.fill_rect(ox + 13, oy + 20, 4, 2, 1)

    # ─────────────────────────────────────────────────────────────────────────
    # Animation 0: Waving Mascot Greeting
    # ─────────────────────────────────────────────────────────────────────────
    def _anim_mascot_wave(self):
        d = self.display
        # Draw base logo
        if hasattr(d, 'buffer'):
            d.buffer[:] = TEN_LOGO
        else:
            d.fill(0)

        # Clear mascot stage between TE and N (x=71..94, y=12..41)
        d.fill_rect(71, 12, 24, 30, 0)

        # 3-step hand wave cycle
        wave_step = (self.frame // 3) % 4
        r_mode = 1 if wave_step == 0 else (2 if wave_step == 1 else (3 if wave_step == 2 else 2))

        # Blinking eye sequence
        blink = 1 if (self.frame % 30) in (28, 29) else 0

        # Draw living mascot in middle of logo
        self._draw_mascot(73, 16, arm_l_mode=0, arm_r_mode=r_mode, leg_mode=0, eye_mode=blink)

        # Mascot greeting speech bubble
        if (self.frame // 8) % 4 != 0:
            d.rect(98, 4, 28, 11, 1)
            d.text("HI!", 104, 6, 1)
            d.pixel(96, 12, 1)
            d.pixel(97, 11, 1)

        d.show()

    # ─────────────────────────────────────────────────────────────────────────
    # Animation 1: Dancing & Stepping Mascot
    # ─────────────────────────────────────────────────────────────────────────
    def _anim_mascot_dance(self):
        d = self.display
        if hasattr(d, 'buffer'):
            d.buffer[:] = TEN_LOGO
        else:
            d.fill(0)

        d.fill_rect(71, 12, 24, 30, 0)

        step_phase = (self.frame // 4) % 4
        # Alternating stepping legs and swaying torso
        if step_phase == 0:
            l_mode = 1 # left leg up
            arm_l = 2
            arm_r = 0
            sway_y = 15
        elif step_phase == 1:
            l_mode = 0 # ground
            arm_l = 0
            arm_r = 0
            sway_y = 16
        elif step_phase == 2:
            l_mode = 2 # right leg up
            arm_l = 0
            arm_r = 1
            sway_y = 15
        else:
            l_mode = 0 # ground
            arm_l = 0
            arm_r = 0
            sway_y = 16

        self._draw_mascot(73, sway_y, arm_l_mode=arm_l, arm_r_mode=arm_r, leg_mode=l_mode)

        # Musical note accents above dancing robot
        note_step = (self.frame // 6) % 2
        if note_step == 0:
            d.pixel(71, 8, 1)
            d.pixel(72, 7, 1)
            d.pixel(73, 7, 1)
        else:
            d.pixel(94, 7, 1)
            d.pixel(95, 7, 1)
            d.pixel(95, 8, 1)

        d.show()

    # ─────────────────────────────────────────────────────────────────────────
    # Animation 2: Horn Radio Wave Telemetry Broadcast
    # ─────────────────────────────────────────────────────────────────────────
    def _anim_mascot_radio_horns(self):
        d = self.display
        if hasattr(d, 'buffer'):
            d.buffer[:] = TEN_LOGO
        else:
            d.fill(0)

        d.fill_rect(71, 6, 24, 36, 0)

        # Eyes look left, right, then center
        eye_phase = (self.frame // 10) % 4
        eye = 2 if eye_phase == 1 else (3 if eye_phase == 3 else 0)

        # Expanding radio wave ring from the horns
        h_wave = (self.frame // 3) % 4

        self._draw_mascot(73, 16, arm_l_mode=0, arm_r_mode=0, leg_mode=0, eye_mode=eye, horn_wave=h_wave)

        # Status HUD above
        d.text("TX", 80, 2, 1)
        d.show()

    # ─────────────────────────────────────────────────────────────────────────
    # Animation 3: Jumping Mascot Leap
    # ─────────────────────────────────────────────────────────────────────────
    def _anim_mascot_jumping_joy(self):
        d = self.display
        if hasattr(d, 'buffer'):
            d.buffer[:] = TEN_LOGO
        else:
            d.fill(0)

        d.fill_rect(71, 6, 24, 36, 0)

        jump_phase = self.frame % 28
        # Jump timeline: 0..8 idle, 9..11 crouch, 12..20 in air, 21..24 land, 25..27 recover
        if jump_phase < 8:
            # Idle
            self._draw_mascot(73, 16, arm_l_mode=0, arm_r_mode=0, leg_mode=0)
        elif jump_phase < 12:
            # Crouch down
            self._draw_mascot(73, 18, arm_l_mode=0, arm_r_mode=0, leg_mode=3)
        elif jump_phase < 20:
            # Air leap (arc height up to -7 pixels)
            air_i = jump_phase - 12
            # Parabolic jump curve
            jump_h = int(7 * math.sin(air_i / 8.0 * 3.14159))
            self._draw_mascot(73, 16 - jump_h, arm_l_mode=1, arm_r_mode=4, leg_mode=1, horn_wave=2)
            # Dust sparks on ground
            d.pixel(74, 38, 1)
            d.pixel(91, 38, 1)
        elif jump_phase < 24:
            # Land crouch
            self._draw_mascot(73, 17, arm_l_mode=0, arm_r_mode=0, leg_mode=3)
        else:
            # Stand back up
            self._draw_mascot(73, 16, arm_l_mode=0, arm_r_mode=0, leg_mode=0)

        d.show()

    # ─────────────────────────────────────────────────────────────────────────
    # Animation 4: Mascot Rover Walking Across Display (Burn-in Safe)
    # ─────────────────────────────────────────────────────────────────────────
    def _anim_mascot_walker_rover(self):
        d = self.display
        d.fill(0)

        # Ground line
        d.hline(0, 48, 128, 1)

        # Rover motion
        if self.rover_state == "walk":
            self.rover_x += 1.2 * self.rover_dir
            # Stepping legs
            leg = 1 if (self.frame // 3) % 2 == 0 else 2
            arm_r = 0
            # Occasionally stop and wave
            if int(self.rover_x) in (35, 80) and random.randint(0, 10) > 6:
                self.rover_state = "wave"
                self.rover_wait = 24

            if self.rover_x >= 104:
                self.rover_x = 104
                self.rover_dir = -1
            elif self.rover_x <= 4:
                self.rover_x = 4
                self.rover_dir = 1
        else:
            # Waving pause state
            leg = 0
            arm_r = 1 if (self.frame // 3) % 2 == 0 else 2
            self.rover_wait -= 1
            if self.rover_wait <= 0:
                self.rover_state = "walk"

        rx = int(self.rover_x)
        ry = 24

        # Draw mascot walking along the ground
        self._draw_mascot(rx, ry, arm_l_mode=0, arm_r_mode=arm_r, leg_mode=leg)

        # Floating brand banner at top
        d.text("TEN ROBOTICS", 16, 6, 1)
        d.show()
