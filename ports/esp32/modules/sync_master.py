import sys
import micropython
from micropython import const
import store_manager
from buzzer import buzzer

class SyncMaster:
    """
    SyncMaster v5: Communication protocol for ESP32.
    Implements closed-loop handshake with upload screen locking and audio prompts.
    """
    def __init__(self, on_command_cb, on_data_cb):
        self.on_command = on_command_cb
        self.on_data = on_data_cb
        self.serial_buf = bytearray()
        self.ble_buf = bytearray()
        self._is_uploading = False
        
        self._ACK_OK = b"UPLOAD:OK\n"
        self._ACK_READY = b"UPLOAD:READY\n"
        self._ACK_ERR = b"UPLOAD:ERR\n"
        
    def reset_buffers(self):
        self.serial_buf = bytearray()
        self.ble_buf = bytearray()
        self._is_uploading = False
        if store_manager.manager:
            store_manager.manager.is_uploading = False

    def purge(self, poller):
        self.reset_buffers()
        try:
            while poller.poll(0):
                sys.stdin.read(1)
        except Exception:
            pass

    def capture_ble(self, payload):
        if len(self.ble_buf) > 8192:
            self.ble_buf = bytearray()
        self.ble_buf.extend(payload)

    def poll_serial(self, poller):
        if len(self.serial_buf) > 8192:
            self.serial_buf = bytearray()
            
        try:
            while poller.poll(0):
                c = sys.stdin.read(1)
                if not c:
                    break
                self.serial_buf.append(ord(c))
            
            if len(self.serial_buf) > 0 and b'\n' in self.serial_buf:
                self._harvest(self.serial_buf, source="SERIAL")
        except Exception as e:
            pass

    def poll_ble(self):
        if self.ble_buf:
            self._harvest(self.ble_buf, source="BLE")

    def _harvest(self, buffer, source):
        if b'\n' not in buffer:
            return

        import gc
        gc.collect()
        
        parts = buffer.split(b'\n')
        buffer[:] = parts.pop()

        for line_bytes in parts:
            try:
                line_str = line_bytes.decode().strip()
            except Exception:
                line_str = ""

            if line_str in ("CLEAR", "STOP", "START", "RESTART", "SYNC", "SERIAL_ON") or line_str.startswith("BEGIN_UPLOAD"):
                if source == "SERIAL":
                    self.on_command("SERIAL_ON", None)
                
                if line_str == "CLEAR":
                    self.reset_buffers()
                    self.on_command("CLEAR", None)
                elif line_str == "STOP":
                    self.reset_buffers()
                    self.on_command("STOP", None)
                elif line_str in ("START", "RESTART"):
                    self.reset_buffers()
                    self.on_command("START", None)
                elif line_str == "SYNC":
                    self.on_command("SYNC", None)
                elif line_str == "SERIAL_ON":
                    self.on_command("SERIAL_ON", None)
                elif line_str.startswith("BEGIN_UPLOAD"):
                    self._is_uploading = True
                    if store_manager.manager:
                        store_manager.manager.is_uploading = True
                    self._current_line = 0
                    self._total_lines = 0
                    self._target_file = "app.py"
                    
                    p_parts = line_str.split(":")
                    if len(p_parts) >= 2:
                        try:
                            self._total_lines = int(p_parts[1])
                        except Exception:
                            pass
                    if len(p_parts) >= 3:
                        self._target_file = p_parts[2]
                        
                    self.on_command("BEGIN_UPLOAD", (self._total_lines, self._target_file))
                    self.send_ack("READY")
                    
                    # Lock display on Download screen
                    if store_manager.manager and store_manager.manager.display:
                        try:
                            d = store_manager.manager.display
                            d.fill(0)
                            d.text("DOWNLOADING CODE", 0, 10, 1)
                            d.text(f"Lines: 0/{self._total_lines}", 10, 35, 1)
                            d.show()
                        except Exception:
                            pass
                continue

            # USER DATA (Code Line)
            raw_full = line_bytes + b'\n'
            self.on_data(raw_full)
            if self._is_uploading:
                self._current_line += 1
                self.on_command("PROGRESS", (self._current_line, self._total_lines))
                self.send_ack("OK")
                
                # Update progress on locked display
                if store_manager.manager and store_manager.manager.display:
                    try:
                        d = store_manager.manager.display
                        d.fill(0)
                        d.text("DOWNLOADING CODE", 0, 10, 1)
                        pct = int(self._current_line * 100 / max(1, self._total_lines))
                        d.text(f"Progress: {pct}%", 10, 35, 1)
                        d.show()
                    except Exception:
                        pass
                
                if self._current_line >= self._total_lines:
                    self._is_uploading = False
                    if store_manager.manager:
                        store_manager.manager.is_uploading = False
                    buzzer.play_button()

    def send_ack(self, type):
        if type == "OK":
            self.on_command("SEND_RAW", self._ACK_OK)
        elif type == "READY":
            self.on_command("SEND_RAW", self._ACK_READY)
        elif type == "ERR":
            self.on_command("SEND_RAW", self._ACK_ERR)
