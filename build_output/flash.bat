@echo off
setlocal enabledelayedexpansion

echo ========================================================
echo   TEN Robotics ESP32 Firmware Flasher (Windows)
echo ========================================================
echo.

set BIN_DIR=%~dp0
if exist "%BIN_DIR%\build_output\micropython.bin" (
    set BIN_DIR=%BIN_DIR%\build_output
)
if not exist "%BIN_DIR%\micropython.bin" (
    echo [ERROR] Firmware binaries not found in %BIN_DIR%
    pause
    exit /b 1
)

set PORT=%1
if "%PORT%"=="" (
    echo Detecting available serial ports...
    powershell -NoProfile -Command "[System.IO.Ports.SerialPort]::GetPortNames() | ForEach-Object { Write-Host '  Found Port:' $_ }"
    echo.
    set /p PORT="Enter ESP32 COM Port (e.g. COM3, COM5, COM11): "
)

if "%PORT%"=="" (
    echo [ERROR] No COM port specified.
    pause
    exit /b 1
)

echo.
echo Flashing ESP32 on %PORT% at 460800 baud...
python -m esptool --chip esp32 -p %PORT% -b 460800 --before default_reset --after hard_reset write_flash --flash_mode dio --flash_size 4MB --flash_freq 40m 0x1000 "%BIN_DIR%\bootloader.bin" 0x8000 "%BIN_DIR%\partition-table.bin" 0x10000 "%BIN_DIR%\micropython.bin"

if %ERRORLEVEL% equ 0 (
    echo.
    echo ========================================================
    echo   FLASH COMPLETE! ESP32 reset and running new firmware.
    echo ========================================================
) else (
    echo.
    echo [ERROR] Flashing failed. Check COM port connection and cable.
)

echo.
pause
