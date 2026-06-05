"""Adapter presenting the original Haasoscope as Pro "usb" board objects.

Each ``OldHaasoscopeBoardAdapter`` implements the Pro "usb object" contract
(send/recv + a few config methods/attributes) for **two channels**. One physical
original board (4 channels) is exposed as two adapters:

    physical board p  ->  virtual board 2p   (channels 0,1, half 0)
                          virtual board 2p+1 (channels 2,3, half 1)

so ``num_chan_per_board`` stays 2 and the whole Pro app runs unchanged.

The adapter is, in effect, an in-process version of ``dummy_scope/dummy_server``
that drives real hardware: it interprets the Pro's 8-byte opcodes, translates the
ones that matter into legacy serial commands (via OldHaasoscopeDevice), and packs
the original 8-bit samples into the Pro's 16-bit packet format.

It subclasses ``UsbSocketAdapter`` purely so that the existing
``isinstance(usb, UsbSocketAdapter)`` / ``hasattr(usb, "socket_addr")`` checks in
the Pro code treat it as a "non-real" board (skipping PLL/clock calibration and
hardware clock-locking that the original board has no concept of). It does **not**
open any socket.
"""

import struct

from dummy_scope.USB_Socket import UsbSocketAdapter

# Packet geometry expected by data_processor.py (see _handle_read_data in
# dummy_server.py and the unpack loop at data_processor.py:186-214).
NSUBSAMPLES = 50                 # 16-bit words per logical sample block
SAMPLES_PER_BLOCK = 20           # ADC samples per channel per block (two-channel mode)
BYTES_PER_BLOCK = NSUBSAMPLES * 2
BEEF = -16657                    # 0xBEEF as signed int16
STROBE_PATTERN = [1, 2, 4, 8, 16, 32, 64, 128]

DEFAULT_FIRMWARE_VERSION = 1000031  # large -> no Pro feature gate trips (matches dummy)


def _clip16(v):
    return max(-32768, min(32767, int(v)))


def _p32(v):
    return struct.pack("<I", v & 0xFFFFFFFF)


