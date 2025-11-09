# External Trigger Echo Delay Calibration

## Overview

The Haasoscope Pro supports daisy-chaining multiple boards via LVDS connections. When multiple boards are synchronized, one board can generate triggers that propagate to other boards through the LVDS chain. However, LVDS signal propagation introduces delays that vary based on cable length and board position in the chain.

The **LVDS delay calibration** mechanism automatically measures and compensates for these trigger propagation delays, ensuring that waveforms from all boards are correctly time-aligned.

## Quick Start

**Automatic Calibration (Recommended):**

The system automatically performs LVDS calibration in these scenarios:

1. **Initial Setup**: After PLL reset completes during startup, calibration runs automatically for the initial trigger board
2. **Switching Trigger Sources**: When you set a different board to channel-based trigger (Rising/Falling Ch0 or Ch1), calibration runs automatically if no saved calibration exists for that trigger board
3. **Restoring Saved Calibrations**: When switching to a trigger board with existing calibration, the saved values are restored automatically

**To use:**
1. Start the application (PLL reset happens automatically)
2. Wait for initial LVDS calibration to complete (~5-50 acquisition cycles per board)
3. Switch trigger sources as needed - calibration is automatic!

**Manual Calibration:**

You can also manually trigger calibration via **Calibration → Board LVDS delays** menu.

**Important Notes:**
- Only one board can be self-triggering at a time (enforced automatically)
- Calibration runs asynchronously in the event loop (UI remains responsive)
- Each trigger source board has its own saved calibration set
- PLL resets are blocked during calibration to prevent interference
- Automatic calibration requires acquisition to be running (not paused)

## Architecture

### Event-Driven Calibration

The calibration system is **non-blocking** and runs asynchronously:

1. `calibrate_lvds_delays()` validates configuration and sets up state
2. Returns immediately to the UI
3. Calibration progresses in background via `_get_predata()` during normal acquisition
4. Each board is calibrated sequentially
5. Results are saved and firmware is updated when complete

State tracking in `scope_state.py`:
```python
self.lvds_calibration_active = False          # Whether calibration is running
self.lvds_calibration_boards = []             # Boards to calibrate
self.lvds_calibration_current_idx = 0         # Current board index
self.lvds_calibration_cycles = 0              # Cycles spent on current board
self.lvds_calibration_max_cycles = 50         # Timeout threshold
self.lvds_calibration_results = []            # Accumulated results
self.lvds_calibration_sets = {}               # Saved calibrations per trigger board
```

### Delay Compensation Split

Delay compensation is split between **firmware** and **software** for optimal precision:

**Firmware (send_trigger_info)** - Coarse 40-sample quantization:
```python
triggerpos += int(8 * lvdstrigdelay[board] / 40 / downsamplefactor / factor)
```
- Adjusts trigger position in 40-sample chunks
- Applied when trigger threshold/mode changes
- Limited precision but faster hardware response

**Software (data_processor.py)** - Fine sample-level residual:
```python
# Total correction needed
total_lvds_correction = 8 * lvdstrigdelay[board] / downsamplefactor

# What firmware already applied
fw_lvds_correction = 40 * factor * int(8 * lvdstrigdelay[board] / 40 / downsamplefactor / factor)

# Software applies the residual
offset -= int(total_lvds_correction - fw_lvds_correction)
```
- Corrects for firmware quantization error
- Sample-level precision for perfect alignment
- Applied during waveform data processing

**Why split?**
- Firmware operates in fixed 40-sample windows
- Software can adjust per-sample for fine alignment
- Combined approach gives best of both: fast firmware response + precise software correction

### Saved Calibrations

Calibrations are **saved per trigger source board**:

```python
state.lvds_calibration_sets = {
    0: {1: 4.5, 2: 9.2, 3: 13.8},  # When Board 0 is trigger source
    1: {0: 3.8, 2: 4.6, 3: 9.1},   # When Board 1 is trigger source
    2: {0: 8.9, 1: 4.2, 3: 4.7},   # When Board 2 is trigger source
}
```

