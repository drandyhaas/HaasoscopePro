# hardware.py
"""
Manages all low-level communication with the USB oscilloscope hardware.
This file assumes that 'board.py', 'usbs.py', and the 'ftd2xx' library are present.
"""
import time
import sys
import ftd2xx
from ftd2xx import DeviceError

# --- Imports from actual hardware libraries ---
from board import *
from usbs import *

# --- Imports from refactored modules ---
from utilsfuncs import inttobytes, find_longest_zero_stretch


class HardwareManager:
    def __init__(self, usbs):
        self.usbs = usbs
        self.num_boards = len(usbs)
        self.time_start = time.time()

        self.event_counters = [0] * self.num_boards
        self.sample_triggered = [0] * self.num_boards
        self.trigger_phase = [0] * self.num_boards
        self.downsample_merging_counter = [0] * self.num_boards
        self.do_ext_trig_echo = [False] * self.num_boards
        self.lvds_trig_delay = [0] * self.num_boards
        self.last_lvds_trig_delay = [0] * self.num_boards
        self.no_ext_board_idx = -1

        self.rate_calc_time = time.time()
        self.rate_calc_events = 0
        self.last_rate = 0
        self.last_size = 0

    def setup_board(self, board_idx, state):
        usb = self.usbs[board_idx]
        ver = version(usb, False)
        if state.firmware_version is None:
            state.firmware_version = ver
        elif ver < state.firmware_version:
            print(f"Warning: Board {board_idx} has older firmware ({ver})!")
            state.firmware_version = ver

        self.adf_reset(board_idx, state)
        setupboard(usb, 0, state.is_two_channel_mode, False)
        for c in range(state.num_chans_per_board):
            setchanacdc(usb, c, False, state.is_oversampling_list[board_idx])
            setchanimpedance(usb, c, False, state.is_oversampling_list[board_idx])
            setchanatt(usb, c, False, state.is_oversampling_list[board_idx])
        setsplit(usb, False)
        self.pll_reset(board_idx, state)
        auxoutselector(usb, 0)
        self.send_trigger_info(board_idx, state)

    def send_trigger_info(self, board_idx, state):
        pos = state.get_trigger_pos_samples() + state.triggershift
        if state.is_ext_triggered[board_idx]:
            delay_samples = 8 * self.lvds_trig_delay[board_idx] / 40 / state.downsample_factor
            if state.is_two_channel_mode: delay_samples /= 2
            pos += int(delay_samples)

        cmd = bytes([8, state.trigger_level + 1, state.trigger_delta,
                     pos // 256, pos % 256,
                     state.trigger_time_thresh, state.trigger_channels[board_idx], 100])
        self.usbs[board_idx].send(cmd)
        self.usbs[board_idx].recv(4)

        pre_len = state.get_trigger_pos_samples() + 5
        self.usbs[board_idx].send(bytes([2, 7] + inttobytes(pre_len) + [0, 0]))
        self.usbs[board_idx].recv(4)

    def update_downsample(self, board_idx, state):
        ds, merging = state.update_downsample_factors()
        cmd = bytes([9, ds, state.is_high_res, merging, 100, 100, 100, 100])
        self.usbs[board_idx].send(cmd)
        self.usbs[board_idx].recv(4)

    def dophase(self, board_idx, plloutnum, updown, pllnum, state, quiet=False):
        self.usbs[board_idx].send(bytes([6, pllnum, int(plloutnum + 2), updown, 100, 100, 100, 100]))
        if updown:
            state.phasecs[board_idx][pllnum][plloutnum] += 1
        else:
            state.phasecs[board_idx][pllnum][plloutnum] -= 1
        if not quiet:
            print(
                f"Phase for pllnum {pllnum}, plloutnum {plloutnum} on board {board_idx} now {state.phasecs[board_idx][pllnum][plloutnum]}")

    def pll_reset(self, board_idx, state):
        self.usbs[board_idx].send(bytes([5, 99, 99, 99, 100, 100, 100, 100]))
        self.usbs[board_idx].recv(4)
        state.phasecs[board_idx] = [[0] * 5, [0] * 5, [0] * 5, [0] * 5]
        state.pll_just_reset[board_idx] = 0
        state.pll_just_reset_dir[board_idx] = 1
        state.phase_nbad[board_idx] = [0] * 12
        if self.num_boards > 1 and state.is_ext_triggered[board_idx]:
            self.do_ext_trig_echo[board_idx] = True

    def adf_reset(self, board_idx, state):
        usb = self.usbs[board_idx]
        adf4350(usb, state.samplerate_ghz * 1000 / 2, None, themuxout=True)
        time.sleep(0.1)
        res = boardinbits(usb)
        print(f"ADF PLL for board {board_idx} locked: {bool(getbit(res, 5))}")

    def get_event(self, state):
        try:
            ready_event = [False] * self.num_boards
            no_ext_boards = []
            self.no_ext_board_idx = -1

            for board in range(self.num_boards):
                if not state.is_ext_triggered[board]:
                    no_ext_boards.append(board)
                    continue
                if self._poll_and_predata(board, state):
                    ready_event[board] = True

            for board in no_ext_boards:
                if self._poll_and_predata(board, state):
                    ready_event[board] = True
                    if self.no_ext_board_idx == -1:
                        self.no_ext_board_idx = board

            if not any(ready_event):
                return None

            all_board_data = {}
            total_rx = 0
            for board in range(self.num_boards):
                if ready_event[board]:
                    raw_data, rx_len = self._read_board_data(board, state)
                    all_board_data[board] = {'raw': raw_data, 'params': self._get_params_for_board(board)}
                    total_rx += rx_len

            self._update_rate_stats(total_rx)
            return all_board_data

        except DeviceError as e:
            print(f"FTD2XX Device error: {e}")
            raise e

    def _poll_and_predata(self, board_idx, state):
        tt = state.trigger_type
        if state.is_ext_triggered[board_idx]:
            tt = 30 if self.do_ext_trig_echo[board_idx] else 3
        elif state.is_ext_sma_triggered[board_idx]:
            tt = 5

        post_trig_len = state.expect_samples + state.expect_samples_extra - state.get_trigger_pos_samples() + 1
        self.usbs[board_idx].send(bytes(
            [1, tt, state.is_two_channel_mode + 2 * state.is_oversampling_list[board_idx], 99] + inttobytes(
                post_trig_len)))
        trigger_counter = self.usbs[board_idx].recv(4)

        if trigger_counter[0] != 251:
            return False

        got_zero = False
        for s in range(20):
            the_bit = getbit(trigger_counter[s // 8 + 1], s % 8)
            if the_bit == 0: got_zero = True
            if the_bit == 1 and got_zero:
                self.sample_triggered[board_idx] = s
                got_zero = False

        self.usbs[board_idx].send(bytes([2, 4, 100, 100, 100, 100, 100, 100]))
        res = self.usbs[board_idx].recv(4)
        self.downsample_merging_counter[board_idx] = res[0] if state.downsample_merging > 1 else 0
        self.trigger_phase[board_idx] = res[1]

        return True

    def _read_board_data(self, board_idx, state):
        n_subsamples = 50
        expect_len = (state.expect_samples + state.expect_samples_extra) * 2 * n_subsamples
        self.usbs[board_idx].send(bytes([0, 99, 99, 99] + inttobytes(expect_len)))
        data = self.usbs[board_idx].recv(expect_len)
        rx_len = len(data)
        if expect_len != rx_len:
            print(f'*** expect_len ({expect_len}) and rx_len ({rx_len}) mismatch on board {board_idx}')
        return data, rx_len

    def _get_params_for_board(self, board_idx):
        return {
            'sample_triggered': self.sample_triggered[board_idx],
            'trigger_phase': self.trigger_phase[board_idx],
            'downsample_merging_counter': self.downsample_merging_counter[board_idx],
            'no_ext_board_idx': self.no_ext_board_idx,
            'lvds_trig_delay': self.lvds_trig_delay[board_idx]
        }

    def _update_rate_stats(self, rx_len):
        self.rate_calc_events += 1
        self.last_size = rx_len
        now = time.time()
        elapsed = now - self.rate_calc_time
        if elapsed >= 1.0:
            self.last_rate = self.rate_calc_events / elapsed
            self.rate_calc_events = 0
            self.rate_calc_time = now

    def adjust_clocks(self, board_idx, nbad_counts, state):
        """
        Manages the multi-step PLL clock phase calibration sequence after a reset.
        Returns True when the sequence is complete, False otherwise.
        """
        nbadclkA, nbadclkB, nbadclkC, nbadclkD, nbadstr = nbad_counts
        pll_state = state.pll_just_reset[board_idx]
        pll_dir = state.pll_just_reset_dir[board_idx]

        # Step 1: Sweep phase up, collecting badness data
        if 0 <= pll_state < 12:
            nbad = sum(nbad_counts)
            state.phase_nbad[board_idx][pll_state] += nbad
            self.dophase(board_idx, 0, (pll_dir == 1), 0, state, quiet=True)  # clklvds
            self.dophase(board_idx, 1, (pll_dir == 1), 0, state, quiet=True)  # clklvdsout
            state.pll_just_reset[board_idx] += pll_dir
            return False

        # Step 2: Turn around and continue sweep to find edges
        elif pll_state >= 12:
            if pll_state == 15:
                state.pll_just_reset_dir[board_idx] = -1
            state.pll_just_reset[board_idx] += state.pll_just_reset_dir[board_idx]
            self.dophase(board_idx, 0, (state.pll_just_reset_dir[board_idx] == 1), 0, state, quiet=True)
            self.dophase(board_idx, 1, (state.pll_just_reset_dir[board_idx] == 1), 0, state, quiet=True)
            return False

        # Step 3: Analyze data and set to optimal phase
        elif pll_state == -1:
            print(f"Bad clk/str per phase step for board {board_idx}: {state.phase_nbad[board_idx]}")
            start, length = find_longest_zero_stretch(state.phase_nbad[board_idx], True)
            print(f"Found good phase range at step {start} for {length} steps.")

            if start >= 12: start -= 12
            n_steps = start + length // 2 + 1
            if n_steps >= 12: n_steps -= 12

            for i in range(n_steps):
                is_last_step = (i == n_steps - 1)
                self.dophase(board_idx, 0, 1, 0, state, quiet=not is_last_step)
                self.dophase(board_idx, 1, 1, 0, state, quiet=not is_last_step)

            state.pll_just_reset[board_idx] -= 1
            return False

        # Step 4 & 5: Finalization steps
        elif pll_state < -1:
            state.pll_just_reset[board_idx] -= 1
            if state.pll_just_reset[board_idx] < -3:
                state.pll_just_reset[board_idx] = -10
                print(f"PLL reset for board {board_idx} complete.")
                return True  # Sequence is finished

        return False

    def use_external_triggers(self, state):
        for board in range(1, self.num_boards):
            state.is_ext_triggered[board] = True
            if clockused(self.usbs[board], board, False) == 0:
                switchclock(self.usbs[board], board)
            self.send_trigger_info(board, state)

    def cleanup(self):
        for usb in self.usbs:
            cleanup(usb)

    def set_rolling(self, board_idx, is_rolling, is_ext_trig):
        r = is_rolling and not is_ext_trig
        self.usbs[board_idx].send(bytes([2, 8, r, 0, 100, 100, 100, 100]))
        self.usbs[board_idx].recv(4)

    def set_gain(self, board, chan, val, is_oversampling):
        setgain(self.usbs[board], chan, val, is_oversampling)
        if is_oversampling and board % 2 == 0:
            setgain(self.usbs[board + 1], chan, val, is_oversampling)

    def set_offset(self, board, chan, val, state):
        idx = board * state.num_chans_per_board + chan
        v_per_div = state.volts_per_div[idx]
        probe_att = state.probe_attenuation[idx]
        is_ac = state.is_ac_coupled_list[idx]
        is_oversampling = state.is_oversampling_list[board]
        scaling = 1000 * v_per_div / 160
        if is_ac: scaling *= 245 / 160
        dooffset(self.usbs[board], chan, val, scaling / probe_att, is_oversampling)
        if is_oversampling and board % 2 == 0:
            dooffset(self.usbs[board + 1], chan, val, scaling / probe_att, is_oversampling)

    def set_acdc(self, board, chan, is_ac, is_oversampling):
        setchanacdc(self.usbs[board], chan, is_ac, is_oversampling)
        if is_oversampling and board % 2 == 0:
            setchanacdc(self.usbs[board + 1], chan, is_ac, is_oversampling)

    def set_impedance(self, board, chan, is_high_z, is_oversampling):
        setchanimpedance(self.usbs[board], chan, is_high_z, is_oversampling)

    def set_attenuator(self, board, chan, is_on, is_oversampling):
        setchanatt(self.usbs[board], chan, is_on, is_oversampling)
        if is_oversampling and board % 2 == 0:
            setchanatt(self.usbs[board + 1], chan, is_on, is_oversampling)

    def set_channel_mode(self, board, state):
        for ch in range(state.num_chans_per_board):
            setchanatt(self.usbs[board], ch, state.is_two_channel_mode, state.is_oversampling_list[board])
        setupboard(self.usbs[board], 0, state.is_two_channel_mode, False)

    def set_oversampling(self, board, is_on):
        setsplit(self.usbs[board], is_on)
        setsplit(self.usbs[board + 1], False)
        for b in [board, board + 1]:
            swapinputs(self.usbs[b], is_on)

    def set_tad(self, board, value):
        spicommand(self.usbs[board], "TAD", 0x02, 0xB6, abs(value), False, quiet=True)

    def set_aux_out(self, board, value):
        auxoutselector(self.usbs[board], value)