class OldHaasoscopeBoardAdapter(UsbSocketAdapter):
    """Pro "usb object" for two channels of an original Haasoscope board."""

    is_legacy = True  # lets main_window distinguish us from a real dummy server

    def __init__(self, device, phys_board, half,
                 firmware_version=DEFAULT_FIRMWARE_VERSION):
        # NOTE: intentionally do NOT call super().__init__ (no socket).
        self.device = device
        self.phys_board = phys_board
        self.half = half
        self.device_name = f"Original Haasoscope b{phys_board} ch{half*2}-{half*2+1}"
        self.serial = f"oldhs_b{phys_board}_h{half}".encode()
        # socket_addr presence is what makes hardware_controller skip PLL calibration.
        self.socket_addr = f"oldhs:{phys_board}:{half}"
        self.beta = None
        self.good = True
        self.firmware_version = firmware_version

        # UsbSocketAdapter attributes we keep inert.
        self._socket = None
        self._buffer = b""
        self._recv_timeout = 250
        self._send_timeout = 2000

        # Queued response bytes for recv(). Each adapter is only ever driven by a
        # single Pro thread (one per board), so no lock is needed here; serial
        # access is serialized inside the shared device.
        self._rx = bytearray()

        # Cached last-sent values so we only hit the serial line on change.
        self._last_trig_level = None
        self._last_trig_rising = None
        self._last_downsample = None
        self._spi_mode = 0

        # Capability overrides consumed by ScopeState via main_window. Only the
        # first board's caps are read, but every adapter advertises them.
        # samplerate is pre-doubled: the Pro halves it in two-channel mode, so
        # 0.25 GHz -> 0.125 GHz = the original board's true 125 MS/s.
        self.caps = {
            'samplerate': 0.25,
            'yscale': device.yscale / 65536.0,
            'basevoltage': int(round(device.yscale * 1000)),  # mV (~7500)
        }

    # ------------------------------------------------------------------ #
    # usb-object contract
    # ------------------------------------------------------------------ #
    def send(self, data) -> int:
        data = bytes(data)
        if len(data) < 1:
            return 0
        resp = self._process(data)
        if resp:
            self._rx.extend(resp)
        return len(data)

    def recv(self, recv_len: int) -> bytes:
        out = bytes(self._rx[:recv_len])
        del self._rx[:recv_len]
        return out

    def set_recv_timeout(self, timeout_ms):
        self._recv_timeout = timeout_ms

    def set_send_timeout(self, timeout_ms):
        self._send_timeout = timeout_ms

    def set_latency_timer(self, latency_ms):
        pass

    def flush_buffer(self):
        self._rx = bytearray()

    def close(self):
        # The shared device is closed once by the entry point, not per adapter.
        self.good = False

    def reopen(self):
        pass

    # ------------------------------------------------------------------ #
    # Opcode dispatch (mirrors dummy_server._process_command)
    # ------------------------------------------------------------------ #
    def _process(self, data):
        op = data[0]
        sub = data[1] if len(data) > 1 else 0
        if op == 0:
            return self._read_data(data)
        if op == 1:
            return self._trigger_check(data)
        if op == 2:
            return self._opcode2(sub, data)
        if op == 3:
            return self._spi(data)
        if op == 4:
            self._spi_mode = data[1]
            return _p32(0)
        if op == 8:
            return self._trigger_info(data)
        if op == 9:
            return self._downsample(data)
        if op == 10:
            return self._channel_control(data)
        # 5 (PLL reset), 6 (phase), 7 (clock switch), 11 (LEDs), and anything
        # else: acknowledge with a 4-byte zero.
        return _p32(0)

    def _gchan(self, pro_chan):
        """Global device channel index for this half's Pro channel (0 or 1)."""
        return self.phys_board * 4 + self.half * 2 + pro_chan

    def _trigger_check(self, data):
        # data[1] = trigger type (1 rising, 2 falling). Drive the edge lazily.
        rising = (data[1] == 1)
        if rising != self._last_trig_rising:
            self.device.set_trigger_rising(rising)
            self._last_trig_rising = rising
        # Always report "event ready" (byte0=251), trigger position 0 in byte1.
        return bytes([251, 0, 0, 0])

    def _opcode2(self, sub, data):
        if sub == 0:                      # firmware version
            return _p32(self.firmware_version)
        if sub == 1:                      # board digital status: bit5 = PLL locked
            return _p32(0x20)
        if sub == 4:                      # predata: byte0=merge counter, byte1=triggerphase
            return bytes([1, 0, 0, 0])
        if sub == 5:                      # clock status (clockused / LVDS ordering)
            # half 0 looks like the first board (internal clock, bit3);
            # later halves look like external-clock-locked slaves (bit1).
            return _p32((1 << 3) if (self.phys_board == 0 and self.half == 0) else (1 << 1))
        return _p32(0)

    def _spi(self, data):
        """opcode 3: intercept the Pro's gain (setgain) and offset (dooffset)
        SPI writes and translate them to legacy hardware commands.

        setgain (board.py:308): mode 0, packet [3, cs, 0x02, 0x00, 26-gain_db, ...]
                 cs=2 -> chan0, cs=1 -> chan1.
        dooffset (board.py:317): mode 1, packet [3, 4, addr, hi, lo, ...]
                 addr=0x19 -> chan0, 0x18 -> chan1, dacval = (hi<<8)|lo.
        """
        cs = data[1]
        addr = data[2]
        if self._spi_mode == 0 and addr == 0x02 and cs in (1, 2):
            pro_chan = 0 if cs == 2 else 1
            gain_db = 26 - data[4]
            level = 100 if gain_db >= 34 else (10 if gain_db >= 14 else 1)
            self.device.set_channel_gain(self._gchan(pro_chan), level)
        elif self._spi_mode == 1 and cs == 4 and addr in (0x18, 0x19):
            pro_chan = 0 if addr == 0x19 else 1
            dacval = (data[3] << 8) | data[4]
            self.device.set_channel_offset(self._gchan(pro_chan), dacval)
        # Return the ADC vendor id the Pro expects (matches dummy_server).
        return bytes([0x51, 0x00, 0x00, 0x00])

    def _channel_control(self, data):
        """opcode 10 (board.py:355-376): impedance / AC-DC coupling / attenuator.
        controlbit 0/4 = impedance(chan0/1), 1/5 = coupling, 2/6 = attenuator."""
        controlbit = data[1]
        value = data[2]
        if controlbit in (0, 4):        # impedance: value = int(onemeg)
            self.device.set_channel_termination(
                self._gchan(0 if controlbit == 0 else 1), bool(value))
        elif controlbit in (1, 5):      # coupling: value = int(not ac) -> 1 = DC
            self.device.set_channel_coupling(
                self._gchan(0 if controlbit == 1 else 1), bool(value))
        # controlbit 2/6 (attenuator) and 7 (oversample split) have no legacy
        # equivalent in v1; acknowledge and ignore.
        return _p32(0)

    def _trigger_info(self, data):
        # opcode 8: data[1] = trigger level (0-255).
        level = data[1]
        if level != self._last_trig_level:
            self.device.set_trigger_level(level)
            self._last_trig_level = level
        return _p32(0)

    def _downsample(self, data):
        # opcode 9: data[1] = ds (power of two).
        ds = data[1]
        if ds != self._last_downsample:
            self.device.set_downsample(ds)
            self._last_downsample = ds
        return _p32(0)

    # ------------------------------------------------------------------ #
    # Data packing
    # ------------------------------------------------------------------ #
    def _read_data(self, data):
        """Pack one event's worth of this half's two channels into Pro format."""
        expect_len = struct.unpack("<I", data[4:8])[0] if len(data) >= 8 else 0
        nblocks = expect_len // BYTES_PER_BLOCK

        # chA -> "first" channel of the pair (words 20-39, c1 = board*2)
        # chB -> "second" channel of the pair (words 0-19, c2 = board*2+1)
        chA, chB = self.device.get_half_data(self.phys_board, self.half)
        n = len(chA)

        out = bytearray()
        for s in range(nblocks):
            base = s * SAMPLES_PER_BLOCK
            # words 0-19: second channel (chB)
            for i in range(SAMPLES_PER_BLOCK):
                idx = base + i
                v = int(chB[idx]) if idx < n else 0
                out += struct.pack("<h", _clip16(v << 8))
            # words 20-39: first channel (chA)
            for i in range(SAMPLES_PER_BLOCK):
                idx = base + i
                v = int(chA[idx]) if idx < n else 0
                out += struct.pack("<h", _clip16(v << 8))
            # words 40-43: clocks (must be 341 or 682, alternating)
            for k in range(4):
                out += struct.pack("<h", 341 if (s + k) % 2 == 0 else 682)
            # words 44-47: strobes (one-hot)
            for k in range(4):
                out += struct.pack("<h", STROBE_PATTERN[(s + k) % 8])
            # word 48: control byte (0); word 49: BEEF marker
            out += struct.pack("<h", 0)
            out += struct.pack("<h", BEEF)

        # Pad any trailing partial request so recv() can return exactly expect_len.
        if len(out) < expect_len:
            out += b"\x00" * (expect_len - len(out))
        return bytes(out)


def make_adapters_for_device(device, firmware_version=DEFAULT_FIRMWARE_VERSION):
    """Build the list of virtual Pro boards for a connected device.

    Returns 2 * device.num_boards adapters, ordered so that virtual board index
    ``2*p + h`` is physical board ``p`` half ``h``.
    """
    adapters = []
    for p in range(device.num_boards):
        for h in (0, 1):
            adapters.append(OldHaasoscopeBoardAdapter(device, p, h, firmware_version))
    return adapters
