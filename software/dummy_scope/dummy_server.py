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
            "pll_locked": True,  # PLL lock status (bit 5)
            "internal_clock": True,  # True=internal, False=external
            "adc_temp": 25.0,  # Simulated ADC die temperature
            "board_temp": 20.0,  # Simulated board temperature
            "channel_impedance": [False, False],  # False=50Ohm, True=1MOhm
            "channel_coupling": [False, False],  # False=DC, True=AC
            "channel_att": [False, False],  # False=no att, True=att
            "split_enabled": False,  # Clock splitter for oversampling
            "spi_mode": 0,  # Current SPI mode (0 or 1)
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

        # Opcode 0: Read data
        if opcode == 0:
            return self._handle_read_data(data)

        # Opcode 1: Trigger check
        elif opcode == 1:
            return self._handle_trigger_check(data)

        # Opcode 2: General commands
        elif opcode == 2:
            return self._handle_opcode2(sub_cmd, data)

        # Opcode 3: SPI transaction
        elif opcode == 3:
            return self._handle_spi_transaction(data)

        # Opcode 4: Set SPI mode
        elif opcode == 4:
            return self._handle_set_spi_mode(data)

        # Opcode 5: PLL reset
        elif opcode == 5:
            return self._handle_pll_reset(data)

        # Opcode 6: Phase adjust
        elif opcode == 6:
            return self._handle_phase_adjust(data)

        # Opcode 7: Clock switch
        elif opcode == 7:
            return self._handle_clock_switch(data)

        # Opcode 8: Trigger info/level
        elif opcode == 8:
            return self._handle_trigger_info(data)

        # Opcode 9: Set downsample/merge
        elif opcode == 9:
            return self._handle_downsample(data)

        # Opcode 10: Set channel parameters
        elif opcode == 10:
            return self._handle_channel_control(data)

        # Opcode 11: Send LED RGB values
        elif opcode == 11:
            return self._handle_led_control(data)

        # Default: return dummy response (4 bytes)
        return struct.pack("<I", 0x00000000)

    def _handle_opcode2(self, sub_cmd: int, data: bytes) -> bytes:
        """Handle opcode 2 (general board commands)."""

        if sub_cmd == 0:
            # Get firmware version
            return struct.pack("<I", self.firmware_version)

        elif sub_cmd == 1:
            # Read board digital status
            # Bit 5 must be 1 for PLL locked
            status = 0x20 if self.board_state["pll_locked"] else 0x00
            return struct.pack("<I", status)

        elif sub_cmd == 4:
            # Get pre-data (merge counter)
            return struct.pack("<I", 0)

        elif sub_cmd == 5:
            # Get LVDS info/status (clockused checks bits)
            # Bit 1: external clock lock status
            # Bit 3: no external clock input (for first board)
            response = 0
            if self.board_state["internal_clock"]:
                response |= (1 << 3)  # Set bit 3 for internal clock (first board)
            else:
                response |= (1 << 1)  # Set bit 1 for external clock locked
            return struct.pack("<I", response)

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

    def _handle_spi_transaction(self, data: bytes) -> bytes:
        """Handle opcode 3 (SPI transaction)."""
        # cs = data[1], nbyte = data[7]
        # Return dummy SPI response (vendor ID 0x51 for ADC, etc.)
        return bytes([0x51, 0x00, 0x00, 0x00])

    def _handle_set_spi_mode(self, data: bytes) -> bytes:
        """Handle opcode 4 (set SPI mode)."""
        mode = data[1]
        self.board_state["spi_mode"] = mode
        return struct.pack("<I", 0)

    def _handle_pll_reset(self, data: bytes) -> bytes:
        """Handle opcode 5 (PLL reset)."""
        self.board_state["pll_locked"] = True
        return struct.pack("<I", 0)

    def _handle_phase_adjust(self, data: bytes) -> bytes:
        """Handle opcode 6 (phase adjust)."""
        # pllnum = data[1], plloutnum = data[2], updown = data[3]
        return struct.pack("<I", 0)

    def _handle_clock_switch(self, data: bytes) -> bytes:
        """Handle opcode 7 (clock switch)."""
        # Toggle clock source
        self.board_state["internal_clock"] = not self.board_state["internal_clock"]
        return struct.pack("<I", 0)

    def _handle_trigger_info(self, data: bytes) -> bytes:
        """Handle opcode 8 (trigger info/level)."""
        return struct.pack("<I", 0)

    def _handle_downsample(self, data: bytes) -> bytes:
        """Handle opcode 9 (set downsample/merge)."""
        return struct.pack("<I", 0)

    def _handle_channel_control(self, data: bytes) -> bytes:
        """Handle opcode 10 (set channel parameters)."""
        controlbit = data[1]
        value = data[2]

        # Handle channel impedance/coupling/att control
        if controlbit == 0:
            self.board_state["channel_impedance"][0] = bool(value)
        elif controlbit == 1:
            self.board_state["channel_coupling"][0] = bool(value)
        elif controlbit == 2:
            self.board_state["channel_att"][0] = bool(value)
        elif controlbit == 4:
            self.board_state["channel_impedance"][1] = bool(value)
        elif controlbit == 5:
            self.board_state["channel_coupling"][1] = bool(value)
        elif controlbit == 6:
            self.board_state["channel_att"][1] = bool(value)
        elif controlbit == 7:
            self.board_state["split_enabled"] = bool(value)

        return struct.pack("<I", 0)

    def _handle_led_control(self, data: bytes) -> bytes:
        """Handle opcode 11 (send LED RGB values)."""
        # data[1] = led_enable, data[2:8] = RGB values
        return struct.pack("<I", 0)

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
