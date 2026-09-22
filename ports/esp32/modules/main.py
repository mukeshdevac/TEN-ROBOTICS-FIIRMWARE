import sys
if '' not in sys.path:
    sys.path.insert(0, '')
for mod in ['store_manager', 'ten', 'hardware', 'buzzer', 'eyes', 'logo']:
    if mod in sys.modules:
        del sys.modules[mod]

import machine
import gc
import time
import os
import store_manager
from buzzer import buzzer

# --- Watchdog Timer Initialization ---
print("Initializing WDT for ESP32 DevKit V1...")
try:
    wdt = machine.WDT(timeout=15000)
    wdt_timer = machine.Timer(2)
    wdt_timer.init(period=4000, mode=machine.Timer.PERIODIC, callback=lambda t: wdt.feed())
    print("WDT Initialized.")
except Exception as e:
    print("WDT Init Warning:", e)

def main():
    print("Starting Main Sequence (TEN Robotics ESP32 V1)...")
    if 'wdt' in globals():
        wdt.feed()

    try:
        store_manager.start()
        print("Store Manager & Hardware Ready")
    except Exception as e:
        print("Store Manager init failed:")
        sys.print_exception(e)

    loop_count = 0
    while True:
        try:
            if 'wdt' in globals():
                wdt.feed()
            loop_count += 1
            mgr = store_manager.manager

            if mgr:
                mgr.poll_serial()
                mgr.poll_buttons()
                mgr.poll_power_telemetry()
                mgr.poll_ui()

            if hasattr(mgr, 'pending_start') and mgr.pending_start:
                mgr.pending_start = False
                mgr.start_prog()

            if loop_count % 10 == 0:
                gc.collect()

            if mgr and mgr.prog_status == "RUNNING" and not mgr.is_uploading:
                try:
                    fsize = os.stat("app.py")[6]
                except Exception:
                    fsize = 0

                if fsize <= 0:
                    print("MAIN: No program found (app.py empty) - halting execution.")
                    mgr.stop_prog("NO SCRIPT")
                else:
                    current_session = mgr.exec_start_ticks
                    
                    def check_abort():
                        if mgr.prog_status != "RUNNING" or mgr.exec_start_ticks != current_session or mgr.is_uploading:
                            raise SystemExit("STOPPED_BY_USER")

                    exec_globals = {
                        "__name__": "__main__",
                        "machine": machine, "time": time, "os": os, "gc": gc,
                        "display": mgr.display, "buzzer": buzzer,
                        "check_abort": check_abort
                    }

                    try:
                        print(f"--- EXEC START (Session {current_session}) ---")
                        mgr._in_exec = True
                        with open("app.py", "r") as f:
                            code_str = f.read()
                        gc.collect()
                        import ten
                        ten.start()
                        exec(code_str, exec_globals)
                        mgr._in_exec = False
                        print(f"--- EXEC DONE (Session {current_session}) ---")
                        if mgr.prog_status == "RUNNING":
                            mgr.stop_prog()
                    except KeyboardInterrupt:
                        mgr._in_exec = False
                        print(f"--- EXEC STOPPED (Session {current_session}) ---")
                        mgr.stop_prog("STOPPED")
                    except BaseException as e:
                        mgr._in_exec = False
                        print(f"--- EXEC ERROR (Session {current_session}) ---")
                        sys.print_exception(e)

                        # Emit structured error for App Toast and Serial Terminal
                        err_name = type(e).__name__
                        err_msg = str(e)
                        if hasattr(mgr, 'send_response'):
                            mgr.send_response(f"ERR:{err_name}: {err_msg}\n")
                            mgr.send_response("STATUS:STOPPED\n")

                        # Safety: immediately stop all motors & actuators
                        if hasattr(mgr, '_stop_all_motors'):
                            mgr._stop_all_motors()

                        # Audio alert
                        buzzer.play_error()

                        # Render Error Screen on OLED Display with clean readable layout
                        if mgr.display and not mgr.is_uploading:
                            try:
                                d = mgr.display
                                d.fill(0)
                                d.fill_rect(0, 0, 128, 12, 1)
                                d.text("SYSTEM ERROR", 16, 2, 0)
                                d.text(f"Type: {err_name[:12]}", 4, 20, 1)
                                d.text(f"Msg: {err_msg[:14]}", 4, 34, 1)
                                d.text("BTN1 to return", 4, 52, 1)
                                d.show()
                            except Exception:
                                pass

                        mgr.stop_prog(e)
                    finally:
                        mgr._in_exec = False
                        exec_globals.clear()
                        gc.collect()

                time.sleep(0.1)
            else:
                time.sleep_ms(30)

        except KeyboardInterrupt:
            # Prevent REPL exit from breaking the firmware loop
            if mgr:
                mgr._in_exec = False
                mgr.stop_prog()
            time.sleep_ms(100)
        except Exception as e:
            print("Main loop caught top-level exception (OS STABLE):")
            sys.print_exception(e)
            time.sleep(0.5)

if __name__ == "__main__":
    main()
