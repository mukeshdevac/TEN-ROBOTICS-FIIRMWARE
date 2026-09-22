"""
TEN Robotics ESP32 DevKit V1 - Cyber Mascot Runner Game (Chrome Dino Style)
Endless runner mini-game featuring the TEN Robotics mascot, cyber obstacles, and flying UAVs.
"""

import time
try:
    import urandom as random
except ImportError:
    import random
import buzzer


class CyberRunnerGame:
    def __init__(self, display):
        self.display = display
        self.width = 128
        self.height = 64
        self.ground_y = 50

        # Player Mascot state
        self.player_x = 12
        self.player_y = 30.0  # y is top of mascot (height = 20, feet at y=50)
        self.player_vy = 0.0
        self.is_jumping = False
        self.jump_count = 0

        # Game states: "TITLE", "PLAYING", "GAMEOVER"
        self.state = "TITLE"
        self.score = 0
        self.high_score = 0
        self.speed = 3.0
        self.frame = 0

        # Obstacles list: each dict has {"type": "pylon"|"uav", "x": float, "y": int, "w": int, "h": int}
        self.obstacles = []
        self.last_spawn_frame = 0

        # Background cyber stars / clouds
        self.clouds = [
            {"x": 20, "y": 8, "w": 12},
            {"x": 75, "y": 14, "w": 16},
            {"x": 115, "y": 10, "w": 10},
        ]

    def reset(self):
        """Reset game to initial playing state."""
        self.player_y = 30.0
        self.player_vy = 0.0
        self.is_jumping = False
        self.jump_count = 0
        self.score = 0
        self.speed = 3.2
        self.obstacles = []
        self.last_spawn_frame = 0
        self.state = "PLAYING"
        try:
            buzzer.play_startup()
        except Exception:
            pass

    def on_btn1_action(self):
        """BTN1: Jump during game, or Start/Restart on Title/GameOver."""
        if self.state in ("TITLE", "GAMEOVER"):
            self.reset()
            return True

        if self.state == "PLAYING":
            # Jump action (supports double jump for extra fun!)
            if not self.is_jumping:
                self.player_vy = -6.2
                self.is_jumping = True
                self.jump_count = 1
                try:
                    buzzer.tone(1600, 30)
                except Exception:
                    pass
                return True
            elif self.jump_count == 1:
                # Double jump mid-air!
                self.player_vy = -5.0
                self.jump_count = 2
                try:
                    buzzer.tone(2000, 30)
                except Exception:
                    pass
                return True
        return False

    def update(self):
        """Update physics, spawn obstacles, check collisions, and render frame."""
        if not self.display:
            return

        self.frame += 1

        if self.state == "TITLE":
            self._render_title()
            return

        if self.state == "GAMEOVER":
            self._render_gameover()
            return

        # ─── 1. Physics & Player Motion ───
        if self.is_jumping:
            self.player_y += self.player_vy
            self.player_vy += 0.7  # Gravity
            # Check ground landing
            if self.player_y >= 30.0:
                self.player_y = 30.0
                self.player_vy = 0.0
                self.is_jumping = False
                self.jump_count = 0

        # Score & Speed scaling
        self.score += 1
        if self.score > self.high_score:
            self.high_score = self.score

        # Score milestone chime every 100 points
        if self.score % 100 == 0:
            try:
                buzzer.play_button()
            except Exception:
                pass
            if self.speed < 6.0:
                self.speed += 0.2

        # ─── 2. Obstacle Management ───
        # Move existing obstacles
        for obs in self.obstacles:
            obs["x"] -= self.speed

        # Remove offscreen obstacles
        self.obstacles = [o for o in self.obstacles if o["x"] + o["w"] > 0]

        # Spawn new obstacle
        if self.frame - self.last_spawn_frame > random.randint(30, 55):
            self.last_spawn_frame = self.frame
            # Randomly spawn either Ground Cyber Pylon or Flying UAV
            spawn_uav = (self.score > 60) and (random.randint(0, 10) > 4)
            if spawn_uav:
                # Flying UAV / Drone
                self.obstacles.append({
                    "type": "uav",
                    "x": 128.0,
                    "y": random.choice([20, 26]),
                    "w": 14,
                    "h": 8,
                })
            else:
                # Ground Cyber Pylon
                h = random.choice([12, 16])
                self.obstacles.append({
                    "type": "pylon",
                    "x": 128.0,
                    "y": self.ground_y - h,
                    "w": 8,
                    "h": h,
                })

        # ─── 3. Collision Detection ───
        px = self.player_x
        py = int(self.player_y)
        pw = 14
        ph = 20

        for obs in self.obstacles:
            ox = int(obs["x"])
            oy = obs["y"]
            ow = obs["w"]
            oh = obs["h"]

            # Bounding box intersection with 2px padding for fair hitbox
            if (px + pw - 2 > ox + 2) and (px + 2 < ox + ow - 2):
                if (py + ph - 2 > oy + 1) and (py + 2 < oy + oh):
                    # Collision detected!
                    self.state = "GAMEOVER"
                    try:
                        buzzer.play_error()
                    except Exception:
                        pass
                    self._render_gameover()
                    return

        # ─── 4. Render Active Frame ───
        self._render_play_frame()

    # ─────────────────────────────────────────────────────────────────────────
    # Renderer Functions
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_player_mascot(self, ox, oy, is_jump, dead=False):
        """Draw the 14x20 running robot mascot."""
        d = self.display

        # Horns on head
        d.pixel(ox + 3, oy, 1)
        d.pixel(ox + 4, oy + 1, 1)
        d.pixel(ox + 10, oy, 1)
        d.pixel(ox + 9, oy + 1, 1)

        # Head (9x6 pixels)
        d.fill_rect(ox + 2, oy + 2, 9, 6, 1)
        d.fill_rect(ox + 3, oy + 4, 7, 3, 0) # face cutout

        # Eyes
        if dead:
            # Dizzy 'X' eyes
            d.pixel(ox + 4, oy + 4, 1)
            d.pixel(ox + 5, oy + 5, 1)
            d.pixel(ox + 8, oy + 4, 1)
            d.pixel(ox + 7, oy + 5, 1)
        else:
            # Focused runner eyes looking forward
            d.pixel(ox + 5, oy + 5, 1)
            d.pixel(ox + 8, oy + 5, 1)

        # Body Torso (9x6 pixels)
        d.fill_rect(ox + 2, oy + 9, 9, 6, 1)
        # Heart LED
        pulse = (self.frame // 4) % 2
        d.pixel(ox + 4, oy + 11, pulse)
        d.pixel(ox + 6, oy + 11, pulse)

        # Arms
        if is_jump:
            # Victory arms angled up
            d.line(ox + 2, oy + 10, ox - 1, oy + 6, 1)
            d.line(ox + 10, oy + 10, ox + 13, oy + 6, 1)
        else:
            # Arms pumping in stride
            arm_stride = (self.frame // 3) % 2
            if arm_stride == 0:
                d.fill_rect(ox, oy + 11, 2, 4, 1)
                d.fill_rect(ox + 11, oy + 9, 2, 4, 1)
            else:
                d.fill_rect(ox, oy + 9, 2, 4, 1)
                d.fill_rect(ox + 11, oy + 11, 2, 4, 1)

        # Legs
        if is_jump:
            # Bent legs in air
            d.fill_rect(ox + 3, oy + 15, 3, 3, 1)
            d.fill_rect(ox + 7, oy + 15, 3, 3, 1)
        else:
            # Alternating stride
            leg_step = (self.frame // 2) % 2
            if leg_step == 0:
                d.fill_rect(ox + 3, oy + 15, 3, 5, 1)  # left foot down
                d.fill_rect(ox + 7, oy + 15, 3, 3, 1)  # right foot back
            else:
                d.fill_rect(ox + 3, oy + 15, 3, 3, 1)  # left foot back
                d.fill_rect(ox + 7, oy + 15, 3, 5, 1)  # right foot down

    def _draw_uav(self, x, y):
        """Draw the flying cyber drone / UAV obstacle."""
        d = self.display
        ix = int(x)
        iy = int(y)

        # Drone fuselage
        d.fill_rect(ix + 3, iy + 3, 8, 4, 1)
        # Red camera sensor eye
        d.pixel(ix + 4, iy + 4, 0)

        # Spinning twin rotors
        prop_frame = (self.frame // 2) % 2
        if prop_frame == 0:
            d.hline(ix, iy + 1, 5, 1)
            d.hline(ix + 9, iy + 1, 5, 1)
        else:
            d.line(ix, iy + 2, ix + 4, iy, 1)
            d.line(ix + 9, iy, ix + 13, iy + 2, 1)

        # Rotor struts
        d.vline(ix + 2, iy + 1, 3, 1)
        d.vline(ix + 11, iy + 1, 3, 1)

        # Landing skids
        d.hline(ix + 2, iy + 7, 10, 1)

    def _draw_pylon(self, x, y, h):
        """Draw the cyber energy pylon obstacle."""
        d = self.display
        ix = int(x)
        # Tapered cyber pylon
        d.rect(ix + 2, y + 3, 4, h - 3, 1)
        d.fill_rect(ix + 3, y + 4, 2, h - 4, 1)
        # Base plate
        d.fill_rect(ix, y + h - 2, 8, 2, 1)
        # Top glowing energy crystal
        spark = (self.frame // 3) % 2
        d.fill_rect(ix + 2, y, 4, 3, spark)

    def _render_play_frame(self):
        d = self.display
        d.fill(0)

        # 1. Top HUD: Score & High Score
        sc_str = f"HI {self.high_score:04d}  {self.score:04d}"
        d.text(sc_str, 20, 2, 1)

        # 2. Scrolling Background Cyber Clouds
        for c in self.clouds:
            c["x"] -= 0.6
            if c["x"] + c["w"] < 0:
                c["x"] = 128 + random.randint(10, 30)
                c["y"] = random.randint(6, 16)
            cx = int(c["x"])
            d.rect(cx, c["y"], c["w"], 4, 1)
            d.pixel(cx + 2, c["y"] - 1, 1)
            d.pixel(cx + 4, c["y"] - 1, 1)

        # 3. Ground Line with Scrolling Grid Ticks
        d.hline(0, self.ground_y, 128, 1)
        tick_offset = int((self.frame * self.speed) % 16)
        for tx in range(-tick_offset, 128, 16):
            if tx >= 0:
                d.pixel(tx, self.ground_y + 2, 1)
                d.pixel(tx + 4, self.ground_y + 4, 1)

        # 4. Obstacles
        for obs in self.obstacles:
            if obs["type"] == "uav":
                self._draw_uav(obs["x"], obs["y"])
            else:
                self._draw_pylon(obs["x"], obs["y"], obs["h"])

        # 5. Mascot Player
        self._draw_player_mascot(self.player_x, int(self.player_y), self.is_jumping)

        d.show()

    def _render_title(self):
        d = self.display
        d.fill(0)
        d.fill_rect(0, 0, 128, 11, 1)
        d.text("7/7: CYBER RUN", 10, 2, 0)

        d.text("TEN DINO RUNNER", 4, 16, 1)

        # Draw mascot demo
        self._draw_player_mascot(16, 28, False)
        # Draw demo pylon and UAV
        self._draw_pylon(56, 36, 14)
        self._draw_uav(94, 26)

        d.hline(0, 50, 128, 1)

        # Blinking start prompt
        if (self.frame // 6) % 2 == 0:
            d.text("PRESS BTN1 TO RUN", 0, 54, 1)
        d.show()

    def _render_gameover(self):
        d = self.display
        d.fill(0)

        # Clean Inverted Game Over Banner
        d.fill_rect(0, 4, 128, 14, 1)
        d.text("=== GAME OVER ===", 4, 7, 0)

        # Centered clean score display without mascot overlap
        d.text(f"SCORE : {self.score:04d}", 20, 24, 1)
        d.text(f"BEST  : {self.high_score:04d}", 20, 37, 1)

        # Bottom divider and flashing replay prompt
        d.hline(0, 50, 128, 1)
        if (self.frame // 6) % 2 == 0:
            d.text("> BTN1: REPLAY <", 8, 54, 1)
        else:
            d.text("  BTN1: REPLAY  ", 8, 54, 1)

        d.show()
