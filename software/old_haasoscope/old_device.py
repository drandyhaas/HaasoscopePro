"""Slim, self-contained serial driver for the *original* Haasoscope hardware.

This is a focused port of the low-level serial sequences from the legacy
``Haasoscope/software/libs/HaasoscopeLibQt.py`` (line numbers in comments refer
to that file). It deliberately depends only on pyserial + numpy and pulls in
none of the legacy GUI code, so the modern HaasoscopePro app stays self-contained.

One ``OldHaasoscopeDevice`` owns the real connection to one physical original
board (which has 4 high-speed channels). It is driven by two
``OldHaasoscopeBoardAdapter`` halves (see old_adapter.py); the shared-event
machinery here makes a single physical acquisition serve both halves.
"""

import threading
import time

import numpy as np

try:
    from serial import Serial, SerialException
    import serial.tools.list_ports
    _HAVE_SERIAL = True
except Exception:  # pragma: no cover - pyserial may be absent in some envs
    _HAVE_SERIAL = False
    SerialException = Exception


NUM_CHAN_PER_BOARD = 4          # original board has 4 fast ADC channels
DEFAULT_RAM_WIDTH = 9           # 2**9 = 512 samples/channel (HaasoscopeLibQt ram_width)
BRATE = 1500000                # serial baud (HaasoscopeLibQt.py:73)
CH340_VIDPID = "1A86:7523"     # CH340 USB-UART, the original board's control link
CLKRATE_MHZ = 125.0            # native ADC sample rate

# Mapping of the Pro's 16-bit offset DAC value to the original 12-bit DAC.
# The Pro centers its offset DAC at 32768 (offset slider == 0). These constants
# are a first cut and should be tuned on the bench (the two DACs differ in range
# and polarity).
OFFSET_PRO_CENTER = 32768
OFFSET_GAIN = -1.0 / 16.0


def find_old_haasoscope_ports():
    """Return a list of serial port names that look like an original Haasoscope.

    Detection mirrors HaasoscopeLibQt.setup_connections() (line 1789): match the
    CH340 USB-to-UART VID:PID. Returns [] if pyserial is unavailable.
    """
    if not _HAVE_SERIAL:
        return []
    ports = []
    for port_no, description, address in serial.tools.list_ports.comports():
        addr = (address or "")
        if CH340_VIDPID in addr or CH340_VIDPID.lower() in addr.lower():
            ports.append(port_no)
    return ports


