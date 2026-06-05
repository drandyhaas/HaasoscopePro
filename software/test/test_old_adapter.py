"""Offline test for the legacy Haasoscope adapter.

Drives OldHaasoscopeBoardAdapter with the exact opcode sequences that
hardware_controller emits, then runs the produced packets through the real
DataProcessor to confirm:
  - the Pro accepts the packets (no BEEF / clock / strobe validation errors)
  - both channels of both halves reconstruct the injected 8-bit waveform

No hardware required: a FakeDevice stands in for OldHaasoscopeDevice.
Run from the software/ dir:  python -m pytest test/test_old_adapter.py -q
or:                          python test/test_old_adapter.py
"""

import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from old_haasoscope.old_adapter import make_adapters_for_device  # noqa: E402
from old_haasoscope.old_device import OldHaasoscopeDevice  # noqa: E402
from scope_state import ScopeState  # noqa: E402
from data_processor import DataProcessor  # noqa: E402
from spi import set_spi_mode  # noqa: E402
from board import setgain, dooffset, setchanacdc  # noqa: E402
from utils import inttobytes  # noqa: E402


class FakeDevice:
    """Mimics OldHaasoscopeDevice's interface with deterministic 8-bit data."""

    def __init__(self, num_boards=1, num_samples=4096):
        self.num_boards = num_boards
        self.num_samples = num_samples
        self.yscale = 7.5
        self.trig_level = None
        self.trig_rising = None
        self.downsample = None
        # Build 4 distinct synthetic raw-byte channels per board (offset binary,
        # 127 = 0V). Centered values returned are (127 - byte), range -128..127.
        self._raw = {}
        for b in range(num_boards):
            chans = np.empty((4, num_samples), dtype=np.int16)
            t = np.arange(num_samples)
            for c in range(4):
                # Different amplitude/phase per channel; stay within 8-bit range.
                byte = 127 + (60 * np.sin(2 * np.pi * (t / 50.0) + c)).astype(int)
                byte = np.clip(byte, 0, 255)
                chans[c] = 127 - byte  # centered, op-amp inverted
            self._raw[b] = chans

    def set_trigger_level(self, level):
        self.trig_level = level

    def set_trigger_rising(self, rising):
        self.trig_rising = rising

    def set_downsample(self, ds):
        self.downsample = ds

    def get_half_data(self, board, half):
        ch = self._raw[board]
        return ch[half * 2], ch[half * 2 + 1]


def _drive_one_board(adapter, expect_samples, expect_samples_extra):
    """Issue the opcode sequence the controller uses, return the data packet."""
    # opcode 1: trigger check (rising, two-channel)
    adapter.send(bytes([1, 1, 1, 99] + inttobytes(expect_samples + expect_samples_extra)))
    tc = adapter.recv(4)
    assert tc[0] == 251, "adapter did not report event ready"
    # opcode 2,4: predata
    adapter.send(bytes([2, 4, 100, 100, 100, 100, 100, 100]))
    pre = adapter.recv(4)
    assert pre[1] == 0, "triggerphase should be 0"
    # opcode 0: read data
    expect_len = (expect_samples + expect_samples_extra) * 2 * 50
    adapter.send(bytes([0, 99, 99, 99] + inttobytes(expect_len)))
    data = adapter.recv(expect_len)
    assert len(data) == expect_len, f"got {len(data)} bytes, expected {expect_len}"
    return data


