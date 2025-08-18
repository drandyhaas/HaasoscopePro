# state.py
"""
Manages the complete configuration and state of the oscilloscope application.
"""


class ScopeState:
    def __init__(self, num_boards, num_chans_per_board=2):
        self.num_boards = num_boards
        self.num_chans_per_board = num_chans_per_board
        self.total_channels = num_boards * num_chans_per_board

        self.active_board = 0
        self.selected_channel = 0

        self.is_paused = True
        self.is_rolling = False
        self.is_single_shot = False
        self.is_drawing = True
        self.is_persist = False
        self.is_recording = False

        self.expect_samples = 100
        self.expect_samples_extra = 5
        self.downsample = 0
        self.downsample_factor = 1
        self.downsample_merging = 1
        self.samplerate_ghz = 3.2
        self.is_high_res = False

        self.trigger_level = 127
        self.trigger_delta = 1
        self.trigger_pos_percent = 50
        self.trigger_time_thresh = 0
        self.trigger_type = 1  # 1=rising, 2=falling
        self.trigger_channels = [0] * num_boards

        self.gains = [0] * self.total_channels
        self.offsets = [0] * self.total_channels
        self.is_ac_coupled_list = [False] * self.total_channels
        self.is_high_impedance_list = [False] * self.total_channels
        self.is_attenuator_on_list = [False] * self.total_channels
        self.probe_attenuation = [1] * self.total_channels
        self.volts_per_div = [0.16] * self.total_channels

        self.is_two_channel_mode = False
        self.is_oversampling_list = [False] * num_boards
        self.is_interleaved_list = [False] * num_boards
        self.is_ext_triggered = [False] * num_boards
        self.is_ext_sma_triggered = [False] * num_boards
        self.tad_values = [0] * num_boards
        self.toff = 36
        self.triggershift = 2

        self.yscale = 3.3 / 2.03 * 10 * 5 / 8 / (2 ** 12) / 16
        self.min_y, self.max_y = -5, 5
        self.min_x, self.max_x = 0, 100
        self.x_units = "ns"
        self.ns_per_unit = 1
        self.fit_width_fraction = 0.2
        self.is_fft_enabled = False
        self.resample_factor = 0

        self.event_count = 0
        self.old_event_count = 0

        # Hardware state tracking
        self.firmware_version = None
        self.phasecs = [[[0] * 5, [0] * 5, [0] * 5, [0] * 5] for _ in range(num_boards)]
        self.pll_just_reset = [-10] * num_boards
        self.pll_just_reset_dir = [0] * num_boards
        self.phase_nbad = [[0] * 12 for _ in range(num_boards)]
        self.extrig_board_std_correction = [1.0] * num_boards
        self.extrig_board_mean_correction = [0.0] * num_boards

    @property
    def active_channel_index(self):
        return self.active_board * self.num_chans_per_board + self.selected_channel

    def set_gain(self, board, chan, value):
        idx = board * self.num_chans_per_board + chan
        self.gains[idx] = value
        v_at_0db = 0.1605
        new_v_per_div = v_at_0db * self.probe_attenuation[idx] / (10 ** (value / 20.0))
        if self.is_oversampling_list[board]:
            new_v_per_div *= 2.0
        self.volts_per_div[idx] = new_v_per_div

    def get_volts_per_div(self, board, chan):
        return self.volts_per_div[board * self.num_chans_per_board + chan]

    def get_voltage_offset(self, board, chan):
        idx = board * self.num_chans_per_board + chan
        scaling = 1000 * self.volts_per_div[idx] / 160
        if self.is_ac_coupled_list[idx]:
            scaling *= 245 / 160
        v_offset = scaling * 1.5 * self.offsets[idx]
        if self.is_oversampling_list[board]:
            v_offset *= 2.0
        if self.is_ac_coupled_list[idx]:
            v_offset *= (160 / 245)
        return v_offset / 1000  # Return in Volts

    def get_trigger_pos_samples(self):
        return int(self.expect_samples * self.trigger_pos_percent / 100)

    def update_x_axis_ranges(self):
        self.update_downsample_factors()
        base_width = 4 * 10 * self.expect_samples * self.downsample_factor / self.samplerate_ghz

        if base_width > 5000000000:
            self.ns_per_unit, self.x_units = 1000000000, "s"
        elif base_width > 5000000:
            self.ns_per_unit, self.x_units = 1000000, "ms"
        elif base_width > 5000:
            self.ns_per_unit, self.x_units = 1000, "us"
        else:
            self.ns_per_unit, self.x_units = 1, "ns"

        self.max_x = base_width / self.ns_per_unit
        self.min_x = 0

        downsample_zoom = 2 ** (-self.downsample) if self.downsample < 0 else 1
        if downsample_zoom > 1:
            _, trigger_pos_x = self.get_trigger_line_positions()
            trigger_frac = trigger_pos_x / self.max_x if self.max_x > 0 else 0.5
            new_width = self.max_x / downsample_zoom
            self.min_x = trigger_pos_x - (trigger_frac * new_width)
            self.max_x = trigger_pos_x + ((1 - trigger_frac) * new_width)

    def update_downsample_factors(self):
        ds = self.downsample
        merging = 1
        if ds < 0: ds = 0

        if ds == 0:
            ds, merging = 0, 1
        elif ds == 1:
            ds, merging = 0, 2
        elif ds == 2:
            ds, merging = 0, 4
        elif ds == 3:
            ds, merging = 0, 8 if not self.is_two_channel_mode else 10
        elif ds == 4:
            ds, merging = 0, 20
        elif not self.is_two_channel_mode:
            if ds == 5: ds, merging = 0, 40
            if ds > 5: ds, merging = ds - 5, 40
        else:
            if ds > 4: ds, merging = ds - 4, 20

        self.downsample_merging = merging
        self.downsample_factor = merging * (2 ** ds)
        return ds, merging

    def get_trigger_line_positions(self):
        h_pos = (self.trigger_level - 127) * self.yscale * 16 * 16
        v_pos = 4 * 10 * (
                    self.get_trigger_pos_samples() + 1.0) * self.downsample_factor / self.ns_per_unit / self.samplerate_ghz
        return h_pos, v_pos

    def get_x_range(self):
        """Returns the current x-axis range as a tuple."""
        return (self.min_x, self.max_x)

    def get_y_range(self):
        """Returns the current y-axis range as a tuple."""
        return (self.min_y, self.max_y)