When you switch trigger sources (by setting a different board to channel-based triggering):
1. All other boards are automatically set to external trigger
2. Previously saved calibration for that trigger board is restored
3. If no saved calibration exists, current delays are used
4. Firmware trigger positions are updated

## Hardware Topology

Boards are connected in a daisy-chain configuration:

```
Board 0 <--LVDS--> Board 1 <--LVDS--> Board 2 <--LVDS--> Board N-1
```

Key signals transmitted over LVDS between boards:
- **lvdsout_trig** / **lvdsin_trig**: Forward trigger signal (board i → board i+1)
- **lvdsout_trig_b** / **lvdsin_trig_b**: Backward trigger signal (board i → board i-1)
- **clkout** / **clkin**: Clock synchronization

The trigger signals can propagate in both directions:
- **Forward**: From lower-indexed board to higher-indexed board
- **Backward**: From higher-indexed board to lower-indexed board (includes tuning factor)

## Firmware Components

### Phase Difference Registers

The firmware tracks trigger signal timing using phase counters:

- **`phase_diff`** (16-bit): Measures timing of forward trigger signal (lvdsin_trig)
- **`phase_diff_b`** (16-bit): Measures timing of backward trigger signal (lvdsin_trig_b)

Read via commands in `command_processor.v`:
- **Command 2, Subcommand 12**: Returns `phase_diff`
- **Command 2, Subcommand 13**: Returns `phase_diff_b`

The firmware returns the phase measurement in bytes `res[0]` and `res[1]`. Consistent values (res[0] == res[1]) indicate stable phase alignment.

### Trigger Types

- **Type 3**: External trigger mode - board waits for LVDS trigger input
- **Type 30**: External trigger **echo** mode - enables phase measurement during calibration

## Software Components

### Key Functions

**`calibrate_lvds_delays()`** (`hardware_controller.py:571-658`)
- Validates exactly one self-triggering board
- Sets up calibration state and enables echo mode for first board
- Returns immediately (non-blocking)
- Calibration proceeds asynchronously in event loop

**`_get_predata(board_idx)`** (`hardware_controller.py:451-557`)
- Called during each acquisition cycle
- Contains echo delay measurement logic
- Progresses through calibration boards sequentially
- Handles timeout and completion

**`_finish_lvds_calibration()`** (`hardware_controller.py:630-661`)
- Applies ~16ns board offset correction
- Saves calibration set indexed by trigger source board
- Updates firmware trigger positions

**`restore_lvds_calibration(trigger_board)`** (`hardware_controller.py:663-692`)
- Restores previously saved calibration
- Called automatically when switching trigger sources
- Updates firmware if calibration exists

## Calibration Algorithm

### Two Boards Example

**Configuration**: Board 0 generates triggers → Board 1 receives triggers

```
Board 0 (self-triggering)     Board 1 (ext trigger)
doexttrig[0] = False           doexttrig[1] = True
triggertype = 0-2              triggertype = 30 (during calibration)
```

**Process:**

1. User selects **Calibration → Board LVDS delays**
2. `calibrate_lvds_delays()` validates and enables echo mode for Board 1
3. During acquisition, `_get_predata(0)` on Board 0:
   - Detects `doexttrigecho[1] == True`
   - Since Board 1 > Board 0: **Forward echo**
   - Sends Command `[2, 12]` to read `phase_diff`
4. Firmware returns phase measurement in `res[0]` and `res[1]`
5. Calculate delay:
   ```python
   if res[0] == res[1]:  # Phase is stable
       lvdstrigdelay = (res[0] + res[1]) / 4  # LVDS cycles
   ```
6. Stability check - if consistent with last measurement:
   - Store `lvdstrigdelay[1]`
   - Disable echo mode
   - Apply ~16ns offset: `lvdstrigdelay[1] -= 16/2.5`
