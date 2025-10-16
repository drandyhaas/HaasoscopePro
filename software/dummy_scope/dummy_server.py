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
import math
import random
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
            "trigger_counter": 0,  # Incrementing trigger counter
            "data_counter": 0,  # For phase continuity in generated data
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
            # Return 1 to keep downsamplemergingcounter stable
            # (real hardware increments this, but for dummy we keep it constant)
            return struct.pack("<I", 1)

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
        # Always simulate trigger ready - continuously return new events
        # Event ready response: byte 0 = 251, byte 1 = trigger position, bytes 2-3 = unused
        # Return trigger position of 0 in byte 1
        # This combined with triggerpos=50 will center the trigger in the display
        trigger_pos = 0
        return bytes([251, trigger_pos, 0, 0])

    def _handle_read_data(self, data: bytes) -> bytes:
        """Handle opcode 0 (read captured data)."""
        # Extract expected data length from bytes [4:8]
        expect_len = struct.unpack("<I", data[4:8])[0] if len(data) >= 8 else 1000

        # The real USB protocol may return 8 bytes of header/status before the data.
        # To match that behavior over TCP/socket, we return: [4-byte status][4-byte count][data]
        # The client's recv() will handle this properly with our buffering logic.

        # Data format: nsubsamples = 50 words per sample
        # Based on data_processor.py line 189:
        #   vals = unpackedsamples[s * nsubsamples + 40: s * nsubsamples + 50]
        # So words 40-49 contain timing info and marker:
        #   vals[0:4]   = clocks (should be 341 or 682)
        #   vals[4:8]   = strobes (should be one-hot: 1, 2, 4, 8, 16, 32, 64, 128)
        #   vals[8]     = control (should be 0)
        #   vals[9]     = marker (should be -16657 / 0xBEEF)
        # Words 0-39 are actual ADC data (20 samples per channel in two-channel mode)

        # Reset data counter at the start of each trigger event to ensure phase starts from 0
        self.board_state["data_counter"] = 0

        # Generate per-event random parameters
        # Time shift: Gaussian distribution with RMS = 1 sample (1/3.2 ns ≈ 0.3125 ns)
        # Sample period at 3.2 GHz = 1/3.2 ns ≈ 0.3125 ns
        sample_period = 1.0 / 3.2  # ns per sample
        time_shift_samples = random.gauss(0, 1.0)  # RMS of 1 sample
        time_shift_ns = time_shift_samples * sample_period

        # Noise: 2% RMS of the signal amplitude
        # ADC is 12-bit, amplitude 1500
        signal_amplitude = 1500
        noise_rms = 0.02 * signal_amplitude  # ~30 ADC counts

        adc_data = bytearray()
        nsubsamples = 50
        bytes_per_sample = nsubsamples * 2  # 100 bytes per sample (50 words * 2 bytes/word)
        num_logical_samples = expect_len // bytes_per_sample

        for s in range(num_logical_samples):
            # Words 0-39: ADC data (40 samples for single-channel mode)
            # In single-channel mode: words 0-39 are all from the single channel
            # Generate continuous sine wave data centered at 0 (symmetric around zero)
            # ADC is 12-bit, so range is -2048 to +2047

            # Start sample index for this block
            sample_index = self.board_state["data_counter"] * 40

            # Words 0-39: 40 consecutive ADC samples
            # Period: 1000 samples = 4 cycles across the 4000-sample capture window
            # Amplitude: 1500 (12-bit ADC), shifted to upper 12 bits when packing
            for i in range(40):
                # Apply time shift to each sample (fractional sample interpolation)
                sample_position = sample_index + i + time_shift_samples
                phase = sample_position * 2 * math.pi / 1000
                val = int(signal_amplitude * math.sin(phase))
                # Add Gaussian noise (~2% RMS)
                noise = random.gauss(0, noise_rms)
                val = int(val + noise)
                # Clamp to 12-bit signed range (-2048 to 2047)
                val = max(-2048, min(2047, val))
                # Shift to upper 12 bits of 16-bit short
                adc_data.extend(struct.pack("<h", val << 4))

            # Words 40-49: Timing and marker
            # Clocks (words 40-43): vals[0:4] should be 341 or 682
            for clk_idx in range(4):
                clock_val = 341 if (self.board_state["data_counter"] + clk_idx) % 2 == 0 else 682
                adc_data.extend(struct.pack("<h", clock_val))

            # Strobes (words 44-47): vals[4:8] should be one-hot encoded
            # Comment says "10*4 clks + 8 strs", but we only have 4 strobe words in vals[4:8]
            # So we generate a cycling pattern of one-hot values
            for strobe_idx in range(4):
                # Cycle through one-hot patterns: 1, 2, 4, 8, 16, 32, 64, 128
                strobe_pattern = [1, 2, 4, 8, 16, 32, 64, 128]
                strobe_val = strobe_pattern[(self.board_state["data_counter"] + strobe_idx) % 8]
                adc_data.extend(struct.pack("<h", strobe_val))

            # Word 48 (vals[8]): Control byte (should be 0)
            adc_data.extend(struct.pack("<h", 0))

            # Word 49 (vals[9]): 0xBEEF marker (-16657 in signed 16-bit)
            adc_data.extend(struct.pack("<h", -16657))

            self.board_state["data_counter"] += 1

        # Handle any remaining bytes by generating a partial block
        remainder = expect_len % bytes_per_sample
        if remainder > 0:
            # Generate one more partial block
            sample_index = self.board_state["data_counter"] * 40

            # Calculate how many complete words we need
            words_needed = remainder // 2

            # Generate ADC data words (up to 40)
            for i in range(min(words_needed, 40)):
                # Apply time shift to each sample (fractional sample interpolation)
                sample_position = sample_index + i + time_shift_samples
                phase = sample_position * 2 * math.pi / 1000
                val = int(signal_amplitude * math.sin(phase))
                # Add Gaussian noise (~2% RMS)
                noise = random.gauss(0, noise_rms)
                val = int(val + noise)
                # Clamp to 12-bit signed range (-2048 to 2047)
                val = max(-2048, min(2047, val))
                # Shift to upper 12 bits of 16-bit short
                adc_data.extend(struct.pack("<h", val << 4))

            # If we need more words beyond the 40 ADC samples, generate timing/marker data
            if words_needed > 40:
                # Clocks (words 40-43)
                for clk_idx in range(min(4, words_needed - 40)):
                    clock_val = 341 if (self.board_state["data_counter"] + clk_idx) % 2 == 0 else 682
                    adc_data.extend(struct.pack("<h", clock_val))

                # Strobes (words 44-47)
                if words_needed > 44:
                    for strobe_idx in range(min(4, words_needed - 44)):
                        strobe_pattern = [1, 2, 4, 8, 16, 32, 64, 128]
                        strobe_val = strobe_pattern[(self.board_state["data_counter"] + strobe_idx) % 8]
                        adc_data.extend(struct.pack("<h", strobe_val))

                # Control (word 48)
                if words_needed > 48:
                    adc_data.extend(struct.pack("<h", 0))

                # Marker (word 49)
                if words_needed > 49:
                    adc_data.extend(struct.pack("<h", -16657))

            self.board_state["data_counter"] += 1

        return bytes(adc_data)

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
