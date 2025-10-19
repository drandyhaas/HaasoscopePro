# scope_state.py

class ScopeState:
    """A class to hold the configuration and state of the oscilloscope application."""

    def __init__(self, num_boards, num_chan_per_board):
        # General and Hardware Configuration
        self.softwareversion = 31.03
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
        self.persist_lines_enabled = [True] * (num_boards * num_chan_per_board)  # Show faint persist lines
        self.persist_avg_enabled = [True] * (num_boards * num_chan_per_board)  # Show persist average

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
        self.doresamp = 0  # Start at 0 since downsample starts at 0 (>=0)
        self.saved_doresamp = 4  # Saved resamp value to restore when downsample < 0
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