def test_adapter_roundtrip():
    device = FakeDevice(num_boards=1, num_samples=4096)
    adapters = make_adapters_for_device(device)
    assert len(adapters) == 2  # one physical board -> two virtual boards

    caps = adapters[0].caps
    state = ScopeState(num_boards=len(adapters), num_chan_per_board=2, caps=caps)
    # main_window forces two-channel mode on for legacy boards (default is False);
    # mirror that here since the adapter always packs the two-channel layout.
    state.dotwochannel = [True] * state.num_board
    es, ese = state.expect_samples, state.expect_samples_extra

    # Allocate xy arrays exactly like main_window.allocate_xy_data().
    num_ch = state.num_chan_per_board * state.num_board
    nsamp = 4 * 10 * es
    xy = np.zeros((num_ch, 2, nsamp), dtype=float)

    processor = DataProcessor(state)

    for board_idx, adapter in enumerate(adapters):
        data = _drive_one_board(adapter, es, ese)
        # Must not raise (BEEF / clock validation lives here).
        processor.process_board_data(data, board_idx, xy)

    # Verify reconstruction. The Pro applies a constant trigger-alignment shift
    # (downsampleoffset) when placing samples, so compare against the source at
    # the best integer shift and require an exact match there. Values are scaled
    # by yscale*256 (the <<8 packing convention).
    scale = state.yscale * 256.0

    def best_shift_error(recon, source):
        ncheck = es * 20
        rec = recon[:ncheck]
        # Find the integer shift d such that rec[i] == source[i+d]*scale.
        best = (None, np.inf)
        for d in range(0, 80):  # downsampleoffset is small and non-negative here
            if ncheck + d > len(source):
                break
            exp = source[d:d + ncheck].astype(float) * scale
            err = np.max(np.abs(rec - exp))
            if err < best[1]:
                best = (d, err)
        return best

    for board_idx, adapter in enumerate(adapters):
        chA, chB = device.get_half_data(adapter.phys_board, adapter.half)
        dA, errA = best_shift_error(xy[board_idx * 2][1], chA)
        dB, errB = best_shift_error(xy[board_idx * 2 + 1][1], chB)
        print(f"  board {board_idx}: chA shift={dA} err={errA:.3g}, "
              f"chB shift={dB} err={errB:.3g}")
        assert errA < 1e-6, f"board {board_idx} chA reconstruction error {errA}"
        assert errB < 1e-6, f"board {board_idx} chB reconstruction error {errB}"
        assert dA == dB, "channels of a half must share the same alignment shift"

    print("test_adapter_roundtrip: PASS")
    print(f"  trig_rising driven to: {device.trig_rising}")
    print(f"  caps: {caps}")


class FakeSerial:
    """Minimal stand-in for pyserial Serial used to exercise the real
    OldHaasoscopeDevice logic without hardware. Records all written bytes and
    returns context-appropriate read data."""

    def __init__(self, num_samples):
        self.num_samples = num_samples
        self.num_bytes = num_samples * 4
        self.timeout = 0.25
        self.sent = bytearray()

    def write(self, data):
        self.sent.extend(bytes(data))

    def read(self, n):
        if n == 1:
            return bytes([20])               # firmware version
        if n == 8:
            return bytes(range(8))           # unique ID
        # acquisition: 4 channels * num_samples of offset-binary bytes
        return bytes([(i % 251) for i in range(n)])

    def close(self):
        pass


def _count_subseq(buf, sub):
    sub = bytes(sub)
    return sum(1 for i in range(len(buf) - len(sub) + 1) if buf[i:i + len(sub)] == sub)


def test_gain_coupling_offset():
    """Drive the real device front-end logic through board.py helpers."""
    device = OldHaasoscopeDevice(num_boards=1, ram_width=9)
    device.ser = FakeSerial(device.num_samples)
    device.good = True
    assert device.init()

    # init() should have read one unique ID and pushed the DAC for all 4 channels
    # (i2c writes to DAC at 0x60 -> subsequence [136, 3, 96]).
    assert len(device.uniqueIDs) == 1
    dac_writes_after_init = _count_subseq(device.ser.sent, [136, 3, 96])
    assert dac_writes_after_init >= 4, f"expected >=4 DAC writes, got {dac_writes_after_init}"

    # init() must send telltickstowait (cmd 125,1) and a default trigger point
    # (cmd 121, centered = num_samples//2 = 256 -> hi/lo 1,0 for ram_width=9).
    assert _count_subseq(device.ser.sent, [125, 1]) >= 1, "telltickstowait (125) not sent"
    assert _count_subseq(device.ser.sent, [121, 1, 0]) >= 1, "default trigger point (121) not sent"

    adapters = make_adapters_for_device(device)
    half0 = adapters[0]  # device channels 0,1

    # --- Trigger point: opcode 8 position maps to cmd 121 (blocks*20 samples) ---
    half0.send(bytes([8, 128, 2, 0, 10, 0, 0, 0]))  # triggerpos = 10 -> 200 samples
    half0.recv(4)
    assert _count_subseq(device.ser.sent, [121, 0, 200]) >= 1, \
        "opcode 8 trigger position not mapped to cmd 121"

    # --- Gain: drive setgain via board.py through the adapter (chan0, 20 dB) ---
    set_spi_mode(half0, 0)
    half0.recv(4)
    setgain(half0, 0, 20, False)   # 20 dB -> x10
    half0.recv(4)
    assert device.gain[0] == 0, "20 dB should select x10 (gain flag 0)"
    assert _count_subseq(device.ser.sent, [134]) >= 1, "command 134 (x10 toggle) not sent"
    assert device.gain_factor(0) == 10.0

    # Lower gain back to x1 (0 dB).
    setgain(half0, 0, 0, False)
    half0.recv(4)
    assert device.gain[0] == 1, "0 dB should select x1"

    # --- Coupling: AC on chan0 via setchanacdc (ac=True) ---
    before = _count_subseq(device.ser.sent, [136, 2, 32, 19])  # i2c 0x20 reg 0x13
    setchanacdc(half0, 0, True, False)
    half0.recv(4)
    assert device.acdc[0] == 0, "AC coupling should set acdc flag to 0"
    after = _count_subseq(device.ser.sent, [136, 2, 32, 19])
    assert after > before, "coupling i2c (0x20 0x13) not sent"

    # Channel 3 coupling must work too (the legacy code's range(0,3) never drove
    # bit 3); all 4 channels should be controllable.
    device.set_channel_coupling(3, is_dc=False)   # AC -> bit 3 clear
    assert (device._b20[0] & (1 << 3)) == 0, "channel 3 AC not reflected in b20 bit 3"
    device.set_channel_coupling(3, is_dc=True)    # DC -> bit 3 set
    assert (device._b20[0] & (1 << 3)) != 0, "channel 3 DC not reflected in b20 bit 3"

    # --- Offset: dooffset shifts the DAC away from the calibrated baseline ---
    base = device.daclevels['low'][0]
    dac_before = _count_subseq(device.ser.sent, [136, 3, 96])
    dooffset(half0, 0, 50, 5.0, False)   # nonzero offset
    half0.recv(4)
    assert device.user_offset[0] != 0.0, "offset not applied"
    dac_after = _count_subseq(device.ser.sent, [136, 3, 96])
    assert dac_after > dac_before, "offset did not push a new DAC value"

    # --- Gain compensation: at x10 the returned samples are 1/10 of raw ---
    device.gain[0] = 1  # x1
    a1, _ = device.get_half_data(0, 0)
    device.gain[0] = 0  # x10
    a10, _ = device.get_half_data(0, 0)
    # Same raw event divided by 10 (allow tiny float error).
    assert np.max(np.abs(a10 - a1 / 10.0)) < 1e-9, "gain compensation not applied"

    print("test_gain_coupling_offset: PASS")
    print(f"  DAC writes after init: {dac_writes_after_init}, baseline ch0: {base}")


