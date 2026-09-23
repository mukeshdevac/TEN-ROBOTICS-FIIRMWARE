"""
TEN Robotics - WiFi & IP Socket Server Engine for ESP32 DevKit V1
Provides AP / STA network management, WebSocket & TCP text socket server on port 8266,
and closed-loop code upload and telemetry routing over WiFi.
Website: https://www.tenrobotics.in/
"""

import network
import socket
import select
import struct
import ubinascii
import hashlib
import time
import gc

def get_mac_suffix():
    try:
        import machine
        raw = machine.unique_id()
        return f"{raw[-2]:02X}{raw[-1]:02X}"
    except Exception:
        return "W100"

class WiFiManager:
    def __init__(self, store_mgr=None, port=8266):
        self.mgr = store_mgr
        self.port = port
        self.ap = None
        self.sta = None
        self.server_sock = None
        self.clients = []
        self.ws_clients = {}  # sock -> bool (is websocket)
        self.client_buffers = {} # sock -> bytearray
        self.ap_name = f"TEN_DEVKIT_{get_mac_suffix()}"
        self.ip_address = "192.168.4.1"
        self.is_active = False

        self._poller = select.poll()
        self.init_network()
        self.start_server()

    def init_network(self):
        """Initializes Access Point (AP) mode by default."""
        try:
            self.ap = network.WLAN(network.AP_IF)
            self.ap.active(True)
            self.ap.config(essid=self.ap_name, authmode=network.AUTH_OPEN)
            # Standard AP IP is 192.168.4.1
            ifconfig = self.ap.ifconfig()
            self.ip_address = ifconfig[0]
            print(f"[WiFi] AP Mode Active: SSID='{self.ap_name}', IP={self.ip_address}")
            self.is_active = True
        except Exception as e:
            print(f"[WiFi] AP Init Warning: {e}")

    def start_server(self):
        """Starts non-blocking TCP socket server on port 8266."""
        try:
            self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_sock.bind(('0.0.0.0', self.port))
            self.server_sock.listen(3)
            self.server_sock.setblocking(False)
            self._poller.register(self.server_sock, select.POLLIN)
            print(f"[WiFi] Server listening on ws://{self.ip_address}:{self.port}")
        except Exception as e:
            print(f"[WiFi] Server bind error: {e}")

    def poll(self):
        """Poll incoming connections and messages without blocking."""
        if not self.server_sock:
            return

        try:
            events = self._poller.poll(0)
        except Exception:
            return

        for sock, ev in events:
            if sock == self.server_sock:
                # Accept new client connection
                try:
                    client_sock, addr = self.server_sock.accept()
                    client_sock.setblocking(False)
                    self.clients.append(client_sock)
                    self.client_buffers[client_sock] = bytearray()
                    self.ws_clients[client_sock] = False
                    self._poller.register(client_sock, select.POLLIN | select.POLLHUP | select.POLLERR)
                    print(f"[WiFi] Client connected from {addr}")
                    if self.mgr:
                        self.mgr.record_activity()
                except Exception:
                    pass
            else:
                # Client socket event
                if ev & (select.POLLHUP | select.POLLERR):
                    self._remove_client(sock)
                elif ev & select.POLLIN:
                    self._handle_client_read(sock)

    def _remove_client(self, sock):
        try:
            self._poller.unregister(sock)
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass
        if sock in self.clients:
            self.clients.remove(sock)
        self.ws_clients.pop(sock, None)
        self.client_buffers.pop(sock, None)
        print("[WiFi] Client disconnected.")

    def _handle_client_read(self, sock):
        try:
            data = sock.recv(1024)
            if not data:
                self._remove_client(sock)
                return
        except Exception:
            self._remove_client(sock)
            return

        buf = self.client_buffers.get(sock, bytearray())
        buf.extend(data)

        # Check for HTTP WebSocket Upgrade Handshake
        if not self.ws_clients.get(sock, False):
            if b"\r\n\r\n" in buf or b"\n\n" in buf:
                req_text = bytes(buf).decode("latin-1", "ignore")
                if "Upgrade: websocket" in req_text or "upgrade: websocket" in req_text.lower():
                    # Parse Sec-WebSocket-Key
                    key = None
                    for line in req_text.split("\r\n"):
                        if line.lower().startswith("sec-websocket-key:"):
                            key = line.split(":", 1)[1].strip()
                            break

                    if key:
                        guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                        accept_val = hashlib.sha1((key + guid).encode("utf-8")).digest()
                        accept_b64 = ubinascii.b2a_base64(accept_val).decode("utf-8").strip()

                        resp = (
                            "HTTP/1.1 101 Switching Protocols\r\n"
                            "Upgrade: websocket\r\n"
                            "Connection: Upgrade\r\n"
                            f"Sec-WebSocket-Accept: {accept_b64}\r\n\r\n"
                        )
                        sock.send(resp.encode("utf-8"))
                        self.ws_clients[sock] = True
                        buf.clear()
                        print("[WiFi] WebSocket Handshake Complete.")
                        if self.mgr:
                            self.mgr.write_out("STATUS:READY\n")
                        return

        # Handle established WebSocket frames or raw text
        if self.ws_clients.get(sock, False):
            self._process_ws_frames(sock, buf)
        else:
            # Raw TCP lines
            if b"\n" in buf:
                parts = buf.split(b"\n")
                self.client_buffers[sock] = bytearray(parts.pop())
                for line in parts:
                    if self.mgr:
                        self.mgr.record_activity()
                        self.mgr.ingest_data(line + b"\n", source="WIFI")

    def _process_ws_frames(self, sock, buf):
        while len(buf) >= 2:
            b1 = buf[0]
            b2 = buf[1]
            opcode = b1 & 0x0F
            is_masked = bool(b2 & 0x80)
            payload_len = b2 & 0x7F

            offset = 2
            if payload_len == 126:
                if len(buf) < 4:
                    return
                payload_len = struct.unpack("!H", buf[2:4])[0]
                offset = 4
            elif payload_len == 127:
                if len(buf) < 10:
                    return
                payload_len = struct.unpack("!Q", buf[2:10])[0]
                offset = 10

            mask = None
            if is_masked:
                if len(buf) < offset + 4:
                    return
                mask = buf[offset:offset+4]
                offset += 4

            if len(buf) < offset + payload_len:
                return # Incomplete frame, wait for more data

            payload = bytearray(buf[offset:offset+payload_len])
            del buf[:offset+payload_len]

            if is_masked and mask:
                for i in range(len(payload)):
                    payload[i] ^= mask[i % 4]

            # Opcode 8 = Close, 9 = Ping, 10 = Pong, 1 = Text, 2 = Binary
            if opcode == 8:
                self._remove_client(sock)
                return
            elif opcode == 9:
                # Send Pong
                pong = bytearray([0x8A, 0x00])
                try: sock.send(pong)
                except Exception: pass
            elif opcode in (1, 2):
                if self.mgr:
                    self.mgr.record_activity()
                    self.mgr.ingest_data(payload, source="WIFI")

    def send_broadcast(self, data):
        """Broadcasts text frame to all connected WebSocket & TCP clients."""
        if not self.clients:
            return

        payload = data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")
        dead_clients = []

        for sock in self.clients:
            try:
                if self.ws_clients.get(sock, False):
                    # Wrap in WebSocket Text Frame (Opcode 1)
                    l = len(payload)
                    frame = bytearray([0x81])
                    if l < 126:
                        frame.append(l)
                    elif l <= 65535:
                        frame.append(126)
                        frame.extend(struct.pack("!H", l))
                    else:
                        frame.append(127)
                        frame.extend(struct.pack("!Q", l))
                    frame.extend(payload)
                    sock.send(frame)
                else:
                    sock.send(payload)
            except Exception:
                dead_clients.append(sock)

        for d in dead_clients:
            self._remove_client(d)
