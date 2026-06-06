# old_haasoscope — Original Haasoscope backend

Lets the modern HaasoscopePro application drive the **original Haasoscope**
hardware (4-channel, 8-bit, 125 MS/s, serial-controlled), so the old hardware
gains all the Pro features without forking the GUI. Run it with `--oldhs`
(see the main [software/README.md](../README.md) for user-facing options).

Original hardware/software repo: https://github.com/drandyhaas/Haasoscope
(the byte sequences here are ported from its `libs/HaasoscopeLibQt.py`).

## Design

The original board is incompatible with the Pro at every layer (serial vs FIFO
transport, different command set, 8-bit vs 16-bit data, 4 vs 2 channels). Rather
than fork the Pro frontend, we add a **backend adapter** behind the thin "usb
object" interface the Pro app already talks to (the same seam the dummy server
uses).

The key trick: the Pro treats channels as **2 per board** (its own 4-channel
mode is two daisy-chained boards). So each physical original board (4 ch) is
exposed as **two virtual Pro boards of 2 channels each**:

```
physical board p  ->  virtual board 2p   (channels 0,1, "half 0")
                      virtual board 2p+1 (channels 2,3, "half 1")
```

This keeps `num_chan_per_board == 2`, so none of the Pro's channel-count logic
changes — the new code is confined to this package plus a few small, default-
preserving hooks (`scope_state` caps, `main_window` labelling, `HaasoscopeProQt`
argument handling).

```
Original board (CH340 serial @1.5Mbaud  [+ optional FT232H for data])
        │
   OldHaasoscopeDevice          owns the connection; init/config/acquire 4 ch
        │  (thread-locked; one physical acquisition feeds both halves)
   ┌────┴─────┐
 Adapter half0  half1           each implements the Pro "usb object" contract
 (ch 0,1)       (ch 2,3)        translate Pro opcodes; pack data to Pro format
        │            │
        └─ usbs = [half0, half1, …] ─► MainWindow(usbs)  (unchanged Pro app)
```

## Files

- **`old_device.py`** — `OldHaasoscopeDevice`: slim serial driver (byte sequences
  ported from the legacy `HaasoscopeLibQt.py`). Connection, init, gain/coupling/
  offset, DAC calibration (`getIDs` + `readcalib`), acquisition (serial and
  FT232H fast-USB), and serial-robustness logic.
- **`old_adapter.py`** — `OldHaasoscopeBoardAdapter`: in-process opcode translator
  (modeled on `dummy_scope/dummy_server.py`). Implements `send`/`recv`, maps the
  Pro's gain/offset/coupling opcodes to device calls, and packs the 8-bit data
  into the Pro's 16-bit / 50-word-per-block packet format.
- **`__init__.py`** — exports plus `make_adapters_for_device()`.

## Capability mapping

