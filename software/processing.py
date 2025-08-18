# processing.py
"""
Handles processing of raw data from the hardware into plottable waveforms
and performs all scientific analysis.
"""
import numpy as np
import struct


class DataManager:
    def __init__(self, state):
        self.state = state
        self.last_clk = -1
        self.nbad_counts = (0, 0, 0, 0, 0)

    def process_event_data(self, event_data):
        processed_waveforms = {}
        for board_idx, data in event_data.items():
            ch_data, nbad = self._unpack_and_align(board_idx, data['raw'], data['params'])
            self.nbad_counts = nbad
            x_data = self._generate_x_axis(board_idx, len(ch_data[0]))
            ch1_idx = board_idx * self.state.num_chans_per_board
            processed_waveforms[ch1_idx] = {'x': x_data, 'y': ch_data[0]}
            if self.state.is_two_channel_mode:
                ch2_idx = ch1_idx + 1
                processed_waveforms[ch2_idx] = {'x': x_data, 'y': ch_data[1]}
        return processed_waveforms

    def _unpack_and_align(self, board_idx, raw_data, params):
        state = self.state
        if state.is_two_channel_mode:
            y_ch1 = np.zeros(int(2 * 10 * state.expect_samples))
            y_ch2 = np.zeros(int(2 * 10 * state.expect_samples))
        else:
            y_ch1 = np.zeros(int(4 * 10 * state.expect_samples))
            y_ch2 = None

        unpack_format = '<' + 'h' * (len(raw_data) // 2)
        unpacked_samples = np.array(struct.unpack(unpack_format, raw_data), dtype=float)

        unpacked_samples_scaled = unpacked_samples * state.yscale

        if state.is_oversampling_list[board_idx] and board_idx % 2 == 0:
            unpacked_samples_scaled += state.extrig_board_mean_correction[board_idx]
            unpacked_samples_scaled *= state.extrig_board_std_correction[board_idx]

        st = params['sample_triggered']
        tp = params['trigger_phase']

        if state.is_ext_triggered[board_idx]:
            no_ext_board = params['no_ext_board_idx']
            if no_ext_board != -1:
                pass

        st_touse = st
        if (tp % 4) != ((tp >> 2) % 4):
            if st < 10: st_touse = st - 1

        trigger_phase = (tp >> 2) % 4 if st < 10 else tp >> 4

        downsample_offset = 2 * (st_touse + (params[
                                                 'downsample_merging_counter'] - 1) % state.downsample_merging * 10) // state.downsample_merging
        downsample_offset += 20 * state.triggershift
        if not state.is_two_channel_mode:
            downsample_offset *= 2

        if state.is_ext_triggered[board_idx]:
            delay_offset = state.toff / state.downsample_factor + (
                        8 * params['lvds_trig_delay'] / state.downsample_factor) % 40
            if state.is_two_channel_mode:
                delay_offset /= 2
            downsample_offset -= int(delay_offset)

        nbadA, nbadB, nbadC, nbadD, nbadS = 0, 0, 0, 0, 0
        n_subsamples = 50

        # --- START: DEFINITIVE FIX FOR PLL RESET ---
        # Check if a PLL calibration sequence is active for this board
        is_calibrating = state.pll_just_reset[board_idx] > -10

        # If we are starting a new calibration, ensure last_clk is reset
        if is_calibrating and state.pll_just_reset[board_idx] == 0:
            self.last_clk = -1
        # --- END: DEFINITIVE FIX ---

        for s in range(0, state.expect_samples + state.expect_samples_extra):
            check_values = unpacked_samples[s * n_subsamples + 40: s * n_subsamples + 50]

            # ALWAYS check for errors during calibration. Otherwise, use the optimization.
            if is_calibrating or check_values[8] != 0 or (self.last_clk != 341 and self.last_clk != 682):
                for n in range(0, 8):
                    val = check_values[n]
                    if n < 4:
                        if val != 341 and val != 682:
                            if n == 0: nbadA += 1
                            if n == 1: nbadB += 1
                            if n == 2: nbadC += 1
                            if n == 3: nbadD += 1
                        self.last_clk = val
                    else:
                        if val not in {0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512}:
                            nbadS += 1

            if state.is_two_channel_mode:
                orig_samp = int(s * 20 - downsample_offset - trigger_phase // 2)
                samp, nsamp, nstart = self._get_slice_params(orig_samp, 20, y_ch1.size)
                if nsamp > 0:
                    src_slice = slice(s * n_subsamples + nstart, s * n_subsamples + nstart + nsamp)
                    src_slice_ch2 = slice(s * n_subsamples + 20 + nstart, s * n_subsamples + 20 + nstart + nsamp)
                    dest_slice = slice(samp, samp + nsamp)
                    y_ch2[dest_slice] = unpacked_samples_scaled[src_slice]
                    y_ch1[dest_slice] = unpacked_samples_scaled[src_slice_ch2]
            else:
                orig_samp = int(s * 40 - downsample_offset - trigger_phase)
                samp, nsamp, nstart = self._get_slice_params(orig_samp, 40, y_ch1.size)
                if nsamp > 0:
                    src_slice = slice(s * n_subsamples + nstart, s * n_subsamples + nstart + nsamp)
                    dest_slice = slice(samp, samp + nsamp)
                    y_ch1[dest_slice] = unpacked_samples_scaled[src_slice]

        return (y_ch1, y_ch2), (nbadA, nbadB, nbadC, nbadD, nbadS)

    def _get_slice_params(self, samp, block_size, total_size):
        nsamp = block_size
        nstart = 0
        if samp < 0:
            nsamp = block_size + samp
            nstart = -samp
            samp = 0
        if samp + nsamp > total_size:
            nsamp = total_size - samp
        nsamp = max(0, nsamp)
        return int(samp), int(nsamp), int(nstart)

    def _generate_x_axis(self, board_idx, num_samples):
        time_multiplier = 2.0 if self.state.is_two_channel_mode else 1.0
        time_per_sample = (time_multiplier *
                           self.state.downsample_factor /
                           self.state.samplerate_ghz)
        if self.state.is_interleaved_list[board_idx]:
            time_per_sample /= 2.0
        x_data = np.arange(num_samples) * time_per_sample
        return x_data / self.state.ns_per_unit

    def calculate_measurements(self, y_data, v_per_div):
        if y_data is None or len(y_data) == 0: return {}
        y_volts = y_data * v_per_div
        return {"Mean": np.mean(y_volts), "RMS": np.std(y_volts), "Max": np.max(y_volts), "Min": np.min(y_volts),
                "Vpp": np.ptp(y_volts)}
