# Ten Robotics - Hardware Pin Mappings for ESP32 DevKit V1 30-PIN (Schematic PCB V2)
# Configured based on TENPCBV2 Schematic Diagram

from machine import Pin

# --- I2C BUS (Shared between 1.3" OLED & INA219 Power Monitor) ---
I2C_SDA = 21
I2C_SCL = 22

# --- SERVOS & BUZZER ---
S1 = 18          # SERVO_1 (D18)
S2 = 19          # SERVO_2 (D19)
BUZZER_PIN = 33  # BUZZER (D33)

# --- MOTORS (DRV8833 Motor Drivers) ---
# Left Motor (ML)
M1_IN1 = 13      # ML_IN1 (D13)
M1_IN2 = 14      # ML_IN2 (D14)

# Right Motor (MR)
M2_IN1 = 27      # MR_IN1 (D27)
M2_IN2 = 26      # MR_IN2 (D26)

# Aux Motor / Additional Drivers (AUXM)
M3_IN1 = 25      # AUXM_IN1 (D25)
M3_IN2 = 23      # AUXM_IN2 (D23)

# General Outputs (OUTIN)
OUT1 = 4         # OUTIN_1 (D4)
OUT2 = 5         # OUTIN_2 (D5)

# --- SENSORS (ADC Channels) ---
SN1 = 34         # SENSOR_1 (D34 - Input Only)
SN2 = 35         # SENSOR_2 (D35 - Input Only)
SN3 = 32         # SENSOR_3 (D32)
SN4 = 36         # VP / VM (Voltage Sense)

# --- PHYSICAL BUTTONS ---
BTN1 = 16        # START Button (RX2 / D16)
BTN2 = 17        # SCREEN Button (TX2 / D17)

# Status LED (Internal / External fallback)
SYS_LED = Pin(2, Pin.OUT)
