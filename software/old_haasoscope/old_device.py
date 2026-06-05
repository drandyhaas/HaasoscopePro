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
                 serial_delay=100, debug=False, calib_dir=None):
        self.serport = serport
        self.calib_dir = calib_dir
        self.num_boards = num_boards
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
        self.good = True
        return True

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
    # Acquisition (shared between the two adapter halves)
    # ------------------------------------------------------------------ #
    def _do_acquire(self, board):
        """Arm and read one event for a physical board.

        Returns a (4, num_samples) int16 array of *centered* sample values
        (127 - raw_byte), i.e. positive = positive volts after the op-amp
        inversion. On a short/timed-out read returns zeros.
        """
        # Prime the trigger (cmd 100), then select+request data for this board
        # (cmd 51+board for fw>=17, else 10+board) - HaasoscopeLibQt.py:1594,1400.
        self._w(100)
        if self.minfirmwareversion >= 17:
            self._w(51, board)
        else:
            self._w(10 + board)

        raw = self.ser.read(self.num_bytes)
        if len(raw) != self.num_bytes:
            if self.debug:
                print(f"old acquire: wanted {self.num_bytes} bytes, "
                      f"got {len(raw)} from board {board}")
            return np.zeros((NUM_CHAN_PER_BOARD, self.num_samples), dtype=np.int16)

        buf = np.frombuffer(raw, dtype=np.uint8)
        chans = np.empty((NUM_CHAN_PER_BOARD, self.num_samples), dtype=np.int16)
        for c in range(NUM_CHAN_PER_BOARD):
            seg = buf[c * self.num_samples:(c + 1) * self.num_samples].astype(np.int16)
            chans[c] = 127 - seg  # invert (op amp) + center -> range -128..127
        return chans

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
        try:
            if self.ser is not None:
                # Best-effort: stop rolling trigger and switch ADCs off is
                # intentionally skipped here to keep teardown simple/safe.
                self.ser.close()
        except Exception:
            pass
        self.good = False