def test_fastusb_parse():
    """Verify the FT232H fast-USB padded buffer is parsed into the right channels."""
    dev = OldHaasoscopeDevice(num_boards=1, ram_width=9, use_fastusb=True)
    ns = dev.num_samples
    pad, endpad = dev.fastusbpadding, dev.fastusbendpadding
    nb = dev.num_bytes + pad * 4

    # Lay out 4 channels of known bytes at the padded offsets.
    raw = bytearray(nb)
    expected = []
    for c in range(4):
        off = c * ns + (c + 1) * pad - endpad
        vals = [(c * 30 + (i % 100)) % 251 for i in range(ns)]
        for i, v in enumerate(vals):
            raw[off + i] = v
        expected.append(vals)

    class FakeFtd:
        def read(self, n):
            return bytes(raw[:n])

        def getQueueStatus(self):
            return 0

        def purge(self, mask):
            pass

        def close(self):
            pass

    dev.ser = FakeSerial(ns)          # arm/request commands still go over serial
    dev._ftd = [FakeFtd()]
    dev.usbsermap = [0]
    dev._fastusb_active = True

    chans = dev._do_acquire(0)
    for c in range(4):
        exp = np.array([127 - v for v in expected[c]], dtype=np.int16)
        assert np.array_equal(chans[c], exp), f"fast-USB channel {c} mismatch"

    print("test_fastusb_parse: PASS")


def test_serial_retry_on_incomplete():
    """An incomplete serial read should flush and re-acquire, not return zeros."""
    dev = OldHaasoscopeDevice(num_boards=1, ram_width=9)
    dev.minfirmwareversion = 20

    class FlakySerial(FakeSerial):
        def __init__(self, ns, fails):
            super().__init__(ns)
            self.fails = fails
            self.resets = 0

        def read(self, n):
            if self.fails > 0:
                return b""              # simulate an overrun: no data this event
            if n == self.num_bytes:
                return bytes([(i % 251) for i in range(n)])
            return b""

        def reset_input_buffer(self):
            self.resets += 1
            self.fails -= 1             # let the next acquisition succeed

    dev.ser = FlakySerial(dev.num_samples, fails=1)
    chans = dev._do_acquire(0)
    assert dev.ser.resets >= 1, "reset_input_buffer not called on incomplete read"
    assert chans.shape == (4, dev.num_samples)
    assert np.any(chans != 0), "expected a valid event after retry, not zeros"
    print("test_serial_retry_on_incomplete: PASS")


if __name__ == "__main__":
    test_adapter_roundtrip()
    test_gain_coupling_offset()
    test_fastusb_parse()
    test_serial_retry_on_incomplete()
