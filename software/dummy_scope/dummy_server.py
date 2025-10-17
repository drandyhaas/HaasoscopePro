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
            # Trigger settings (from opcode 8)
            "trigger_level": 0,  # Voltage threshold for triggering (0-255, maps to ADC value)
            "trigger_delta": 0,  # Trigger hysteresis
            "trigger_pos": 0,  # Position in waveform where trigger should occur
            "trigger_time_thresh": 0,  # Timing threshold
            "trigger_chan": 0,  # Channel to trigger on
            # Downsample settings (from opcode 9)
            "downsample_ds": 0,  # Downsample factor (power of 2)
            "downsample_highres": 1,  # 1 = averaging mode, 0 = decimation mode
            "downsample_merging": 1,  # Number of samples to merge
            # Trigger type (from opcode 1)
            "trigger_type": 1,  # 1 = rising edge, 2 = falling edge
            # Channel mode (from opcode 1, data[2])
            "two_channel_mode": False,  # False = single channel (3.2 GS/s), True = two channel (1.6 GS/s per channel)
            # Gain and offset (from SPI commands)
            "channel_gain": [0, 0],  # Gain in dB for each channel (0 = 0dB = 1x)
            "channel_offset": [0, 0],  # Offset in ADC counts for each channel
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
        # Parse trigger type from data[1]
        # 1 = rising edge, 2 = falling edge
        trigger_type = data[1]
        self.board_state["trigger_type"] = trigger_type

        # Parse two-channel mode from data[2]
        # data[2] = is_two_channel + 2 * state.dooversample[board_idx]
        # For non-oversampling mode: data[2] = 0 (single channel) or 1 (two channel)
        channel_mode_byte = data[2]
        is_two_channel = (channel_mode_byte % 2) == 1  # Extract the LSB
        self.board_state["two_channel_mode"] = is_two_channel

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
        # Time shift: Uniformly distributed between 0 and 1 sample period of the trigger channel
        # In single-channel mode: trigger samples at 3.2 GS/s, so jitter is 0 to 1/3.2 ns
        # In two-channel mode: trigger samples at 1.6 GS/s, so jitter is 0 to 1/1.6 ns (2x larger)
        two_channel_mode = self.board_state["two_channel_mode"]
        base_sample_period = 1.0 / 3.2  # ns per base sample at 3.2 GHz

        # Time jitter: uniform distribution between 0 and 1 trigger channel sample period
        # This represents timing uncertainty in the trigger
        if two_channel_mode:
            # In two-channel mode, trigger channel samples at 1.6 GS/s (half rate)
            # So jitter is 2x larger: 0 to 2/3.2 ns = 0 to 1/1.6 ns
            time_shift_ns = random.uniform(0, 2 * base_sample_period)
            # Convert time shift to base sample units for phase calculations
            time_shift_samples = time_shift_ns / base_sample_period
        else:
            # In single-channel mode, trigger channel samples at 3.2 GS/s
            # Jitter is 0 to 1/3.2 ns
            time_shift_ns = random.uniform(0, base_sample_period)
            # Convert time shift to base sample units for phase calculations
            time_shift_samples = time_shift_ns / base_sample_period

        # Noise: 2% RMS of the signal amplitude
        # ADC is 12-bit, amplitude 1500
        signal_amplitude = 1500
        noise_rms = 0.01 * signal_amplitude  # ~15 ADC counts

        # Convert trigger level from 0-255 range to ADC 12-bit range (-2048 to +2047)
        # trigger_level is sent as (state.triggerlevel+1), so we need to subtract 1
        trigger_level_raw = self.board_state["trigger_level"] - 1
        # Map 0-254 to ADC range: 0 -> -2048, 127 -> 0, 254 -> +2047
        trigger_level_adc = int((trigger_level_raw - 127) * 2047 / 127)

        # Get trigger type (1 = rising, 2 = falling)
        trigger_type = self.board_state["trigger_type"]
        is_falling = (trigger_type == 2)

        # Apply triggerdelta based on edge direction:
        # - Rising edge: signal must cross UP through (trigger_level + triggerdelta)
        # - Falling edge: signal must cross DOWN through (trigger_level - triggerdelta)
        trigger_delta = self.board_state["trigger_delta"]
        trigger_delta_adc = int(trigger_delta * 2047 / 127)
        if is_falling:
            actual_trigger_level_adc = trigger_level_adc - trigger_delta_adc
        else:
            actual_trigger_level_adc = trigger_level_adc + trigger_delta_adc

        # Get trigger position (in logical sample blocks) and convert to ADC sample index
        # Each logical sample block contains 40 ADC samples (words 0-39)
        # Note: trigger_pos already includes triggershift (see hardware_controller.py:214)
        # IMPORTANT: The software expects the trigger at (triggerpos + 1) * 40 samples
        # (see data_processor.py:275 - vline_time uses triggerpos + 1.0)
        trigger_pos_blocks = self.board_state["trigger_pos"]
        trigger_pos = (trigger_pos_blocks + 1) * 40

        adc_data = bytearray()
        nsubsamples = 50
        bytes_per_sample = nsubsamples * 2  # 100 bytes per sample (50 words * 2 bytes/word)
        num_logical_samples = expect_len // bytes_per_sample

        # Get gain and offset BEFORE calculating trigger_possible
        # We need these to determine the actual waveform range
        trigger_chan = self.board_state["trigger_chan"]

        # Determine which channel's gain/offset to use based on trigger channel
        # In two-channel mode: ch0 and ch1 are separate
        # In single-channel mode: always use ch0 (since that's the active channel)
        two_channel_mode = self.board_state["two_channel_mode"]

        if two_channel_mode:
            # Use the gain/offset of the trigger channel
            trigger_gain_db = self.board_state["channel_gain"][trigger_chan]
            trigger_offset_adc = self.board_state["channel_offset"][trigger_chan]
        else:
            # Single channel mode - always use ch0
            trigger_gain_db = self.board_state["channel_gain"][0]
            trigger_offset_adc = self.board_state["channel_offset"][0]

        # Convert gain from dB to linear
        trigger_gain = pow(10, trigger_gain_db / 20.0)

        # Calculate the actual amplitude of the trigger channel after gain
        trigger_amplitude = signal_amplitude * trigger_gain

        # For square wave (ch1), use 70% amplitude
        if two_channel_mode and trigger_chan == 1:
            trigger_amplitude = signal_amplitude * 0.7 * trigger_gain

        # Calculate phase offset so the waveform crosses actual_trigger_level_adc at trigger_pos
        # The waveform (after gain and offset) ranges from:
        #   (trigger_offset_adc - trigger_amplitude) to (trigger_offset_adc + trigger_amplitude)
        # For triggering to be possible, actual_trigger_level_adc must be within this range
        trigger_possible = (trigger_amplitude > 0 and
                          actual_trigger_level_adc >= (trigger_offset_adc - trigger_amplitude) and
                          actual_trigger_level_adc <= (trigger_offset_adc + trigger_amplitude))

        if trigger_possible:
            # Normalize the trigger level relative to the offset center
            normalized_level = (actual_trigger_level_adc - trigger_offset_adc) / trigger_amplitude
            # Clamp to valid range for arcsin
            normalized_level = max(-1.0, min(1.0, normalized_level))

            if is_falling:
                # Falling edge: sin(phase) = level with negative derivative (going down)
                # This occurs at phase = π - arcsin(level)
                phase_at_trigger = math.pi - math.asin(normalized_level)
            else:
                # Rising edge: sin(phase) = level with positive derivative (going up)
                # This occurs at phase = arcsin(level)
                phase_at_trigger = math.asin(normalized_level)
        else:
            # Trigger level is out of range - trigger not possible
            # Use random phase since the waveform won't cross the threshold
            phase_at_trigger = random.uniform(0, 2 * math.pi)

        # Calculate the effective downsample factor
        ds = self.board_state["downsample_ds"]
        merging = self.board_state["downsample_merging"]
        highres = self.board_state["downsample_highres"]
        downsample_factor = merging * (2 ** ds)

        # Period: 1000 samples = 4 cycles across the 4000-sample capture window (at full rate)
        # This doesn't change with downsampling - the output samples are still at the same rate
        wave_period = 1000.0
        # Calculate phase offset so that at trigger_pos, we have the trigger crossing
        # phase = (sample_position - phase_offset) * 2*pi / period
        # At trigger_pos: phase = phase_at_trigger
        # So: phase_offset = trigger_pos - (phase_at_trigger * period) / (2*pi)
        phase_offset = trigger_pos - (phase_at_trigger * wave_period) / (2 * math.pi)

        # Check if we're in two-channel mode
        two_channel_mode = self.board_state["two_channel_mode"]

        # For two-channel mode: generate random phase offsets for the non-triggered channel
        # since there's no phase coherence between the two channels

        if two_channel_mode:
            # Generate random phase offsets for both channels
            # We'll apply trigger alignment to the triggered channel only
            ch0_random_phase = random.uniform(0, 2 * math.pi)
            ch1_random_phase = random.uniform(0, 2 * math.pi)
        else:
            ch0_random_phase = 0
            ch1_random_phase = 0

        # Get gain and offset for both channels
        # Gain is in dB, convert to linear: gain_linear = 10^(gain_db/20)
        ch0_gain = pow(10, self.board_state["channel_gain"][0] / 20.0)
        ch1_gain = pow(10, self.board_state["channel_gain"][1] / 20.0)
        ch0_offset = self.board_state["channel_offset"][0]
        ch1_offset = self.board_state["channel_offset"][1]

        for s in range(num_logical_samples):
            # Words 0-39: ADC data
            # In single-channel mode: words 0-39 are all from channel 1 at 3.2 GS/s (40 samples)
            # In two-channel mode: words 0-19 are channel 2, words 20-39 are channel 1, each at 1.6 GS/s (20 samples each)
            # Generate triggered sine wave data
            # ADC is 12-bit, so range is -2048 to +2047

            # Start sample index for this block
            if two_channel_mode:
                # In two-channel mode, each logical block has 20 samples per channel
                # Sample index for channel 1 (used for triggering)
                sample_index = self.board_state["data_counter"] * 20
            else:
                # In single-channel mode, each logical block has 40 samples
                sample_index = self.board_state["data_counter"] * 40

            if two_channel_mode:
                # Two-channel mode: Generate 20 samples for channel 1 (words 0-19), then 20 for channel 0 (words 20-39)
                # Each channel samples at 1.6 GS/s (half the single-channel rate)
                # Channel 0 (words 20-39) should have the SAME waveform as in single-channel mode (trigger channel)
                # Channel 1 (words 0-19) can have different data (e.g., a 100 MHz square wave)
                # The base waveform has period 1000 samples at 3.2 GHz base rate
                # When downsampling by factor N:
                #   - Each output sample represents N input samples averaged/decimated
                #   - Output sample i corresponds to base sample positions i*N to i*N+N-1
                # Amplitude: 1500 (12-bit ADC), shifted to upper 12 bits when packing

                # Channel 1 (words 0-19): Generate a 100 MHz square wave for variety
                # 100 MHz at 1.6 GS/s = 16 samples per cycle
                # Apply trigger alignment if triggering on ch1, otherwise use random phase
                square_period = 16.0  # 100 MHz at 1.6 GS/s base rate
                for i in range(20):
                    # In two-channel mode, samples are spaced 2x further apart (1.6 GS/s vs 3.2 GS/s)
                    # So each output sample i represents base samples at positions i*2, i*2+1 (interleaved)
                    if downsample_factor == 1:
                        # No downsampling - generate sample at 1.6 GS/s rate
                        # Channel 1 uses even-numbered base samples (0, 2, 4, ...)
                        base_sample_pos = (sample_index + i) * 2 + time_shift_samples
                        # Position in 1.6 GS/s samples (divide by 2 since we're using every other base sample)
                        ch1_sample_pos = base_sample_pos / 2
                        if trigger_chan == 1 and trigger_possible:
                            # Triggering on ch1 and trigger is possible - align to trigger position
                            # Trigger position is in base samples, convert to ch1 samples
                            ch1_trigger_pos = trigger_pos / 2
                            square_phase = ((ch1_sample_pos - ch1_trigger_pos) % square_period) / square_period
                            # For falling edge, shift by half period to trigger on falling edge instead of rising
                            if is_falling:
                                square_phase = (square_phase + 0.5) % 1.0
                        else:
                            # Not triggering on ch1 or trigger not possible - use random phase
                            square_phase = ((ch1_sample_pos + ch1_random_phase * square_period / (2 * math.pi)) % square_period) / square_period
                        # Convert phase to square wave value, apply gain
                        val = int(signal_amplitude * 0.7 * (1 if square_phase < 0.5 else -1) * ch1_gain)
                        noise = random.gauss(0, noise_rms)
                        val = int(val + noise + ch1_offset)
                    elif highres == 1:
                        # Averaging mode
                        val_sum = 0
                        base_start = (sample_index + i) * 2 * downsample_factor
                        for j in range(downsample_factor):
                            base_sample_pos = base_start + j * 2 + time_shift_samples
                            ch1_sample_pos = base_sample_pos / 2
                            if trigger_chan == 1 and trigger_possible:
                                ch1_trigger_pos = trigger_pos / 2
                                square_phase = ((ch1_sample_pos - ch1_trigger_pos) % square_period) / square_period
                                if is_falling:
                                    square_phase = (square_phase + 0.5) % 1.0
                            else:
                                square_phase = ((ch1_sample_pos + ch1_random_phase * square_period / (2 * math.pi)) % square_period) / square_period
                            base_val = int(signal_amplitude * 0.7 * (1 if square_phase < 0.5 else -1) * ch1_gain)
                            noise = random.gauss(0, noise_rms)
                            val_sum += base_val + noise
                        # Apply offset to averaged value
                        val = int(val_sum / downsample_factor + ch1_offset)
                    else:
                        # Decimation mode
                        base_sample_pos = (sample_index + i) * 2 * downsample_factor + time_shift_samples
                        ch1_sample_pos = base_sample_pos / 2
                        if trigger_chan == 1 and trigger_possible:
                            ch1_trigger_pos = trigger_pos / 2
                            square_phase = ((ch1_sample_pos - ch1_trigger_pos) % square_period) / square_period
                            if is_falling:
                                square_phase = (square_phase + 0.5) % 1.0
                        else:
                            square_phase = ((ch1_sample_pos + ch1_random_phase * square_period / (2 * math.pi)) % square_period) / square_period
                        val = int(signal_amplitude * 0.7 * (1 if square_phase < 0.5 else -1) * ch1_gain)
                        noise = random.gauss(0, noise_rms)
                        val = int(val + noise + ch1_offset)

                    # Clamp to 12-bit signed range (-2048 to 2047)
                    val = max(-2048, min(2047, val))
                    # Shift to upper 12 bits of 16-bit short
                    adc_data.extend(struct.pack("<h", val << 4))

                # Channel 0 (words 20-39): Generate sine wave
                # Apply trigger alignment if triggering on ch0, otherwise use random phase
                for i in range(20):
                    if downsample_factor == 1:
                        # No downsampling - generate sample at 1.6 GS/s rate
                        # Channel 0 uses odd-numbered base samples (1, 3, 5, ...) - but offset by 1
                        base_sample_pos = (sample_index + i) * 2 + 1 + time_shift_samples
                        if trigger_chan == 0:
                            # Triggering on ch0 - align to trigger position
                            phase = (base_sample_pos - phase_offset) * 2 * math.pi / wave_period
                        else:
                            # Not triggering on ch0 - use random phase
                            phase = base_sample_pos * 2 * math.pi / wave_period + ch0_random_phase
                        val = int(signal_amplitude * math.sin(phase) * ch0_gain)
                        noise = random.gauss(0, noise_rms)
                        val = int(val + noise + ch0_offset)
                    elif highres == 1:
                        # Averaging mode
                        val_sum = 0
                        base_start = (sample_index + i) * 2 * downsample_factor + 1
                        for j in range(downsample_factor):
                            base_sample_pos = base_start + j * 2 + time_shift_samples
                            if trigger_chan == 0:
                                phase = (base_sample_pos - phase_offset * downsample_factor) * 2 * math.pi / wave_period
                            else:
                                phase = base_sample_pos * 2 * math.pi / wave_period + ch0_random_phase
                            base_val = int(signal_amplitude * math.sin(phase) * ch0_gain)
                            noise = random.gauss(0, noise_rms)
                            val_sum += base_val + noise
                        val = int(val_sum / downsample_factor + ch0_offset)
                    else:
                        # Decimation mode
                        base_sample_pos = (sample_index + i) * 2 * downsample_factor + 1 + time_shift_samples
                        if trigger_chan == 0:
                            phase = (base_sample_pos - phase_offset * downsample_factor) * 2 * math.pi / wave_period
                        else:
                            phase = base_sample_pos * 2 * math.pi / wave_period + ch0_random_phase
                        val = int(signal_amplitude * math.sin(phase) * ch0_gain)
                        noise = random.gauss(0, noise_rms)
                        val = int(val + noise + ch0_offset)

                    # Clamp to 12-bit signed range (-2048 to 2047)
                    val = max(-2048, min(2047, val))
                    # Shift to upper 12 bits of 16-bit short
                    adc_data.extend(struct.pack("<h", val << 4))

            else:
                # Single-channel mode: Words 0-39 are 40 consecutive ADC samples at 3.2 GS/s
                # The base waveform has period 1000 samples at 3.2 GHz (doesn't change with downsampling)
                # When downsampling by factor N:
                #   - Each output sample represents N input samples averaged/decimated
                #   - Output sample i corresponds to base sample positions i*N to i*N+N-1
                # Amplitude: 1500 (12-bit ADC), shifted to upper 12 bits when packing
                for i in range(40):
                    if downsample_factor == 1:
                        # No downsampling - generate sample directly at base rate
                        base_sample_pos = sample_index + i + time_shift_samples
                        phase = (base_sample_pos - phase_offset) * 2 * math.pi / wave_period
                        val = int(signal_amplitude * math.sin(phase) * ch0_gain)
                        noise = random.gauss(0, noise_rms)
                        val = int(val + noise + ch0_offset)
                    elif highres == 1:
                        # Averaging mode: average downsample_factor base-rate samples together
                        # Output sample i averages base samples from (sample_index+i)*N to (sample_index+i)*N + N-1
                        val_sum = 0
                        base_start = (sample_index + i) * downsample_factor
                        for j in range(downsample_factor):
                            base_sample_pos = base_start + j + time_shift_samples
                            phase = (base_sample_pos - phase_offset * downsample_factor) * 2 * math.pi / wave_period
                            base_val = int(signal_amplitude * math.sin(phase) * ch0_gain)
                            noise = random.gauss(0, noise_rms)
                            val_sum += base_val + noise
                        val = int(val_sum / downsample_factor + ch0_offset)
                    else:
                        # Decimation mode: pick the first sample of every N base-rate samples
                        base_sample_pos = (sample_index + i) * downsample_factor + time_shift_samples
                        phase = (base_sample_pos - phase_offset * downsample_factor) * 2 * math.pi / wave_period
                        val = int(signal_amplitude * math.sin(phase) * ch0_gain)
                        noise = random.gauss(0, noise_rms)
                        val = int(val + noise + ch0_offset)

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
                if downsample_factor == 1:
                    # No downsampling - generate sample directly at base rate
                    base_sample_pos = sample_index + i + time_shift_samples
                    phase = (base_sample_pos - phase_offset) * 2 * math.pi / wave_period
                    val = int(signal_amplitude * math.sin(phase) * ch0_gain)
                    noise = random.gauss(0, noise_rms)
                    val = int(val + noise + ch0_offset)
                elif highres == 1:
                    # Averaging mode: average downsample_factor base-rate samples together
                    val_sum = 0
                    base_start = (sample_index + i) * downsample_factor
                    for j in range(downsample_factor):
                        base_sample_pos = base_start + j + time_shift_samples
                        phase = (base_sample_pos - phase_offset * downsample_factor) * 2 * math.pi / wave_period
                        base_val = int(signal_amplitude * math.sin(phase) * ch0_gain)
                        noise = random.gauss(0, noise_rms)
                        val_sum += base_val + noise
                    val = int(val_sum / downsample_factor + ch0_offset)
                else:
                    # Decimation mode: pick the first sample of every N base-rate samples
                    base_sample_pos = (sample_index + i) * downsample_factor + time_shift_samples
                    phase = (base_sample_pos - phase_offset * downsample_factor) * 2 * math.pi / wave_period
                    val = int(signal_amplitude * math.sin(phase) * ch0_gain)
                    noise = random.gauss(0, noise_rms)
                    val = int(val + noise + ch0_offset)

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
        # SPI transaction format: [opcode=3, cs, addr, b1, b2, b3, b4, nbyte]
        # cs = data[1] (chip select)
        # addr = data[2] (SPI address/command)
        # b1-b4 = data[3:7] (data bytes)
        # nbyte = data[7] (number of bytes)

        cs = data[1]
        addr = data[2]
        b1 = data[3]
        b2 = data[4] if len(data) > 4 else 0

        # Detect gain setting (SPI mode 0)
        # setgain: cs=2 (ch0) or cs=1 (ch1), addr=0x02, b1=0x00, b2=(26-gain_db)
        if self.board_state["spi_mode"] == 0 and addr == 0x02:
            if cs == 2:  # Channel 0 gain
                self.board_state["channel_gain"][0] = 26 - b2
            elif cs == 1:  # Channel 1 gain
                self.board_state["channel_gain"][1] = 26 - b2

        # Detect offset setting (SPI mode 1)
        # dooffset: cs=4, addr=0x19 (ch0) or 0x18 (ch1), b1=high byte, b2=low byte
        if self.board_state["spi_mode"] == 1 and cs == 4:
            dac_value = (b1 << 8) | b2
            # Convert DAC value back to offset in ADC counts
            # DAC range is 0-65535, centered at 32768
            # Map to ADC 12-bit range (-2048 to +2047)
            # From dooffset: dacval = int((pow(2, 16) - 1) * (val * scaling / 2 + 500) / 1000)
            # Reverse: val * scaling / 2 + 500 = dac_value * 1000 / 65535
            # For dummy purposes, we'll use a simplified conversion
            # assuming scaling ≈ 1 for now, so offset in mV ≈ 2 * (dac_value * 1000 / 65535 - 500)
            offset_mv = 2 * (dac_value * 1000 / 65535 - 500)
            # Convert mV to ADC counts (assuming basevoltage=200mV maps to full ADC range)
            # ADC range: ±2048 counts for ±200mV, so 1mV ≈ 10.24 counts
            offset_adc = int(offset_mv * 2048 / 200)

            if addr == 0x19:  # Channel 0 offset
                self.board_state["channel_offset"][0] = offset_adc
            elif addr == 0x18:  # Channel 1 offset
                self.board_state["channel_offset"][1] = offset_adc

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
        # Parse trigger parameters:
        # data[1] = trigger_level (0-255)
        # data[2] = trigger_delta (hysteresis)
        # data[3:5] = trigger_pos (16-bit)
        # data[5] = trigger_time_thresh
        # data[6] = trigger_chan
        self.board_state["trigger_level"] = data[1]
        self.board_state["trigger_delta"] = data[2]
        self.board_state["trigger_pos"] = (data[3] << 8) | data[4]
        self.board_state["trigger_time_thresh"] = data[5]
        self.board_state["trigger_chan"] = data[6]
        return struct.pack("<I", 0)

    def _handle_downsample(self, data: bytes) -> bytes:
        """Handle opcode 9 (set downsample/merge)."""
        # Parse downsample parameters:
        # data[1] = ds (downsample factor as power of 2)
        # data[2] = highres (1 = averaging, 0 = decimation)
        # data[3] = downsamplemerging (number of samples to merge)
        # Total downsample factor = downsamplemerging * 2^ds
        self.board_state["downsample_ds"] = data[1]
        self.board_state["downsample_highres"] = data[2]
        self.board_state["downsample_merging"] = data[3]
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
