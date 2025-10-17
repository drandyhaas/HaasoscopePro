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

    def __init__(self, host: str = "localhost", port: int = 9998, firmware_version: int = 0):
        self.host = host
        self.port = port
        self.firmware_version = firmware_version
        self.running = False
        self.server_socket = None
        self.clients: Dict[socket.socket, str] = {}

        # Per-channel waveform configuration
        self.channel_config = {
            0: {
                "wave_type": "pulse",  # "sine", "square", "pulse"
                "frequency": 3.2e6,  # Hz (3.2 MHz = 1000 samples per period at 3.2 GS/s)
                "amplitude": 1500,  # ADC counts (for sine/square waves)
                "pulse_tau_rise": 10.0,  # samples (rise time constant for pulse)
                "pulse_tau_decay": 50.0,  # samples (decay time constant for pulse)
                "pulse_amplitude_min": 100,  # minimum pulse amplitude (ADC counts)
                "pulse_amplitude_max": 2000,  # maximum pulse amplitude (ADC counts)
            },
            1: {
                "wave_type": "pulse",  # "sine", "square", "pulse"
                "frequency": 100e6,  # Hz (100 MHz)
                "amplitude": 1500,  # ADC counts (for sine/square waves)
                "pulse_tau_rise": 8.0,  # samples
                "pulse_tau_decay": 40.0,  # samples
                "pulse_amplitude_min": 10,  # minimum pulse amplitude (ADC counts)
                "pulse_amplitude_max": 500,  # maximum pulse amplitude (ADC counts)
            }
        }

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
            print(f"[DUMMY SERVER] Firmware version: {self.firmware_version}")

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

    def _generate_double_exponential_pulse(self, t: float, t0: float, amplitude: float,
                                          tau_rise: float, tau_decay: float) -> float:
        """
        Generate a double-exponential pulse value at time t.

        Formula: A * (e^{-(t-t₀)/τ_d} - e^{-(t-t₀)/τ_r})

        Args:
            t: Current time (sample index)
            t0: Pulse start time (sample index)
            amplitude: Pulse amplitude
            tau_rise: Rise time constant (samples)
            tau_decay: Decay time constant (samples)

        Returns:
            Pulse value at time t
        """
        if t < t0:
            return 0.0

        dt = t - t0

        # Compute double exponential
        # Use max to avoid division by zero or negative time constants
        tau_r = max(0.1, tau_rise)
        tau_d = max(0.1, tau_decay)

        exp_decay = math.exp(-dt / tau_d)
        exp_rise = math.exp(-dt / tau_r)

        # Normalize so peak amplitude is close to the specified amplitude
        # The peak occurs at t_peak = (tau_r * tau_d) / (tau_d - tau_r) * ln(tau_d / tau_r)
        # At the peak, the normalization factor is needed
        # For simplicity, we'll use an empirical normalization
        if tau_d > tau_r:
            norm_factor = 1.0 / (math.exp(-tau_r / tau_d) - math.exp(-1.0))
        else:
            norm_factor = 1.0

        return amplitude * norm_factor * (exp_decay - exp_rise)

    def _generate_channel_waveform(self, channel: int, num_samples: int,
                                   start_phase: float, downsample_factor: int,
                                   highres: int, sample_rate: float) -> list:
        """
        Generate waveform for a single channel based on its configuration.

        Args:
            channel: Channel number (0 or 1)
            num_samples: Number of samples to generate
            start_phase: Starting phase offset in radians
            downsample_factor: Total downsampling factor
            highres: 1 for averaging mode, 0 for decimation
            sample_rate: Sample rate in GS/s (3.2 for single channel, 1.6 for two channel)

        Returns:
            List of ADC sample values
        """
        config = self.channel_config[channel]
        wave_type = config["wave_type"]
        frequency = config["frequency"]
        amplitude = config["amplitude"]

        # Get gain and offset
        gain = pow(10, self.board_state["channel_gain"][channel] / 20.0)
        offset = self.board_state["channel_offset"][channel]

        # Noise parameters
        noise_rms = 0.01 * amplitude  # 1% RMS noise

        # Calculate period in samples
        sample_rate_hz = sample_rate * 1e9  # Convert GS/s to Hz
        wave_period = sample_rate_hz / frequency

        samples = []

        # For pulse waveforms, generate random pulses
        if wave_type == "pulse":
            # Random pulse amplitude for this event
            pulse_amp = random.uniform(config["pulse_amplitude_min"], config["pulse_amplitude_max"])
            tau_rise = config["pulse_tau_rise"]
            tau_decay = config["pulse_tau_decay"]

            # Place pulse at a random position in the waveform, but ensure it's visible
            # For triggered events, center it roughly in the middle
            pulse_t0 = num_samples * 0.4 + random.uniform(-num_samples * 0.1, num_samples * 0.1)

            for i in range(num_samples):
                if downsample_factor == 1:
                    base_sample_pos = i
                    val = self._generate_double_exponential_pulse(
                        base_sample_pos, pulse_t0, pulse_amp, tau_rise, tau_decay
                    )
                    val = int(val * gain)
                    noise = random.gauss(0, noise_rms)
                    val = int(val + noise + offset)
                elif highres == 1:
                    # Averaging mode
                    val_sum = 0
                    for j in range(downsample_factor):
                        base_sample_pos = i * downsample_factor + j
                        base_val = self._generate_double_exponential_pulse(
                            base_sample_pos, pulse_t0, pulse_amp, tau_rise, tau_decay
                        )
                        base_val = int(base_val * gain)
                        noise = random.gauss(0, noise_rms)
                        val_sum += base_val + noise
                    val = int(val_sum / downsample_factor + offset)
                else:
                    # Decimation mode
                    base_sample_pos = i * downsample_factor
                    val = self._generate_double_exponential_pulse(
                        base_sample_pos, pulse_t0, pulse_amp, tau_rise, tau_decay
                    )
                    val = int(val * gain)
                    noise = random.gauss(0, noise_rms)
                    val = int(val + noise + offset)

                val = max(-2048, min(2047, val))
                samples.append(val)

        elif wave_type == "square":
            for i in range(num_samples):
                if downsample_factor == 1:
                    base_sample_pos = i
                    phase = (base_sample_pos * 2 * math.pi / wave_period + start_phase) % (2 * math.pi)
                    val = int(amplitude * (1 if phase < math.pi else -1) * gain)
                    noise = random.gauss(0, noise_rms)
                    val = int(val + noise + offset)
                elif highres == 1:
                    # Averaging mode
                    val_sum = 0
                    for j in range(downsample_factor):
                        base_sample_pos = i * downsample_factor + j
                        phase = (base_sample_pos * 2 * math.pi / wave_period + start_phase) % (2 * math.pi)
                        base_val = int(amplitude * (1 if phase < math.pi else -1) * gain)
                        noise = random.gauss(0, noise_rms)
                        val_sum += base_val + noise
                    val = int(val_sum / downsample_factor + offset)
                else:
                    # Decimation mode
                    base_sample_pos = i * downsample_factor
                    phase = (base_sample_pos * 2 * math.pi / wave_period + start_phase) % (2 * math.pi)
                    val = int(amplitude * (1 if phase < math.pi else -1) * gain)
                    noise = random.gauss(0, noise_rms)
                    val = int(val + noise + offset)

                val = max(-2048, min(2047, val))
                samples.append(val)

        else:  # sine wave (default)
            for i in range(num_samples):
                if downsample_factor == 1:
                    base_sample_pos = i
                    phase = (base_sample_pos * 2 * math.pi / wave_period + start_phase)
                    val = int(amplitude * math.sin(phase) * gain)
                    noise = random.gauss(0, noise_rms)
                    val = int(val + noise + offset)
                elif highres == 1:
                    # Averaging mode
                    val_sum = 0
                    for j in range(downsample_factor):
                        base_sample_pos = i * downsample_factor + j
                        phase = (base_sample_pos * 2 * math.pi / wave_period + start_phase)
                        base_val = int(amplitude * math.sin(phase) * gain)
                        noise = random.gauss(0, noise_rms)
                        val_sum += base_val + noise
                    val = int(val_sum / downsample_factor + offset)
                else:
                    # Decimation mode
                    base_sample_pos = i * downsample_factor
                    phase = (base_sample_pos * 2 * math.pi / wave_period + start_phase)
                    val = int(amplitude * math.sin(phase) * gain)
                    noise = random.gauss(0, noise_rms)
                    val = int(val + noise + offset)

                val = max(-2048, min(2047, val))
                samples.append(val)

        return samples

    def _generate_wave_buffer(self, num_samples: int, start_phase: float = 0.0) -> Dict[str, list]:
        """
        Generate raw waveform data for both channels.

        Args:
            num_samples: Number of ADC samples to generate
            start_phase: Starting phase offset in radians

        Returns:
            Dictionary with 'ch0' and 'ch1' keys containing lists of ADC sample values
        """
        two_channel_mode = self.board_state["two_channel_mode"]

        # Get downsample parameters
        ds = self.board_state["downsample_ds"]
        merging = self.board_state["downsample_merging"]
        highres = self.board_state["downsample_highres"]
        downsample_factor = merging * (2 ** ds)

        ch0_samples = []
        ch1_samples = []

        if two_channel_mode:
            # Generate samples for both channels at 1.6 GS/s (interleaved at 3.2 GS/s base rate)
            ch1_samples = self._generate_channel_waveform(
                channel=1,
                num_samples=num_samples,
                start_phase=start_phase,
                downsample_factor=downsample_factor,
                highres=highres,
                sample_rate=1.6  # GS/s per channel in two-channel mode
            )

            ch0_samples = self._generate_channel_waveform(
                channel=0,
                num_samples=num_samples,
                start_phase=start_phase,
                downsample_factor=downsample_factor,
                highres=highres,
                sample_rate=1.6  # GS/s per channel in two-channel mode
            )
        else:
            # Single-channel mode: only ch0 at 3.2 GS/s
            ch0_samples = self._generate_channel_waveform(
                channel=0,
                num_samples=num_samples,
                start_phase=start_phase,
                downsample_factor=downsample_factor,
                highres=highres,
                sample_rate=3.2  # GS/s in single-channel mode
            )

        return {'ch0': ch0_samples, 'ch1': ch1_samples}

    def _find_trigger(self, wave_buffer: Dict[str, list], start_search_index: int = 0) -> int:
        """
        Find the trigger point in the waveform buffer.

        Args:
            wave_buffer: Dictionary with 'ch0' and 'ch1' waveform data
            start_search_index: Index to start searching from (to ensure pre-trigger margin)

        Returns:
            Sample index where trigger occurs, or None if no trigger found
        """
        # Get trigger parameters
        trigger_level_raw = self.board_state["trigger_level"] - 1
        trigger_level_adc = int((trigger_level_raw - 127) * 2047 / 127)
        trigger_delta = self.board_state["trigger_delta"]
        trigger_delta_adc = int(trigger_delta * 2047 / 127)
        trigger_type = self.board_state["trigger_type"]
        trigger_chan = self.board_state["trigger_chan"]
        is_falling = (trigger_type == 2)

        # Select the trigger channel data
        if trigger_chan == 0:
            trigger_data = wave_buffer['ch0']
        else:
            trigger_data = wave_buffer['ch1']

        # Search for trigger crossing with hysteresis, starting from start_search_index
        # Hysteresis works as follows:
        # - Rising edge: Signal must first go below threshold (arming), then cross above threshold+delta (trigger)
        # - Falling edge: Signal must first go above threshold (arming), then cross below threshold-delta (trigger)

        armed = False

        for i in range(max(1, start_search_index), len(trigger_data)):
            curr_val = trigger_data[i]

            if is_falling:
                # Falling edge with hysteresis:
                # First, signal must go above threshold to arm
                if not armed and curr_val > trigger_level_adc:
                    armed = True
                # Once armed, trigger fires when signal goes below (threshold - delta)
                elif armed and curr_val <= trigger_level_adc - trigger_delta_adc:
                    return i
            else:
                # Rising edge with hysteresis:
                # First, signal must go below threshold to arm
                if not armed and curr_val < trigger_level_adc:
                    armed = True
                # Once armed, trigger fires when signal goes above (threshold + delta)
                elif armed and curr_val >= trigger_level_adc + trigger_delta_adc:
                    return i

        # No trigger found
        return None

    def _find_trigger_with_margin(self, wave_buffer: Dict[str, list], pre_trigger_samples: int) -> int:
        """
        Find trigger in buffer, ensuring enough pre-trigger samples are available.

        Args:
            wave_buffer: Dictionary with 'ch0' and 'ch1' waveform data
            pre_trigger_samples: Number of samples needed before the trigger point

        Returns:
            Sample index where trigger occurs (with margin), or None if no trigger found
        """
        # Start searching after pre_trigger_samples to ensure we have enough headroom
        return self._find_trigger(wave_buffer, start_search_index=pre_trigger_samples)

    def _handle_read_data(self, data: bytes) -> bytes:
        """Handle opcode 0 (read captured data)."""
        # Extract expected data length from bytes [4:8]
        expect_len = struct.unpack("<I", data[4:8])[0] if len(data) >= 8 else 1000

        # Data format: nsubsamples = 50 words per sample
        # Based on data_processor.py line 189:
        #   vals = unpackedsamples[s * nsubsamples + 40: s * nsubsamples + 50]
        # So words 40-49 contain timing info and marker:
        #   vals[0:4]   = clocks (should be 341 or 682)
        #   vals[4:8]   = strobes (should be one-hot: 1, 2, 4, 8, 16, 32, 64, 128)
        #   vals[8]     = control (should be 0)
        #   vals[9]     = marker (should be -16657 / 0xBEEF)
        # Words 0-39 are actual ADC data (20 samples per channel in two-channel mode)

        two_channel_mode = self.board_state["two_channel_mode"]
        nsubsamples = 50
        bytes_per_sample = nsubsamples * 2  # 100 bytes per sample (50 words * 2 bytes/word)
        num_logical_samples = expect_len // bytes_per_sample

        # Calculate the number of ADC samples needed from buffer
        # In single-channel mode: 40 ADC samples per logical block at 3.2 GS/s
        # In two-channel mode: 20 ADC samples per channel per logical block, but at 1.6 GS/s
        #                      So we need 40 samples at 3.2 GS/s, then extract every other one
        # Always use 40 samples per block for buffer generation (full rate)
        samples_per_block = 40

        # Output samples per block (what we extract and send)
        if two_channel_mode:
            output_samples_per_block = 20
        else:
            output_samples_per_block = 40

        total_adc_samples_needed = num_logical_samples * samples_per_block

        # Get trigger position (where trigger should appear in the output)
        # trigger_pos is in logical sample blocks, convert to ADC samples at full rate
        # Add 1 block to account for how the hardware interprets trigger position
        trigger_pos_blocks = self.board_state["trigger_pos"]
        trigger_pos_samples = (trigger_pos_blocks + 1) * samples_per_block

        # Generate a buffer with enough headroom for pre-trigger and post-trigger samples
        # We need: pre-trigger samples + actual data samples + search window
        # Add extra headroom (2x the needed samples) to ensure we can find triggers
        buffer_size = total_adc_samples_needed + trigger_pos_samples + total_adc_samples_needed

        # Generate waveform buffer at full rate (3.2 GS/s) with random starting phase
        start_phase = random.uniform(0, 2 * math.pi)
        wave_buffer = self._generate_wave_buffer(buffer_size, start_phase)

        # Find trigger point in the buffer, but only search after we have enough pre-trigger samples
        # This ensures we can always extract the correct window
        trigger_index = self._find_trigger_with_margin(wave_buffer, trigger_pos_samples)

        # Determine the starting index in the buffer to extract data
        if trigger_index is not None:
            # Trigger found - center data on trigger position
            start_index = trigger_index - trigger_pos_samples
            # Ensure we don't go negative
            if start_index < 0:
                start_index = 0
        else:
            # No trigger found - use random phase
            max_start = buffer_size - total_adc_samples_needed
            if max_start > 0:
                start_index = random.randint(0, max_start)
            else:
                start_index = 0

        # Extract the data window from the buffer
        end_index = start_index + total_adc_samples_needed

        # Ensure we have enough data
        if end_index > len(wave_buffer['ch0']):
            end_index = len(wave_buffer['ch0'])
            start_index = max(0, end_index - total_adc_samples_needed)

        # Now format the data into logical sample blocks with timing/marker data
        adc_data = bytearray()

        for s in range(num_logical_samples):
            # Calculate the buffer index for this block
            buffer_idx = start_index + s * samples_per_block

            if two_channel_mode:
                # Two-channel mode: words 0-19 are channel 1, words 20-39 are channel 0
                # Extract 20 samples for each channel, skipping every other sample (1.6 GS/s from 3.2 GS/s buffer)

                # Channel 1 (words 0-19)
                for i in range(20):
                    # Skip every other sample to get 1.6 GS/s rate
                    val = wave_buffer['ch1'][buffer_idx + i * 2]
                    # Shift to upper 12 bits of 16-bit short
                    adc_data.extend(struct.pack("<h", val << 4))

                # Channel 0 (words 20-39)
                for i in range(20):
                    # Skip every other sample to get 1.6 GS/s rate
                    val = wave_buffer['ch0'][buffer_idx + i * 2]
                    # Shift to upper 12 bits of 16-bit short
                    adc_data.extend(struct.pack("<h", val << 4))

            else:
                # Single-channel mode: Words 0-39 are 40 consecutive ADC samples at 3.2 GS/s
                # Extract 40 samples from the pre-generated buffer
                for i in range(40):
                    val = wave_buffer['ch0'][buffer_idx + i]
                    # Shift to upper 12 bits of 16-bit short
                    adc_data.extend(struct.pack("<h", val << 4))

            # Words 40-49: Timing and marker
            # Clocks (words 40-43): vals[0:4] should be 341 or 682
            for clk_idx in range(4):
                clock_val = 341 if (s + clk_idx) % 2 == 0 else 682
                adc_data.extend(struct.pack("<h", clock_val))

            # Strobes (words 44-47): vals[4:8] should be one-hot encoded
            # Cycle through one-hot patterns: 1, 2, 4, 8, 16, 32, 64, 128
            for strobe_idx in range(4):
                strobe_pattern = [1, 2, 4, 8, 16, 32, 64, 128]
                strobe_val = strobe_pattern[(s + strobe_idx) % 8]
                adc_data.extend(struct.pack("<h", strobe_val))

            # Word 48 (vals[8]): Control byte (should be 0)
            adc_data.extend(struct.pack("<h", 0))

            # Word 49 (vals[9]): 0xBEEF marker (-16657 in signed 16-bit)
            adc_data.extend(struct.pack("<h", -16657))

        # Handle any remaining bytes by generating a partial block
        remainder = expect_len % bytes_per_sample
        if remainder > 0:
            # Calculate how many complete words we need
            words_needed = remainder // 2
            buffer_idx = start_index + num_logical_samples * samples_per_block

            # Extract ADC data words (up to 40)
            adc_words_to_extract = min(words_needed, 40 if not two_channel_mode else 40)
            for i in range(adc_words_to_extract):
                if i < len(wave_buffer['ch0']) - buffer_idx:
                    val = wave_buffer['ch0'][buffer_idx + i]
                else:
                    val = 0  # Padding if we run out of buffer
                # Shift to upper 12 bits of 16-bit short
                adc_data.extend(struct.pack("<h", val << 4))

            # If we need more words beyond the ADC samples, generate timing/marker data
            if words_needed > 40:
                # Clocks (words 40-43)
                for clk_idx in range(min(4, words_needed - 40)):
                    clock_val = 341 if (num_logical_samples + clk_idx) % 2 == 0 else 682
                    adc_data.extend(struct.pack("<h", clock_val))

                # Strobes (words 44-47)
                if words_needed > 44:
                    for strobe_idx in range(min(4, words_needed - 44)):
                        strobe_pattern = [1, 2, 4, 8, 16, 32, 64, 128]
                        strobe_val = strobe_pattern[(num_logical_samples + strobe_idx) % 8]
                        adc_data.extend(struct.pack("<h", strobe_val))

                # Control (word 48)
                if words_needed > 48:
                    adc_data.extend(struct.pack("<h", 0))

                # Marker (word 49)
                if words_needed > 49:
                    adc_data.extend(struct.pack("<h", -16657))

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
        default=1000031,
        help="Firmware version as decimal"
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