7. Save calibration set for trigger Board 0
8. Update firmware trigger positions

### Three Boards Example

**Configuration**: Board 1 generates triggers → Boards 0 and 2 receive triggers

```
Board 0 (ext trig)    Board 1 (self-trig)    Board 2 (ext trig)
doexttrig[0] = True   doexttrig[1] = False   doexttrig[2] = True
```

**Calibration sequence:**

1. **Board 0 (Backward echo)**:
   - Enable `doexttrigecho[0] = True`
   - Board 1 sends Command `[2, 13]` to read `phase_diff_b`
   - Calculate: `lvdstrigdelay = (res[0] + res[1]) / 4`
   - **Apply backward tuning**: `lvdstrigdelay += round(lvdstrigdelay / 11.5, 1)`
   - Apply offset correction

2. **Board 2 (Forward echo)**:
   - Enable `doexttrigecho[2] = True`
   - Board 1 sends Command `[2, 12]` to read `phase_diff`
   - Calculate: `lvdstrigdelay = (res[0] + res[1]) / 4`
   - No backward tuning needed
   - Apply offset correction

3. Save both delays under trigger source Board 1

### Multi-Hop Delays

The echo signal physically travels through all intermediate boards:

**Example**: 4 boards with Board 1 as trigger source

```
Board 0 ← Board 1 → Board 2 → Board 3
```

- **Board 0 delay**: 1-hop backward through cable
- **Board 2 delay**: 1-hop forward through cable
- **Board 3 delay**: 2-hop forward (Board 1 → Board 2 → Board 3)
  - Includes Board 2 internal routing + both cables
  - Approximately 2× single-hop delay

The `phase_diff` measurement captures the **total multi-hop echo time**.

## Board Offset Correction

A ~16ns (~6.4 LVDS cycles) correction is applied to all ext-trig boards:

```python
for board in range(num_board):
    if doexttrig[board]:
        lvdstrigdelay[board] -= 16 / 2.5  # 16ns / 2.5ns per cycle
```

This compensates for systematic timing offsets in the trigger path.

## Physical Interpretation

Delays are measured in **LVDS clock cycles** (400 MHz = 2.5 ns/cycle):

| LVDS Cycles | Time (ns) | Samples @ 3.2 GHz |
|-------------|-----------|-------------------|
| 1.0         | 2.5       | 8                 |
| 4.5         | 11.25     | 36                |
| 6.4         | 16.0      | 51                |
| 10.0        | 25.0      | 80                |

**Conversion factor**: 8 samples per LVDS cycle (3.2 GHz / 400 MHz = 8)

## Safety Features

### Single Self-Triggering Board

The system enforces **exactly one self-triggering board**:

```python
# In rising_falling_changed() - main_window.py:3504-3514
if not is_other_boards and not is_external_sma:
    for board_idx in range(num_board):
        if board_idx != active_board and not doexttrig[board_idx]:
            doexttrig[board_idx] = True  # Force to ext trigger
            set_exttrig(board_idx, True)

    # Restore saved calibration for this trigger board
    restore_lvds_calibration(active_board)
```

When you set a board to channel-based triggering, all other boards are automatically switched to external trigger mode.

### PLL Reset Prevention

Automatic PLL resets are blocked during calibration:

```python
# In update_plot_event() - main_window.py:1132-1134
elif s.lvds_calibration_active:
    # Don't trigger PLL resets during LVDS calibration
    pass
```

This prevents interruption of the calibration process by transient clock issues.

### External Clock Lock Verification

After PLL reset completes, all ext-trig boards are verified to be locked to external clock:

```python
# In adjustclocks() - hardware_controller.py:209-212
if all(x == -10 for x in plljustreset):
    ensure_exttrig_boards_locked()  # Check sequentially board 0→N
```

## Timing Behavior

### Calibration Duration