| Pro side | Original hardware |
|----------|-------------------|
| transport `send`/`recv` (8-byte opcodes) | CH340 serial commands; data via serial or FT232H |
| data: 16-bit, 50 words/block, BEEF/clock markers | 8-bit centered samples `(127 - byte) << 8`, markers synthesized |
| `samplerate` (capability) | `0.25` GHz → Pro halves it in two-channel mode → 125 MS/s |
| `yscale` (capability) | fixed `1/8192` (ADC→divisions); voltage cal is in `basevoltage` |
| `basevoltage` (capability) | `device.yscale × 1000` mV/div (5.5 V/div; bench-cal'd for 50 Ω) |
| gain (SPI, dB) | x1 / x10 (cmd 134) + sample scaling compensation |
| offset (SPI, 16-bit DAC) | 12-bit DAC (`setdac`), additive on calibrated baseline |
| AC/DC (opcode 10) | IO-expander `0x20` reg `0x13` (`setacdc`) |
| PLL / clock calibration | skipped (adapter carries `socket_addr`, like the dummy) |

## Connection / port selection

`OldHaasoscopeDevice(serport=...)` uses the given port if one is passed
(`HaasoscopeProQt.py --oldhs-port COM13`). Otherwise `find_old_haasoscope_ports()`
auto-detects: it matches the CH340 USB-UART (VID:PID `1A86:7523`) and returns
candidates **sorted descending**, then `open()` takes the first — mirroring the
legacy `HaasoscopeLibQt.setup_connections()` (`ports.sort(reverse=True)` + first
match). Because pyserial orders `COM`/`ttyUSB` names numerically, a machine with
both `COM6` and `COM13` picks `COM13`, the same as the old app. With more than one
CH340 adapter present this is just a heuristic, so prefer `--oldhs-port` to be
explicit.

A couple of subtleties worth knowing if you touch the init path:
- Firmware-version detection (`get_firmware_version`) selects the board with
  `[30 + board]` for board < 10, **not** `_select_board()` — at that point
  `minfirmwareversion` is still the default 255, and `_select_board` would emit
  the firmware ≥17-only `[53, board]` form. The legacy code is deliberate about
  this (`HaasoscopeLibQt.py:376`).
- `getIDs()` restores the full `sertimeout` for its 8-byte read; `open()` lowers
  `ser.timeout` to the short streaming poll interval, which is too brief for the
  ID reply.

## Serial robustness

The original board streams without hardware flow control, so the host can drop
bytes at 1.5 Mbaud. Instead of the legacy throttle (`serialdelaytimerwait`):

1. **Low-latency mode** (`set_low_latency_mode`, Linux) so the driver drains the
   RX FIFO promptly — the actual cause of byte loss.
2. **Accumulating read** with a progress-based deadline (assembles bursty data).
3. **Retry-on-incomplete** — flush/**drain to idle**, then re-acquire a fresh
   event (cheap, since the board free-runs); bounded by `max_read_retries`.

`--oldhs-fastusb` moves bulk data to the FT232H sync-245 FIFO for the highest
rate (commands still go over serial).

## Tests

`../test/test_old_adapter.py` (no hardware required):
- adapter ↔ `DataProcessor` roundtrip (packet validation + exact reconstruction)
- gain / coupling / offset / DAC calibration against the real device logic
- FT232H fast-USB padded-buffer parsing
- serial retry-on-incomplete

```bash
cd software && python test/test_old_adapter.py
```

## Pro UI behaviour in legacy mode

The Pro app's UI is the original's superset, so legacy mode disables or constrains
the controls the original hardware can't honour. Done in `main_window.py` keyed on
`self.is_legacy` and in `hardware_controller.tell_downsample` keyed on the adapter's
`is_legacy` flag.

- **Y-axis convention:** Pro shows *true input volts* — the legacy device pre-
  divides ADC samples by the analog gain factor in `OldHaasoscopeDevice.get_half_data`,
  so a 0.1 V input at ×10 reads as 0.1 V on the trace. The original `HaasoscopeQt.py`
  used a different convention (raw amp output, only the `Vmean`/`Vrms` text
  compensated), so the y-axis numbers between the two apps will not match.
- **Two-channel mode** is forced on (samplerate cap is pre-doubled and the
  packet layout assumes it). `twochanCheck` is disabled.
- **50 Ω / 1 MΩ (`ohmCheck`) is disabled.** On v9.0 it's a physical switch the
  software can't drive, and the Pro's `mohm` flag silently halves V/div in
  `gain_changed`. `gain_changed` now skips that divisor entirely for legacy so
  the displayed V/div tracks reality.
- **Attenuator (`attCheck`) is disabled** — no hardware equivalent.
- **Gain (`gainBox`) is restricted to {0, 14, 34} dB** (the x1 / x10 / x100 snap
  points). Spinbox max is 34 (so x100 is reachable, vs the Pro default of 26)
  and `singleStep = 20` so up/down cleanly walks the three values. `gain_changed`
  snaps any intermediate value to the nearest of {0, 14, 34} before computing
  V/div, so the displayed mV/div matches the engaged hardware gain. **Caveat:**
  ×100 super-gain on v9.0 is a *physical DPDT switch on the board* — selecting
  it from the UI only updates the DAC-baseline selection and the sample
  compensation factor, it does NOT engage the analog ×100 path; the user must
  flip the physical switch for the trace to actually be ×100.
- **Timebase merging-factor encoding bypassed.** The Pro's `tell_downsample()`
  repurposes downsample values 1–5 as "stay at full rate + FPGA-side averaging,"
  which the legacy hardware doesn't implement. The adapter is detected via
  `is_legacy` and `tell_downsample` forwards `ds` unchanged with `merging=1`,
  so `state.downsamplefactor = 2^ds` matches the actual hardware divisor and
  the x-axis time/div text is correct.
- **Downsample cap of 18.** Mirrors the original `HaasoscopeLibQt.py`
  `maxdownsample`; the "slower" button stops there for legacy.
- **AC-mode offset scaling** skips the Pro's `245/160` front-end factor, since
  legacy compensates AC vs DC via separate DAC baseline tables (`lowac`/
  `highac`/etc.), not via that ratio.

## Known limitations (need a physical board to finish)

- **Vertical calibration:** the Pro computes volts as `sample × yscale × VperD`
  (`VperD = basevoltage/1000`), so `yscale` and `basevoltage` must be independent
  — if both derive from one constant it enters volts *quadratically*. The adapter
  fixes `caps['yscale'] = 1/8192` (display geometry) and puts the whole linear
  calibration in `caps['basevoltage'] = device.yscale × 1000` mV/div. Bench-cal'd
  for **50 Ω** mode against a 5.0 V Vpp source; re-tune with
  `device.yscale *= true_Vpp / measured_Vpp`. The 1 MΩ path may differ (50 Ω/1 MΩ
  is a physical switch the software can't read).
- **Offset calibration is per-(gain × supergain × AC/DC).** Currently only the
  (x1, normal, DC) entry in `OFFSET_GAIN_BY_MODE` is bench-tuned (`-1/192`); the
  other 7 combos default to the same value and need re-tuning. Method per combo:
  set the gain/coupling, send a known offset click, measure the on-screen mV
  shift, then `OFFSET_GAIN_BY_MODE[key] *= intended/measured`.
- **ADC byte interpretation (int8 vs uint8):** we treat raw bytes as unsigned
  offset-binary and invert with `127 - byte` (monotonic over 0..255). The legacy
  code reads them as signed `int8` before `127 - x`, which differs for bytes
  > 127. Ours is the physically-correct interpretation; if the waveform looks
  discontinuous around mid-scale on real hardware, try matching the legacy int8
  behavior. This belongs with the scaling calibration above.
- ×100 super-gain and 50 Ω / 1 MΩ impedance are physical switches on v9.0 boards.
- Logic analyzer and slow MAX10 ADC are not yet exposed.
- Multi-board DAC table/board-order indexing needs verification on a real chain.
