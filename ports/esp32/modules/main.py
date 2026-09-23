import sys
if '' not in sys.path:
    sys.path.insert(0, '')
for mod in ['store_manager', 'wifi_manager', 'ble_manager', 'ten', 'hardware', 'buzzer', 'eyes', 'logo']:
    if mod in sys.modules:
        del sys.modules[mod]

import machine
import gc
import time
import os
import store_manager
from buzzer import buzzer
import ten

class SafeTime:
    """Safe time wrapper that keeps the OS fully alive during user sleeps."""
    @staticmethod
    def sleep(s):
        ten.delay(int(s * 1000))

    @staticmethod
    def sleep_ms(ms):
        ten.delay(int(ms))

    @staticmethod
    def sleep_us(us):
        time.sleep_us(us)

    @staticmethod
    def ticks_ms():
        return time.ticks_ms()

    @staticmethod
    def ticks_us():
        return time.ticks_us()

    @staticmethod
    def ticks_diff(t1, t2):
        return time.ticks_diff(t1, t2)

    @staticmethod
    def ticks_add(t, d):
        return time.ticks_add(t, d)

    @staticmethod
    def time():
        return time.time()

    @staticmethod
    def localtime(*args):
        return time.localtime(*args)

# SafeTime module alias
sys.modules['time'] = SafeTime
sys.modules['ten'] = ten

def main():
    print("Starting Supervised Main Sequence (TEN Robotics ESP32 DevKit V1)...")

    try:
        store_manager.start()
        print("Store Manager & Multi-Transport Engine Ready.")
    except Exception as e:
        print("Store Manager init failed:")
        sys.print_exception(e)

    loop_count = 0
    while True:
        try:
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

            if loop_count % 20 == 0:
                gc.collect()

            # Supervised Program Execution
            if mgr and mgr.prog_status == "RUNNING" and not mgr.is_uploading:
                try:
                    fsize = os.stat("app.py")[6]
                except Exception:
                    fsize = 0

                if fsize <= 0:
                    print("MAIN: No program found (app.py empty) - halting execution.")
                    mgr.stop_prog("NO SCRIPT")
                else:
                    session_id = mgr.exec_start_ticks
                    mgr._in_exec = True

                    def check_abort():
                        if not mgr or mgr.prog_status != "RUNNING" or mgr.exec_start_ticks != session_id or mgr.is_uploading:
                            raise KeyboardInterrupt("STOPPED_BY_USER")

                    def custom_print(*args, **kwargs):
                        sep = kwargs.get("sep", " ")
                        end = kwargs.get("end", "\n")
                        text = sep.join(str(a) for a in args) + end
                        if mgr:
                            mgr.write_out(text)
                        else:
                            sys.stdout.write(text)

                    def broadcast(val):
                        if mgr:
                            mgr.write_out(f"SENSOR:{val}\n")
                        else:
                            sys.stdout.write(f"SENSOR:{val}\n")

                    exec_globals = {
                        "__name__": "__main__",
                        "machine": machine,
                        "time": SafeTime,
                        "os": os,
                        "gc": gc,
                        "display": mgr.display if mgr else None,
                        "buzzer": buzzer,
                        "ten": ten,
                        "print": custom_print,
                        "broadcast": broadcast,
                        "check_abort": check_abort
                    }

                    try:
                        print(f"--- EXEC START (Session {session_id}) ---")
                        with open("app.py", "r") as f:
                            code_str = f.read()

                        gc.collect()
                        ten.start()
                        exec(code_str, exec_globals)
                        print(f"--- EXEC COMPLETED (Session {session_id}) ---")
                        if mgr and mgr.prog_status == "RUNNING":
                            mgr.stop_prog()
                    except KeyboardInterrupt:
                        print(f"--- EXEC HALTED (Session {session_id}) ---")
                        if mgr:
                            mgr.stop_prog()
                    except BaseException as e:
                        print(f"--- EXEC ERROR (Session {session_id}) ---")
                        sys.print_exception(e)
                        buzzer.play_error()
                        if mgr:
                            mgr.write_out(f"ERR:{str(e)}\n")
                            mgr.write_out("STATUS:STOPPED\n")
                            if mgr.display and not mgr.is_uploading:
                                try:
                                    d = mgr.display
                                    d.fill(0)
                                    d.fill_rect(0, 0, 128, 12, 1)
                                    d.text("SYSTEM ERROR", 16, 2, 0)
                                    err_name = type(e).__name__[:14]
                                    err_msg = str(e)[:14]
                                    d.text(err_name, 8, 26, 1)
                                    d.text(err_msg, 8, 44, 1)
                                    d.show()
                                except Exception:
                                    pass
                            mgr.stop_prog(e)
                    finally:
                        exec_globals.clear()
                        ten.stop_all()
                        if mgr:
                            mgr._in_exec = False
                        gc.collect()

                time.sleep_ms(50)
            else:
                time.sleep_ms(20)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print("Main supervisor caught top-level exception (OS STABLE):")
            sys.print_exception(e)
            time.sleep_ms(200)

if __name__ == "__main__":
    main()