class OldHaasoscopeDevice:
    """Drives one physical original Haasoscope board over serial.

    v1 uses the plain serial readout path (no FT232H fast-USB). That is slower
    but robust and matches the ``getdata`` serial branch in the legacy code
    (HaasoscopeLibQt.py:1439). Fast-USB can be added later as an optimization.
    """

    def __init__(self, serport=None, num_boards=1, ram_width=DEFAULT_RAM_WIDTH,
                 serial_delay=100, debug=False, calib_dir=None, use_fastusb=False):
        self.serport = serport
        self.calib_dir = calib_dir
        self.num_boards = num_boards
        # Fast-USB (FT232H sync-245 FIFO) readout. Commands always stay on the
        # CH340 serial link; only the bulk ADC data moves to the FT232H.
        self.use_fastusb = use_fastusb
        self._ftd = []                  # opened ftd2xx handles
        self._fastusb_active = False
        self.usbsermap = None           # board index -> index into self._ftd
        self.fastusbpadding = 4         # bytes per channel (HaasoscopeLibQt:100)
        self.fastusbendpadding = 2      # of which this many are at the end (line 101)
        self.ram_width = ram_width
        self.num_samples = int(2 ** ram_width)
        self.num_bytes = self.num_samples * NUM_CHAN_PER_BOARD  # per board
        self.serial_delay = serial_delay
        self.debug = debug
        self.brate = BRATE
        self.clkrate = CLKRATE_MHZ
        # Match the legacy timeout heuristic (HaasoscopeLibQt.py:74).
        self.sertimeout = 0.25 + self.num_bytes * 8 * 11.0 / self.brate
        self.ser = None
        self.good = False
        self.minfirmwareversion = 255
        self.uniqueIDs = []

        # Full-scale Vpp for x1 gain (HaasoscopeLibQt.py:1701). Adjusted up for
        # v9.0 boards (firmware >= 15) after firmware is read in init().
        self.yscale = 7.5

        # Runtime state mirrored from Pro-side requests.
        self.downsample = 2

        # Per-channel front-end state (global channel index = board*4 + chan).
        nch = num_boards * NUM_CHAN_PER_BOARD
        self.gain = [1] * nch          # 1 = x1 (low), 0 = x10 (high)  [HaasoscopeLibQt 142]
        self.supergain = [1] * nch     # 1 = normal, 0 = x100 (physical switch on v9.0)
        self.acdc = [1] * nch          # 1 = DC, 0 = AC  [HaasoscopeLibQt 144]
        self.user_offset = [0.0] * nch  # additive DAC offset from the Pro offset slider
        # Port-B (0x20 reg 0x13) shadow register for AC/DC coupling, per board.
        # bit c (0..2) = 1 -> DC on channel c; high nibble 0 keeps ADCs powered.
        self._b20 = [0x07] * num_boards  # default all DC

        # DAC baseline tables (per global channel). Defaults from HaasoscopeLibQt
        # lines 133-140; overwritten per-board by readcalib() when a calib file
        # exists. These center a 0V input at the middle of the ADC range.
        def _tbl(v):
            return [v] * nch
        self.daclevels = {
            'low':        _tbl(2050),  # x1  DC
            'high':       _tbl(2800),  # x10 DC
            'lowsuper':   _tbl(120),   # x100 DC
            'highsuper':  _tbl(50),    # x100 DC (high)
            'lowac':      _tbl(2250),  # x1  AC
            'highac':     _tbl(4600),  # x10 AC
            'lowsuperac': _tbl(2300),  # x100 AC
            'highsuperac': _tbl(4600),  # x100 AC (high)
        }
        # JSON calib keys -> table names (HaasoscopeLibQt readcalib, lines 874-882).
        self._calib_key_map = {
            'lowdaclevels': 'low', 'highdaclevels': 'high',
            'lowdaclevelssuper': 'lowsuper', 'highdaclevelssuper': 'highsuper',
            'lowdaclevelsac': 'lowac', 'highdaclevelsac': 'highac',
            'lowdaclevelssuperac': 'lowsuperac', 'highdaclevelssuperac': 'highsuperac',
        }

        # Robustness for the (flow-control-less) serial readout: re-acquire a few
        # times on an incomplete read instead of throttling the sender. The board
        # free-runs (rolling trigger), so a discarded event is cheap.
        self.max_read_retries = 3
        self._read_timeout = 0.05  # per-read poll interval; deadline is computed

        # Shared-event machinery so the two adapter halves share one physical
        # acquisition. Per physical board: latest event + which halves consumed it.
        self._lock = threading.RLock()
        self._event = [None] * num_boards
        self._consumed = [set() for _ in range(num_boards)]

    # ------------------------------------------------------------------ #
    # Low-level serial helpers
    # ------------------------------------------------------------------ #
    def _w(self, *vals):
        """Write raw command bytes."""
        self.ser.write(bytearray(vals))

    @staticmethod
    def _hi_lo(n):
        """Two-byte big-endian split, like bytearray.fromhex('{:04x}'.format(n))."""
        n = int(n) & 0xFFFF
        return (n >> 8) & 0xFF, n & 0xFF

    def _select_board(self, board):
        """Make a board active for serial passthrough (HaasoscopeLibQt.py:248)."""
        if self.minfirmwareversion >= 17:
            self._w(53, board)
        else:
            self._w(30 + board)

    def _firmchan(self, chan):
        """Map a global channel index to the firmware's channel numbering
        (HaasoscopeLibQt.writefirmchan, line 346)."""
        theboard = self.num_boards - 1 - (chan // NUM_CHAN_PER_BOARD)
        chanonboard = chan % NUM_CHAN_PER_BOARD
        return theboard * NUM_CHAN_PER_BOARD + chanonboard

    # ------------------------------------------------------------------ #
    # Connection + init
    # ------------------------------------------------------------------ #
    def open(self):
        """Open the serial connection. Returns True on success."""
        if not _HAVE_SERIAL:
            print("pyserial not available - cannot open original Haasoscope")
            return False
        if self.serport is None:
            ports = find_old_haasoscope_ports()
            if not ports:
                print("No original Haasoscope (CH340) serial port found")
                return False
            self.serport = ports[0]
        try:
            # stopbits=2 matches HaasoscopeLibQt.py:1796
            self.ser = Serial(self.serport, self.brate,
                              timeout=self.sertimeout, stopbits=2)
        except SerialException as e:
            print(f"Could not open {self.serport}: {e}")
            return False
        print(f"Connected to original Haasoscope on {self.serport} "
              f"(timeout {self.sertimeout:.3f}s)")
        # Proper fix for high-baud byte loss: ask the driver to deliver data
        # promptly so the host keeps up with the CH340 RX FIFO (no throttling).
        self._try_low_latency()
        # Small per-read poll interval; the accumulating reader uses an overall
        # deadline, so this just bounds how often it re-checks progress.
        try:
            self.ser.timeout = self._read_timeout
        except Exception:
            pass
        self.good = True
        return True

    def _try_low_latency(self):
        """Enable serial low-latency mode where supported (Linux/pyserial>=3.5).

        On Linux this clears the FTDI/CH340 16 ms latency timer so the host
        drains the RX FIFO frequently - the real cause of byte loss at 1.5 Mbaud.
        No-op on platforms/versions that don't support it.
        """
        try:
            self.ser.set_low_latency_mode(True)
            print("Enabled serial low-latency mode")
        except (NotImplementedError, ValueError, OSError, AttributeError) as e:
            if self.debug:
                print(f"Serial low-latency mode unavailable: {e}")

    def get_firmware_version(self, board):
        """Read a board's firmware version byte (HaasoscopeLibQt.py:245).

        Returns 0 if not found (very old firmware). Does not sys.exit on failure.
        """
        self._select_board(board)
        self._w(147)
        old_to = self.ser.timeout
        self.ser.timeout = 0.1
        rslt = self.ser.read(1)
        self.ser.timeout = old_to
        return rslt[0] if len(rslt) > 0 else 0

    def init(self):
        """Configure boards to a sane default state ( port of HaasoscopeLibQt.init,
        line 1687). Must be called after open(). Returns True on success."""
        # Assign board IDs and mark the last board (lines 1688-1693).
        if self.num_boards > 10:
            self._w(50, 0)
            self._w(52, self.num_boards - 1)
        else:
            self._w(0)
            self._w(20 + (self.num_boards - 1))

        # Determine the minimum firmware version across boards.
        self.minfirmwareversion = 255
        for b in range(self.num_boards):
            fw = self.get_firmware_version(b)
            self.minfirmwareversion = min(self.minfirmwareversion, fw)
        print(f"Original Haasoscope min firmware version: {self.minfirmwareversion}")

        # Full-scale voltage (lines 1701-1703).
        self.yscale = 7.5
        if self.minfirmwareversion >= 15:
            self.yscale *= 1.1  # v9.0 boards with 10M/1.1M/11k input resistors

        # Rolling (self) trigger on, so the board free-runs (line 1706).
        self._w(101)

        # Number of samples to send (cmd 122, line 185).
        self._w(122, *self._hi_lo(self.num_samples))
        # Bytes-skip = 0, i.e. send every byte (cmd 123, line 211).
        self._w(123, 0)
        # Downsample (cmd 124, line 686).
        self.set_downsample(self.downsample)
        # High-res averaging during downsample (cmd 143, line 530).
        self._w(143)
        # Trigger time-over-threshold = 1 sample (cmd 129, line 311), with the
        # "use downsample for tot" high bit set as the legacy code does.
        self._set_trigger_time(1)
        # Serial inter-chunk delay (cmd 135, line 201).
        self._w(135, *self._hi_lo(self.serial_delay))

        # ADC SPI front-end setup (cmd 131, lines 1716-1721).
        self._spi_setup("08 00")   # common-mode bias 0.9V, not connected
        self._spi_setup("06 10")   # offset-binary output, no clock divide
        self._spi_setup("04 1b")   # 150 Ohm termination chA
        self._spi_setup("05 1b")   # 150 Ohm termination chB
        self._spi_setup("01 00")   # non-multiplexed output (less noise)

        # I2C IO-expander setup: set ports to outputs and load starting values
        # (cmd 136, setupi2c line 447). a20=0xf0 (gain/oversample bits), and the
        # per-board b20 coupling shadow (default all DC).
        self._i2c("20 00 00")
        self._i2c("20 01 00")
        self._i2c("21 00 00")
        self._i2c("20 12 f0")
        for b in range(self.num_boards):
            self._i2c("20 13 " + ('%02x' % (self._b20[b] & 0xFF)), b)

        # Optionally switch bulk data readout to the FT232H (sync-245 FIFO).
        if self.use_fastusb:
            self._setup_fastusb()

        # Read per-board unique IDs and load DAC calibration, then push the
        # baseline DAC for every channel so 0V reads at the ADC center.
        self.getIDs()
        self.readcalib(self.calib_dir)
        for gchan in range(self.num_boards * NUM_CHAN_PER_BOARD):
            self._apply_dac(gchan)

        return True

    # ------------------------------------------------------------------ #
    # Unique IDs + calibration files
    # ------------------------------------------------------------------ #
    def getIDs(self):
        """Read each board's 8-byte unique ID (HaasoscopeLibQt.getIDs, line 572)."""
        self.uniqueIDs = []
        for b in range(self.num_boards):
            self._select_board(b)
            self._w(142)
            rslt = self.ser.read(8)
            if len(rslt) == 8:
                self.uniqueIDs.append(''.join('%02x' % x for x in rslt))
            else:
                self.uniqueIDs.append(None)
                print(f"Could not read unique ID for board {b}")

    def readcalib(self, calib_dir=None):
        """Load per-board DAC calibration tables from calib_<uniqueID>.json.txt
        (HaasoscopeLibQt.readcalib, line 858). Falls back to default DAC levels
        when no file is found."""
        import json
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        search_dirs = [d for d in (
            calib_dir,
            os.path.join(here, "calib"),
            # Sibling original-Haasoscope repo (…/Haasoscope/software/calib).
            os.path.normpath(os.path.join(here, "..", "..", "..",
                                          "Haasoscope", "software", "calib")),
        ) if d]

        for b, uid in enumerate(self.uniqueIDs):
            if not uid:
                continue
            loaded = False
            for d in search_dirs:
                fname = os.path.join(d, f"calib_{uid}.json.txt")
                if not os.path.exists(fname):
                    continue
                try:
                    with open(fname) as fh:
                        c = json.load(fh)
                except Exception as e:
                    print(f"calib read error {fname}: {e}")
                    continue
                sc = b * NUM_CHAN_PER_BOARD
                for key, tbl in self._calib_key_map.items():
                    if key in c and len(c[key]) >= NUM_CHAN_PER_BOARD:
                        self.daclevels[tbl][sc:sc + NUM_CHAN_PER_BOARD] = \
                            c[key][:NUM_CHAN_PER_BOARD]
                print(f"Loaded DAC calibration for board {b} ({uid}) from {fname}")
                loaded = True
                break
            if not loaded:
                print(f"No calib file for board {b} ({uid}); using default DAC levels")

    # ------------------------------------------------------------------ #
    # SPI / I2C helpers (ported, serial-readout only)
    # ------------------------------------------------------------------ #
    def _spi_setup(self, hexpair):
        """tellSPIsetup equivalent (HaasoscopeLibQt.py:373): cmd 131 + 2 bytes."""
        b = bytearray.fromhex(hexpair)
        time.sleep(0.01)
        self._w(131, b[0], b[1])
        time.sleep(0.01)

    def _i2c(self, whattosend, board=200):
        """sendi2c equivalent (HaasoscopeLibQt.py:427): cmd 136, count, payload,
        pad to 5 bytes, board id (200 = all boards)."""
        time.sleep(0.02)
        myb = bytearray.fromhex(whattosend)
        self._w(136)
        self._w(len(myb) - 1)            # data count (excluding address)
        for byte in myb:
            self._w(byte)
        for _ in range(4 - len(myb)):
            self._w(255)                 # pad to a total of 5 bytes
        self._w(int(board))
        time.sleep(0.02)

    def _set_trigger_time(self, ttt):
        """settriggertime (HaasoscopeLibQt.py:311): cmd 129 + 2 bytes, with the
        max_ram_width bit set so the threshold respects downsampling."""
        max_ram_width = 13
        ttt = int(ttt) + (1 << max_ram_width)
        self._w(129, *self._hi_lo(ttt))

    # ------------------------------------------------------------------ #
    # Runtime configuration (called from the adapter on Pro opcodes)
    # ------------------------------------------------------------------ #
    def set_downsample(self, ds):
        """Set downsample power-of-two (cmd 124, HaasoscopeLibQt.py:686)."""
        ds = max(0, int(ds))
        with self._lock:
            self._w(124, ds)
            self.downsample = ds

    def set_trigger_level(self, level):
        """Set trigger threshold 0-255 (cmd 127, HaasoscopeLibQt.py:291). The
        value is inverted on the wire because of the negative-feedback op amp."""
        level = max(0, min(255, int(level)))
        with self._lock:
            self._w(127, 255 - level)

    def set_trigger_rising(self, rising):
        """Set trigger edge (cmd 128, HaasoscopeLibQt.py:305): 1 = rising."""
        with self._lock:
            self._w(128, 1 if rising else 0)

    # ------------------------------------------------------------------ #
    # Front-end: gain / coupling / offset / termination + DAC calibration
    # ------------------------------------------------------------------ #
    def _setdac(self, chanonboard, val, board):
        """Set a channel's DAC (HaasoscopeLibQt.setdac, line 463). DAC at i2c
        0x60; channel registers 0x50/0x52/0x54/0x56; ref/gain nibble 8 (0-2V) or
        9 (0-4V, value halved); 12-bit value."""
        creg = {0: "50", 1: "52", 2: "54", 3: "56"}.get(int(chanonboard))
        if creg is None:
            return
        val = int(max(0, min(2 * 4096 - 1, val)))
        d = "8"
        if val > 4095:
            d = "9"
            val = int(val / 2)
        self._i2c("60 " + creg + d + ('%03x' % int(val)), int(board))

    def _baseline(self, gchan):
        """Baseline DAC level for the current gain/supergain/coupling of a
        channel (HaasoscopeLibQt.setdacvalue, line 794)."""
        g, sg, ac = self.gain[gchan], self.supergain[gchan], self.acdc[gchan]
        if g == 1:                      # x1 (low gain)
            key = 'low' if sg == 1 else 'lowsuper'
        else:                           # x10 (high gain)
            key = 'high' if sg == 1 else 'highsuper'
        if ac == 0:                     # AC coupling -> AC variant table
            key += 'ac'
        return self.daclevels[key][gchan]

    def _apply_dac(self, gchan):
        """Push the DAC for one channel = calibrated baseline + user offset."""
        board = self.num_boards - 1 - (gchan // NUM_CHAN_PER_BOARD)
        chanonboard = gchan % NUM_CHAN_PER_BOARD
        self._setdac(chanonboard, self._baseline(gchan) + self.user_offset[gchan], board)

    def gain_factor(self, gchan):
        """Multiplicative analog-gain factor for a channel (used to scale samples
        back to true input volts since yscale is fixed at x1)."""
        f = 1.0
        if self.gain[gchan] == 0:
            f *= 10.0
        if self.supergain[gchan] == 0:
            f *= 100.0
        return f

    def set_channel_gain(self, gchan, level):
        """Select x1/x10/x100 gain for a channel (level in {1, 10, 100}).

        x10 is software-toggled with command 134 (HaasoscopeLibQt.tellswitchgain,
        line 618). x100 (super gain) is a physical DPDT switch on v9.0 boards, so
        we only track its state for DAC-table selection - it cannot be set here.
        """
        if gchan >= len(self.gain):
            return
        want_x10 = 0 if level >= 10 else 1     # self.gain: 0 = x10 on
        want_super = 0 if level >= 100 else 1  # self.supergain: 0 = x100 on
        with self._lock:
            if self.gain[gchan] != want_x10:
                self._w(134)
                self._w(self._firmchan(gchan))  # command 134 toggles x10
                self.gain[gchan] = want_x10
            self.supergain[gchan] = want_super  # state only (physical switch)
            self._apply_dac(gchan)              # baseline depends on gain

    def set_channel_coupling(self, gchan, is_dc):
        """Set AC/DC coupling via IO-expander 0x20 reg 0x13
        (HaasoscopeLibQt.setacdc, line 811). Only channels 0-2 have a coupling
        bit on the original hardware."""
        if gchan >= len(self.acdc):
            return
        new_ac = 1 if is_dc else 0  # self.acdc: 1 = DC, 0 = AC
        with self._lock:
            if self.acdc[gchan] != new_ac:
                self.acdc[gchan] = new_ac
                board = self.num_boards - 1 - (gchan // NUM_CHAN_PER_BOARD)
                chanonboard = gchan % NUM_CHAN_PER_BOARD
                if chanonboard < 3:
                    if is_dc:
                        self._b20[board] |= (1 << chanonboard)
                    else:
                        self._b20[board] &= ~(1 << chanonboard)
                    self._i2c("20 13 " + ('%02x' % (self._b20[board] & 0xFF)), int(board))
            self._apply_dac(gchan)  # baseline differs for AC vs DC

    def set_channel_offset(self, gchan, pro_dacval):
        """Apply the Pro offset (a 16-bit DAC value centered at 32768) as an
        additive shift on the original 12-bit DAC.

        NOTE: OFFSET_GAIN / sign are a first cut and should be tuned on hardware
        (the two DACs differ in range and polarity).
        """
        if gchan >= len(self.user_offset):
            return
        with self._lock:
            self.user_offset[gchan] = OFFSET_GAIN * (pro_dacval - OFFSET_PRO_CENTER)
            self._apply_dac(gchan)

    def set_channel_termination(self, gchan, onemeg):
        """Pro sends 50 Ohm vs 1 MOhm. On the original v9.0 hardware the 50/1M
        choice is a physical switch (read, not set, by software), so this is a
        no-op aside from tracking. ADC-side termination (50/150/300) could be set
        via command 131 if desired later."""
        # Intentionally inert for v1; documented in Phase 4.
        return

    # ------------------------------------------------------------------ #
    # Fast-USB (FT232H sync-245 FIFO) data readout
    # ------------------------------------------------------------------ #
    def _setup_fastusb(self):
        """Open FT232H device(s), switch the board(s) to USB2 readout, and map
        boards to FT232H connections. Falls back to serial on any failure."""
        if not self._open_fastusb():
            print("No FT232H fast-USB device found; using serial readout")
            return
        self._enable_fastusb_on_board()
        if self._make_usbsermap():
            self._fastusb_active = True
            print(f"Fast-USB (FT232H) readout enabled for {self.num_boards} board(s)")
        else:
            print("Fast-USB board mapping failed; falling back to serial readout")
            self._disable_fastusb()

    def _open_fastusb(self):
        """Open and configure FT232H devices for sync-245 FIFO mode
        (HaasoscopeLibQt.setup_connections, line 1807)."""
        try:
            import ftd2xx as ftd
        except Exception as e:
            print(f"ftd2xx not available for fast-USB: {e}")
            return False
        self._ftd = []
        try:
            ndev = ftd.createDeviceInfoList()
        except Exception:
            ndev = 0
        for i in range(ndev):
            try:
                desc = str(ftd.getDeviceInfoDetail(i).get('description', ''))
            except Exception:
                continue
            # The original FT232H hat reports "Haasoscope" (the Pro reports
            # "Haasoscope Pro"/USB3); avoid grabbing a Pro board.
            if 'Haasoscope' in desc and 'Pro' not in desc:
                try:
                    dev = ftd.open(i)
                    dev.setTimeouts(1000, 1000)
                    dev.setBitMode(0xff, 0x40)   # sync 245 FIFO mode
                    dev.setUSBParameters(0x10000, 0x10000)
                    dev.setLatencyTimer(1)
                    dev.purge(ftd.defines.PURGE_RX | ftd.defines.PURGE_TX)
                    self._ftd.append(dev)
                    print(f"Opened FT232H fast-USB device: {desc}")
                except Exception as e:
                    print(f"Could not open FT232H device {i}: {e}")
        return len(self._ftd) >= self.num_boards

    def _enable_fastusb_on_board(self):
        """Tell the board(s) to write data over the FT232H FIFO.

        cmd 58 toggles fast-USB writing (toggle_fastusb, line 235); cmd 137
        switches readout to USB2 (toggledousb, line 516); cmd 125,1 sets
        ticks-to-wait=1 (telltickstowait for fw>=5, line 268).
        """
        self._w(58)
        self._w(137)
        self._w(125, 1)

    def _disable_fastusb(self):
        """Revert to serial readout and release FT232H handles."""
        try:
            self._w(137)   # toggle USB2 readout back off
            self._w(58)    # toggle fast-USB writing back off
        except Exception:
            pass
        for dev in self._ftd:
            try:
                dev.close()
            except Exception:
                pass
        self._ftd = []
        self._fastusb_active = False

    def _make_usbsermap(self):
        """Map each board to the FT232H carrying its data
        (HaasoscopeLibQt.makeusbsermap, line 1335)."""
        if len(self._ftd) < self.num_boards:
            return False
        pad = self.fastusbpadding
        bwant = self.num_bytes + pad * NUM_CHAN_PER_BOARD
        self.usbsermap = [-1] * self.num_boards
        for dev in self._ftd:
            try:
                dev.setTimeouts(50, 1000)        # short timeout while probing
            except Exception:
                pass
        found, ok = set(), True
        self._w(100)                             # prime all boards
        for bn in range(self.num_boards):
            if self.minfirmwareversion >= 17:
                self._w(51, bn)
            else:
                self._w(10 + bn)
            time.sleep(0.25)                     # wait for a rolling-trigger event
            foundit = False
            for ui, dev in enumerate(self._ftd):
                if ui in found:
                    continue
                try:
                    rslt = dev.read(bwant)
                except Exception:
                    rslt = b""
                if len(rslt) == bwant:
                    self.usbsermap[bn] = ui
                    found.add(ui)
                    foundit = True
                    break
            if not foundit:
                print(f"Could not find FT232H connection for board {bn}")
                ok = False
                break
        for dev in self._ftd:
            try:
                dev.setTimeouts(1000, 1000)      # restore normal timeout
            except Exception:
                pass
        print(f"fast-USB usbsermap: {self.usbsermap}")
        return ok

    # ------------------------------------------------------------------ #
    # Acquisition (shared between the two adapter halves)
    # ------------------------------------------------------------------ #
    def _parse_channels(self, buf, padding, endpadding):
        """Split a raw byte buffer into 4 centered int16 channel arrays.

        Channel c occupies num_samples bytes at offset
        ``c*ns + (c+1)*padding - endpadding`` (HaasoscopeLibQt.py:1446). For the
        plain serial path padding/endpadding are 0.
        """
        ns = self.num_samples
        chans = np.zeros((NUM_CHAN_PER_BOARD, ns), dtype=np.int16)
        for c in range(NUM_CHAN_PER_BOARD):
            off = c * ns + (c + 1) * padding - endpadding
            seg = buf[off:off + ns]
            if len(seg) == ns:
                chans[c] = 127 - seg.astype(np.int16)  # invert (op amp) + center
        return chans

    def _read_exact(self, n):
        """Accumulate exactly n bytes, tolerating bursty delivery.

        Returns fewer than n only if an overall deadline elapses (a genuine
        overrun / incomplete event). The deadline scales with the expected
        transfer time at the baud rate plus the per-32-byte FPGA delay, with a
        generous floor and margin.
        """
        transfer_s = n * 11.0 / self.brate
        delay_s = (n / 32.0) * (2e-6 * self.serial_delay)
        deadline = time.time() + 0.25 + 2.0 * (transfer_s + delay_s)
        buf = bytearray()
        while len(buf) < n:
            chunk = self.ser.read(n - len(buf))   # up to self._read_timeout
            if chunk:
                buf.extend(chunk)
            elif time.time() > deadline:
                break
        return bytes(buf)

    def _drain_serial(self):
        """Discard any buffered input AND drain until the line is idle, so a
        late-arriving tail of an aborted event cannot desync the next read.
        reset_input_buffer() alone is a one-shot flush; the read loop catches
        bytes that arrive just after it."""
        try:
            self.ser.reset_input_buffer()
            while self.ser.read(4096):   # exits ~one poll (self._read_timeout) after quiet
                pass
        except Exception:
            pass

    def _read_serial(self, board):
        raw = self._read_exact(self.num_bytes)
        if len(raw) != self.num_bytes:
            if self.debug:
                print(f"old acquire (serial): wanted {self.num_bytes} bytes, "
                      f"got {len(raw)} from board {board}")
            self._drain_serial()        # re-sync before re-acquiring
            return None                 # signal _do_acquire to re-acquire
        return self._parse_channels(np.frombuffer(raw, dtype=np.uint8), 0, 0)

    def _read_fastusb(self, board):
        try:
            import ftd2xx as ftd
        except Exception:
            return np.zeros((NUM_CHAN_PER_BOARD, self.num_samples), dtype=np.int16)
        pad = self.fastusbpadding
        nb = self.num_bytes + pad * NUM_CHAN_PER_BOARD
        dev = self._ftd[self.usbsermap[board]]
        try:
            raw = dev.read(nb)
            if dev.getQueueStatus() > 0:           # drain any leftover bytes
                self._drain_ftd(dev)
        except Exception as e:
            print(f"fast-USB read error on board {board}: {e}")
            self._drain_ftd(dev)
            return None                            # signal retry
        if len(raw) != nb:
            if self.debug:
                print(f"old acquire (fastusb): wanted {nb} bytes, got {len(raw)}")
            self._drain_ftd(dev)                    # re-sync before re-acquiring
            return None                            # signal retry
        return self._parse_channels(np.frombuffer(raw, dtype=np.uint8),
                                    pad, self.fastusbendpadding)

    def _drain_ftd(self, dev):
        """Purge the FT232H RX buffer and drain any late tail until idle, so an
        aborted event cannot desync the next read."""
        try:
            import ftd2xx as ftd
            dev.purge(ftd.defines.PURGE_RX)
            for _ in range(64):                     # bounded drain
                nq = dev.getQueueStatus()
                if nq <= 0:
                    break
                dev.read(nq)
        except Exception:
            pass

    def _do_acquire(self, board):
        """Arm and read one event for a physical board.

        Returns a (4, num_samples) int16 array of *centered* sample values
        (127 - raw_byte), i.e. positive = positive volts after the op-amp
        inversion. On a short/timed-out read returns zeros. The arm/request
        commands always go over serial; only the bulk data may come from the
        FT232H when fast-USB is active.
        """
        # Re-acquire on an incomplete read rather than throttling the sender.
        for _ in range(self.max_read_retries):
            # Prime the trigger (cmd 100), then select+request data for this board
            # (cmd 51+board for fw>=17, else 10+board) - HaasoscopeLibQt:1594,1400.
            self._w(100)
            if self.minfirmwareversion >= 17:
                self._w(51, board)
            else:
                self._w(10 + board)

            data = (self._read_fastusb(board) if self._fastusb_active
                    else self._read_serial(board))
            if data is not None:
                return data

        # Persistent incomplete reads: return zeros so the pipeline stays alive.
        if self.debug:
            print(f"old acquire: board {board} incomplete after "
                  f"{self.max_read_retries} tries")
        return np.zeros((NUM_CHAN_PER_BOARD, self.num_samples), dtype=np.int16)

    def get_half_data(self, board, half):
        """Return the two centered channel arrays for one adapter half.

        half 0 -> channels (0, 1); half 1 -> channels (2, 3). A single physical
        acquisition is shared: a fresh event is read only when the current one
        has not yet been produced, or once both halves have consumed it (or the
        same half asks twice).
        """
        with self._lock:
            need_fresh = (self._event[board] is None
                          or len(self._consumed[board]) >= 2
                          or half in self._consumed[board])
            if need_fresh:
                self._event[board] = self._do_acquire(board)
                self._consumed[board] = set()
            self._consumed[board].add(half)
            ev = self._event[board]
            g0 = board * NUM_CHAN_PER_BOARD + half * 2
            f0, f1 = self.gain_factor(g0), self.gain_factor(g0 + 1)
        # Scale samples back to true input volts (yscale is fixed at the x1 scale).
        chA = ev[half * 2].astype(float)
        chB = ev[half * 2 + 1].astype(float)
        if f0 != 1.0:
            chA = chA / f0
        if f1 != 1.0:
            chB = chB / f1
        return chA, chB

    def close(self):
        if self._fastusb_active:
            self._disable_fastusb()
        else:
            for dev in self._ftd:
                try:
                    dev.close()
                except Exception:
                    pass
        try:
            if self.ser is not None:
                # Best-effort: stop rolling trigger and switch ADCs off is
                # intentionally skipped here to keep teardown simple/safe.
                self.ser.close()
        except Exception:
            pass
        self.good = False
