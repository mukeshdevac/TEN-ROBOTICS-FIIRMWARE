# TEN Robotics ESP32 Firmware Binaries

This folder contains pre-compiled firmware binaries ready for direct flashing to any TEN Robotics ESP32 DevKit V1 board without requiring ESP-IDF setup.

## Binary Files & Flash Offsets:
- **`bootloader.bin`** -> Address `0x1000`
- **`partition-table.bin`** -> Address `0x8000`
- **`micropython.bin`** -> Address `0x10000`

---

## How to Flash:

### Option 1: Quick Flash Script (Windows)
Run `flash.bat` or run:
```cmd
flash.bat COM11
```
(Replace `COM11` with your board's serial port).

### Option 2: Using esptool (Command Line)
```bash
python -m esptool --chip esp32 -p <YOUR_COM_PORT> -b 460800 --before default_reset --after hard_reset write_flash --flash_mode dio --flash_size 4MB --flash_freq 40m 0x1000 bootloader.bin 0x8000 partition-table.bin 0x10000 micropython.bin
```

---

## What is Included in this Firmware:
1. **7-Page OLED System HUD**:
   - `1/7: SYSTEM` (BLE Status & DevKit Identity)
   - `2/7: PROGRAM` (Script Status, execution metrics, zero-freeze guard)
   - `3/7: BATTERY (2S)` (Calibrated 6.0V - 8.4V Li-ion, low battery alert toggle)
   - `4/7: MOTOR TEST` (M1–M4/OUT selector with 10% speed increments & direction toggle)
   - `5/7: SERVO TEST` (S1/S2 angle selector, FROM/TO range sweep execution)
   - `6/7: SENSORS` (P1/P2/P3 real-time analog telemetry)
   - `7/7: CYBER RUN` (Offline Chrome Dino mini-game with mascot, pylons & drones)
2. **Screensaver**:
   - 30-second idle screensaver with pure TEN Robotics logo and mascot animation.
3. **Web IDE & Bluetooth BLE**:
   - Direct web IDE compatibility with https://www.tenrobotics.in.
