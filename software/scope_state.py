# scope_state.py

class ScopeState:
    """A class to hold the configuration and state of the oscilloscope application."""

    def __init__(self, num_boards, num_chan_per_board):
        # General and Hardware Configuration
        self.softwareversion = 31.09
        self.num_board = num_boards
        self.num_chan_per_board = num_chan_per_board
        self.samplerate = 3.2  # GHz
        self.expect_samples = 100
        self.expect_samples_extra = 5
        self.depth_before_pllreset = 100
        self.firmwareversion = [-1] * num_boards  # Per-board firmware version
        self.basevoltage = 200

        # Application State
        self.paused = True
        self.isrolling = 1  # Start in Auto (rolling) mode
        self.getone = False
        self.dodrawing = True
        self.dopattern = 0
        self.pll_reset_grace_period = 0
        self.dooverrange = False
        self.isdrawing = False
        self.dorecordtofile = False
        self.outf = None
        self.numrecordeventsperfile = 1000

        # Board/Channel Specific States
        self.activeboard = 0
        self.selectedchannel = 0
        self.dotwochannel = [False] * self.num_board # Now a per-board list
        self.dointerleaved = [False] * self.num_board
        self.dooversample = [False] * self.num_board
        self.doexttrig = [0] * self.num_board
        self.doextsmatrig = [0] * self.num_board
        self.doexttrigecho = [False] * self.num_board
        self.fallingedge = [0] * self.num_board
        self.triggerchan = [0] * self.num_board
        self.triggertype = [1] * self.num_board
        self.acdc = [False] * (self.num_board * self.num_chan_per_board)
        self.mohm = [False] * (self.num_board * self.num_chan_per_board)
        self.att = [False] * (self.num_board * self.num_chan_per_board)
        self.tenx = [1] * (self.num_board * self.num_chan_per_board)
        self.offset = [0] * (self.num_board * self.num_chan_per_board)
        self.gain = [0] * (self.num_board * self.num_chan_per_board)
        self.VperD = [(self.basevoltage / 1000.)] * (self.num_board * self.num_chan_per_board)
        self.auxoutval = [0] * self.num_board
        self.tad = [0] * self.num_board
        self.lpf = [0] * (num_boards * num_chan_per_board)
        self.time_skew = [0] * (num_boards * num_chan_per_board)  # Time offset in nanoseconds per channel
        self.channel_names = [''] * (num_boards * num_chan_per_board)  # Custom names for each channel
        self.channel_enabled = [True] * (num_boards * num_chan_per_board)  # Whether channel is enabled (chanonCheck)

        # Per-channel persistence settings
        self.persist_time = [0] * (num_boards * num_chan_per_board)  # Persistence time in ms for each channel
        self.persist_lines_enabled = [False] * (num_boards * num_chan_per_board)  # Show faint persist lines
        self.persist_avg_enabled = [True] * (num_boards * num_chan_per_board)  # Show persist average
        self.persist_heatmap_enabled = [True] * (num_boards * num_chan_per_board)  # Show heatmap instead of lines

        # Triggering Parameters
        self.triggerlevel = 127
        self.triggerdelta = [2] * self.num_board  # Per-board trigger delta
        self.triggerpos = 50
        self.triggershift = 2
        self.triggertimethresh = [0] * self.num_board  # Per-board time over threshold
        self.toff = 100
        self.trigger_delay = [0] * self.num_board
        self.trigger_holdoff = [0] * self.num_board

        # Data Processing and Display Parameters
        self.downsample = 0
        self.downsamplefactor = 1
        self.downsamplezoom = 1
        self.downsamplemerging = 1
        self.doresamp = [0] * (num_boards * num_chan_per_board)  # Per-channel resamp
        self.saved_doresamp = [4] * (num_boards * num_chan_per_board)  # Per-channel saved resamp value
        self.resamp_overridden = [False] * (num_boards * num_chan_per_board)  # Per-channel flag: has user manually set resamp?
        self.xy_mode = False
        self.skip_next_event = False
        self.fitwidthfraction = 0.2
        self.line_width = 2  # Default line width for plots
        self.yscale = 3.3 / 2.03 * 10 * 5 / 8 / pow(2, 12) / 16
        self.nsunits = 1
        self.units = "ns"
        self.min_y, self.max_y = -5, 5
        self.min_x, self.max_x = 0, 4 * 10 * self.expect_samples / self.samplerate

        # Internal processing variables
        self.sample_triggered = [0] * self.num_board
        self.triggerphase = [0] * self.num_board
        self.downsamplemergingcounter = [0] * self.num_board
        self.distcorr = [0] * self.num_board
        self.totdistcorr = [0] * self.num_board
        self.distcorrtol = 3.0
        self.distcorrsamp = 30
        self.noextboard = -1
        self.lvdstrigdelay = [0] * self.num_board
        self.lastlvdstrigdelay = [0] * self.num_board
        self.plljustreset = [-10] * self.num_board
        self.plljustresetdir = [0] * self.num_board
        self.phasenbad = [[0] * 12] * self.num_board
        self.phasecs = [[([0] * 5) for _ in range(4)] for _ in range(self.num_board)]
        self.extraphasefortad = [0] * self.num_board
        self.triggerautocalibration = [False] * self.num_board
        self.extrigboardstdcorrection = [1] * self.num_board
        self.extrigboardmeancorrection = [0] * self.num_board
        self.trig_stabilizer_enabled = True
        self.extra_trig_stabilizer_enabled = True
        self.pulse_stabilizer_enabled = [False] * self.num_board  # Per-board pulse stabilizer

        # Frequency response correction (FIR filter)
        self.fir_correction_enabled = False  # Whether to apply FIR correction
        self.fir_coefficients = None  # 64-tap FIR filter coefficients for non-oversampling (numpy array)
        self.fir_calibration_samplerate = None  # Sample rate at which calibration was performed
        self.fir_freq_response = None  # Measured H(f) for display (dict: {'freqs': array, 'magnitude': array, 'phase': array})

        # FIR coefficients for oversampling mode (board-specific)
        # When oversampling, boards N and N+1 form a pair and need separate calibrations
        self.fir_coefficients_oversample = [None, None]  # [board_N, board_N+1]
        self.fir_calibration_samplerate_oversample = [None, None]
        self.fir_freq_response_oversample = [None, None]

        # FIR coefficients for interleaved oversampling mode
        # When both oversampling and interleaving are enabled, the interleaved data at 6.4 GHz needs its own calibration
        self.fir_coefficients_interleaved = None  # Interleaved waveform at 2x sample rate
        self.fir_calibration_samplerate_interleaved = None
        self.fir_freq_response_interleaved = None

        # FIR coefficients for two-channel mode
        # When two-channel mode is enabled, sample rate is halved (1.6 GHz instead of 3.2 GHz)
        self.fir_coefficients_twochannel = None  # Two-channel mode at 1.6 GHz per channel
        self.fir_calibration_samplerate_twochannel = None
        self.fir_freq_response_twochannel = None

        # Savitzky-Golay polynomial filtering
        self.polynomial_filtering_enabled = False  # Whether to apply Savitzky-Golay filter
        self.savgol_window_length = 15  # Window length (must be odd, >= 3)
        self.savgol_polyorder = 3  # Polynomial order (must be < window_length)

        # Resampling method
        self.polyphase_upsampling_enabled = True  # Use polyphase (less ringing) vs FFT-based resampling

        # Performance metrics
        self.nevents = 0
        self.oldnevents = 0
        self.tinterval = 100.
        self.oldtime = 0
        self.lastrate = 0
        self.lastsize = 0

        # FFT display state dictionary, mapping channel name to boolean
        self.fft_enabled = {} # e.g., {"CH1": False, "CH2": True, ...}

    @property
    def activexychannel(self):
        return self.activeboard * self.num_chan_per_board + self.selectedchannel

    @activexychannel.setter
    def activexychannel(self, value):
        """Set the active channel by decomposing into board and channel."""
        self.activeboard = value // self.num_chan_per_board
        self.selectedchannel = value % self.num_chan_per_board
