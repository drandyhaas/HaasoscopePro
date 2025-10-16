#!/usr/bin/env python3
"""
Dummy Oscilloscope Server
Simulates a HaasoscopePro board via TCP socket for testing without hardware.
Connect with: HaasoscopeProQt.py --socket localhost:9999
"""

import socket
import struct
import threading
import argparse
import time
from typing import Dict, Tuple

class DummyOscilloscopeServer:
    """Minimal simulated oscilloscope board responding to HaasoscopePro commands."""

    def __init__(self, host: str = "localhost", port: int = 9998, firmware_version: int = 0x12345678):
        self.host = host
        self.port = port
        self.firmware_version = firmware_version
        self.running = False
        self.server_socket = None
        self.clients: Dict[socket.socket, str] = {}

        # Board state simulation
        self.board_state = {
            "trigger_ready": False,
            "fan_on": False,
            "fan_pwm": 128,
            "clk_out_enabled": True,
            "aux_out": 0,
            "board_position": 0,  # 0=middle, 1=first, 2=last
            "has_external_clock": False,  # For LVDS ordering
        }

    def start(self):
        """Start the dummy server."""
        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            print("Opening port",self.port)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            print(f"[DUMMY SERVER] Listening on {self.host}:{self.port}")
            print(f"[DUMMY SERVER] Firmware version: 0x{self.firmware_version:08x}")

            while self.running:
                try:
                    self.server_socket.settimeout(1.0)
                    client_socket, client_addr = self.server_socket.accept()
                    client_name = f"{client_addr[0]}:{client_addr[1]}"
                    self.clients[client_socket] = client_name
                    print(f"[DUMMY SERVER] Client connected: {client_name}")

                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket, client_name),
                        daemon=True
                    )
                    client_thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"[DUMMY SERVER] Error accepting connection: {e}")
        except Exception as e:
            print(f"[DUMMY SERVER] Server error: {e}")
        finally:
            self.stop()

    def _handle_client(self, client_socket: socket.socket, client_name: str):
        """Handle a single client connection."""
        try:
            while self.running:
                data = client_socket.recv(8)  # All commands are 8 bytes
                if not data or len(data) < 8:
                    break

                response = self._process_command(data)
                client_socket.sendall(response)

        except Exception as e:
            print(f"[DUMMY SERVER] Client {client_name} error: {e}")
        finally:
            client_socket.close()
            del self.clients[client_socket]
            print(f"[DUMMY SERVER] Client disconnected: {client_name}")

    def _process_command(self, data: bytes) -> bytes:
        """Process an 8-byte command and return response."""
        if len(data) < 8:
            return struct.pack("<I", 0xFFFFFFFF)  # Error response

        opcode = data[0]
        sub_cmd = data[1] if len(data) > 1 else 0

        # Opcode 2: General commands
        if opcode == 2:
            return self._handle_opcode2(sub_cmd, data)

        # Opcode 1: Trigger check
        elif opcode == 1:
            return self._handle_trigger_check(data)

        # Opcode 0: Read data
        elif opcode == 0:
            return self._handle_read_data(data)

        # Default: return dummy response (4 bytes)
        return struct.pack("<I", 0x00000000)

    def _handle_opcode2(self, sub_cmd: int, data: bytes) -> bytes:
        """Handle opcode 2 (general board commands)."""

        if sub_cmd == 0:
            # Get firmware version
            return struct.pack("<I", self.firmware_version)

        elif sub_cmd == 1:
            # Read board digital status
            status = 0x00000042  # Dummy status
            return struct.pack("<I", status)

        elif sub_cmd == 4:
            # Get pre-data (merge counter)
            return struct.pack("<I", 0)

        elif sub_cmd == 5:
            # Get LVDS info/status
            # Bit 0 = has external clock input (0 for first board, 1 for subsequent)
            has_clock = 1 if self.board_state["has_external_clock"] else 0
            return struct.pack("<I", has_clock)

        elif sub_cmd == 6:
            # Set fan on/off
            self.board_state["fan_on"] = bool(data[2])
            return struct.pack("<I", 0)

        elif sub_cmd == 7:
            # Set trigger pre-length
            return struct.pack("<I", 0)

        elif sub_cmd == 8:
            # Set rolling/external trigger mode
            return struct.pack("<I", 0)

        elif sub_cmd == 9:
            # Enable LVDS clock output
            self.board_state["clk_out_enabled"] = bool(data[2])
            return struct.pack("<I", 0)

        elif sub_cmd == 10:
            # Set aux output selector
            self.board_state["aux_out"] = data[2]
            return struct.pack("<I", 0)

        elif sub_cmd == 14:
            # Set first/last board
            self.board_state["board_position"] = data[2]
            return struct.pack("<I", 0)

        elif sub_cmd == 19:
            # Reload firmware from flash
            return struct.pack("<I", 0)

        elif sub_cmd == 20:
            # Set trigger delay/holdoff
            return struct.pack("<I", 0)

        elif sub_cmd == 21:
            # Set fan PWM duty cycle
            self.board_state["fan_pwm"] = data[2]
            return struct.pack("<I", 0)

        else:
            # Unknown sub-command
            return struct.pack("<I", 0)

    def _handle_trigger_check(self, data: bytes) -> bytes:
        """Handle opcode 1 (trigger status check)."""
        # Simple dummy: simulate trigger ready after a few calls
        if self.board_state["trigger_ready"]:
            # Event ready response: byte 0 = 251, byte 1 = counter
            return bytes([251, 0, 0, 0])
        else:
            # Not ready
            return bytes([0, 0, 0, 0])

    def _handle_read_data(self, data: bytes) -> bytes:
        """Handle opcode 0 (read captured data)."""
        # Return dummy ADC data: sine wave pattern
        expect_len = struct.unpack("<I", data[4:8])[0] if len(data) >= 8 else 100

        # For now, just return status byte
        return bytes([0, 0, 0, 0])

    def stop(self):
        """Stop the server."""
        self.running = False
        for client in list(self.clients.keys()):
            try:
                client.close()
            except:
                pass
        if self.server_socket:
            self.server_socket.close()
        print("[DUMMY SERVER] Server stopped")


def main():
    parser = argparse.ArgumentParser(
        description="Dummy oscilloscope server for testing HaasoscopePro"
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Server host (default: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9998,
        help="Server port (default: 9998)"
    )
    parser.add_argument(
        "--version",
        type=lambda x: int(x, 0),
        default=0x12345678,
        help="Firmware version as hex (default: 0x12345678)"
    )

    args = parser.parse_args()

    server = DummyOscilloscopeServer(
        host=args.host,
        port=args.port,
        firmware_version=args.version
    )

    try:
        print("Starting dummy oscilloscope server...")
        print("Press Ctrl+C to stop")
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
