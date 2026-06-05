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
| `yscale` (capability) | `7.5 / 65536` (first cut; tune on bench) |
| gain (SPI, dB) | x1 / x10 (cmd 134) + sample scaling compensation |
| offset (SPI, 16-bit DAC) | 12-bit DAC (`setdac`), additive on calibrated baseline |
| AC/DC (opcode 10) | IO-expander `0x20` reg `0x13` (`setacdc`) |
| PLL / clock calibration | skipped (adapter carries `socket_addr`, like the dummy) |

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

## Known limitations (need a physical board to finish)

- `yscale` / offset-mapping constants are first-cut; tune against a known signal.
- **ADC byte interpretation (int8 vs uint8):** we treat raw bytes as unsigned
  offset-binary and invert with `127 - byte` (monotonic over 0..255). The legacy
  code reads them as signed `int8` before `127 - x`, which differs for bytes
  > 127. Ours is the physically-correct interpretation; if the waveform looks
  discontinuous around mid-scale on real hardware, try matching the legacy int8
  behavior. This belongs with the scaling calibration above.
- ×100 super-gain and 50 Ω / 1 MΩ impedance are physical switches on v9.0 boards.
- Logic analyzer and slow MAX10 ADC are not yet exposed.
- Multi-board DAC table/board-order indexing needs verification on a real chain.