- **Per board**: 5-50 acquisition cycles (typically ~10 cycles)
- **4 boards**: ~30-150 total cycles
- **At 1 kHz trigger rate**: 30-150 ms total

### Firmware Update Timing

Firmware trigger positions are updated:
1. After LVDS calibration completes
2. When downsample factor changes
3. When trigger mode changes

Call to `send_trigger_info()` updates the hardware immediately.

## Troubleshooting

### Calibration Times Out

**Symptoms**: "Board X: Calibration timed out after 50 cycles"

**Causes**:
- Phase measurements not stabilizing (res[0] != res[1])
- LVDS clock phase misalignment
- Cable connection issues

**Solutions**:
- Check LVDS cable connections
- Run PLL calibration first
- Verify external clock lock on all boards

### Waveforms Not Aligned After Calibration

**Check**:
1. Calibration completed successfully (no timeout messages)
2. Trigger threshold is stable (not changing during measurement)
3. Firmware trigger positions updated (check console for "Updating firmware trigger positions")
4. Downsample factor hasn't changed since calibration

**Debug**:
- Re-run calibration
- Check `lvdstrigdelay` values in state
- Verify both firmware and software compensation are active

### Switching Trigger Sources

When switching which board generates triggers:

1. Select the new trigger board in UI
2. Set it to channel-based trigger (Rising/Falling Ch0 or Ch1)
3. System automatically:
   - Sets all other boards to external trigger
   - Restores saved calibration for that trigger board (if exists)
   - **Starts automatic calibration** if no saved calibration exists (requires acquisition running)
   - Updates firmware trigger positions

You can also manually trigger calibration via **Calibration → Board LVDS delays** menu.

## Implementation Details

### Conversion Constants

```python
LVDS_FREQ = 400e6          # 400 MHz LVDS clock
ADC_FREQ = 3.2e9           # 3.2 GHz ADC sampling
SAMPLES_PER_LVDS = 8       # ADC_FREQ / LVDS_FREQ
NS_PER_LVDS = 2.5          # 1/LVDS_FREQ * 1e9
```

### Firmware Trigger Position Quantization

Firmware operates in **40-sample windows**:
```python
triggerpos_increment = int(8 * lvdstrigdelay / 40 / downsamplefactor / factor)
actual_samples = triggerpos_increment * 40 * factor
```

Residual correction in software ensures sample-level precision.

### Backward Echo Tuning Factor

The `11.5` tuning factor for backward echo:
```python
if echoboard < board_idx:  # Backward direction
    lvdstrigdelay += round(lvdstrigdelay / 11.5, 1)
```

This empirical correction accounts for asymmetries in the backward signal path timing. The exact value may need adjustment for different hardware configurations.

## API Reference

### State Variables

```python
state.doexttrig[board]              # True if board uses external trigger
state.doexttrigecho[board]          # True if board is in echo mode (calibration)
state.lvdstrigdelay[board]          # Measured delay in LVDS cycles
state.lvds_calibration_active       # True during active calibration
state.lvds_calibration_sets[trig_board][board]  # Saved delays per trigger source
```

### Functions

```python
controller.calibrate_lvds_delays()
# Start LVDS calibration (non-blocking)
# Returns: (success: bool, message: str)

controller.restore_lvds_calibration(trigger_board)
# Restore saved calibration for trigger_board
# Returns: bool (True if calibration restored)

controller.send_trigger_info(board)
# Update firmware trigger position for board
# Includes LVDS delay compensation

controller.ensure_boards_locked()
# Verify all ext-trig boards locked to external clock
# Called after PLL reset
```

## Version History

- **v32**: Event-driven calibration, firmware/software split compensation, saved calibrations per trigger board, automatic calibration on startup and when switching trigger sources, fixed board processing order for distcorr stabilization
- **v31**: Menu-based calibration only (removed automatic calibration)
- **v30**: Multi-board systematic calibration
- **v29**: Initial doexttrigecho implementation
