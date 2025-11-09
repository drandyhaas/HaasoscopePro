# External Trigger Echo Delay Calibration

## Overview

The Haasoscope Pro supports daisy-chaining multiple boards via LVDS connections. When multiple boards are synchronized, one board can generate triggers that propagate to other boards through the LVDS chain. However, LVDS signal propagation introduces delays that vary based on cable length and board position in the chain.

The **doexttrigecho** mechanism automatically measures and compensates for these trigger propagation delays, ensuring that trigger timing is accurately known at each board.

## Quick Start

**To calibrate delays for a multi-board system:**

1. Configure one board as the trigger source (disable external trigger)
2. Configure all other boards to use external trigger
3. Go to **Calibration → Board LVDS delays** menu
4. Wait for calibration to complete (~5-50 acquisition cycles per board)
5. Results are displayed showing measured delays for each board

**Note**: This is the only way to calibrate LVDS delays. The `calibrate_lvds_delays()` function systematically measures all boards and validates the configuration.

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
- **Backward**: From higher-indexed board to lower-indexed board

## Firmware Components

### Phase Difference Registers

The firmware tracks trigger signal timing using phase counters connected to the LVDS trigger inputs:

- **`phase_diff`** (16-bit): Measures timing of forward trigger signal (lvdsin_trig)
- **`phase_diff_b`** (16-bit): Measures timing of backward trigger signal (lvdsin_trig_b)

These are read via:
- **Command 2, Subcommand 12**: Returns `phase_diff` as a 32-bit value
- **Command 2, Subcommand 13**: Returns `phase_diff_b` as a 32-bit value

The firmware returns the phase measurement in bytes `res[0]` and `res[1]` of the 4-byte response. Consistent values (res[0] == res[1]) indicate stable phase alignment.

### Trigger Types

When a board receives Command 1 (set trigger and get status), the trigger type determines behavior:

- **Type 3**: External trigger mode - board waits for LVDS trigger input
- **Type 30**: External trigger **echo** mode - board uses external trigger AND measures phase timing

During calibration, the echoing board uses Type 30 to enable phase measurement.

### Command Processor

Located in `command_processor.v`, lines 303-304:

```verilog
12: o_tdata <= {16'd0, phase_diff_sync};
13: o_tdata <= {16'd0, phase_diff_b_sync};
```

These subcommands of Command 2 provide the raw phase difference measurements from the triggerer module.

## Software Components

### State Variables

In `scope_state.py`:

```python
self.doexttrigecho = [False] * self.num_board  # Which board is echoing triggers
self.lvdstrigdelay = [0] * self.num_board      # Measured delay for each board
self.lastlvdstrigdelay = [0] * self.num_board  # Previous measurement for stability check
```

### Key Functions

In `hardware_controller.py`:

#### `set_exttrig(board_idx, is_ext)`
Enables/disables external trigger mode for a board. This sets the board's trigger configuration but does not trigger delay calibration. Calibration must be run separately via `calibrate_lvds_delays()`.

#### `calibrate_lvds_delays()`
The main calibration function (lines 539-625). Systematically measures all boards in sequence.

#### `_get_predata(board_idx)`
Called during data acquisition for each board. Contains the echo delay measurement logic (lines 441-489) that is used by `calibrate_lvds_delays()`.

## Calibration Algorithm

### Single Board (N=1)

**No calibration needed.**

- Only one board exists
- No LVDS trigger propagation
- `doexttrigecho[0] = False`
- `lvdstrigdelay[0] = 0`

### Two Boards (N=2)

**Scenario**: Board 0 generates triggers → Board 1 receives triggers

#### Configuration
```
Board 0 (self-triggering)     Board 1 (ext trigger)
doexttrig[0] = False           doexttrig[1] = True
triggertype = 0-2              triggertype = 3 (ext trig)
```

#### Calibration Process

User selects **Calibration → Board LVDS delays** menu:

1. **`calibrate_lvds_delays()` validates**:
   - Board 0 is self-triggering ✓
   - Board 1 needs calibration

2. **Enable echo mode for Board 1**: `doexttrigecho[1] = True`, sets `triggertype = 30`

3. **Board 0** runs acquisition and calls `_get_predata(0)`:
   - Detects that `doexttrigecho[1] == True`
   - Echoboard = 1
   - Since echoboard (1) > board (0): **Forward echo**
   - Sends Command `[2, 12, ...]` to read `phase_diff`

4. **Firmware on Board 0** returns phase measurement:
   - `res[0]` and `res[1]` contain phase counts
   - These measure the delay of trigger signal traveling from Board 1 to Board 0

5. **Software calculates delay**:
   ```python
   if res[0] == res[1]:  # Phase is stable
       lvdstrigdelay = (res[0] + res[1]) / 4  # Convert to LVDS clock cycles
       # No adjustment needed for forward echo
   ```

6. **Stability check**:
   - If `lvdstrigdelay == lastlvdstrigdelay[1]`: measurement is stable
   - Store final value: `state.lvdstrigdelay[1] = lvdstrigdelay`
   - Disable echo mode: `state.doexttrigecho[1] = False`
   - Print: `"lvdstrigdelay from board 0 to echoboard 1 is X.X"`

7. **If phase unstable** (res[0] != res[1]):
   - Only after PLL calibration completes, adjust clock phases on Board 0:
   ```python
   if all(item <= -10 for item in state.plljustreset):
       self.dophase(0, plloutnum=0, updown=1, quiet=True)  # Adjust clklvds
       self.dophase(0, plloutnum=1, updown=1, quiet=True)  # Adjust clklvdsout
   ```
   - Retry on next acquisition cycle

8. **Calibration complete**: Function returns with result

#### Physical Interpretation

The delay represents LVDS cable propagation time:
- Measured in LVDS clock cycles (typically 400 MHz = 2.5 ns per cycle)
- Example: `lvdstrigdelay = 4.5` means 11.25 ns propagation delay
- Used to correct trigger timestamp when processing data from Board 1

### Three Boards (N=3)

**Scenario**: Board 1 generates triggers → Board 0 and Board 2 receive triggers

#### Configuration
```
Board 0 (ext trigger)          Board 1 (self-triggering)      Board 2 (ext trigger)
doexttrig[0] = True            doexttrig[1] = False            doexttrig[2] = True
triggertype = 3                triggertype = 0-2               triggertype = 3
```

#### Calibration Process

User selects **Calibration → Board LVDS delays** menu:

1. **`calibrate_lvds_delays()` validates**:
   - Board 1 is self-triggering ✓
   - Boards 0 and 2 need calibration

2. **Calibrate Board 0 (Backward Echo)**:
   - Enable echo mode: `doexttrigecho[0] = True`, sets `triggertype = 30`
   - Board 1 runs `_get_predata(1)`:
     * Detects `doexttrigecho[0] == True`
     * Echoboard = 0
     * Since echoboard (0) < board (1): **Backward echo**
     * Sends Command `[2, 13, ...]` to read `phase_diff_b`
   - Delay calculation:
     ```python
     if res[0] == res[1]:
         lvdstrigdelay = (res[0] + res[1]) / 4
         # Backward echo needs tuning adjustment - this has to be tuned a little experimentally
         lvdstrigdelay += round(lvdstrigdelay / 11.5, 1)
     ```
   - Once stable, store and disable echo mode
   - **Note**: The tuning factor (`/11.5`) accounts for asymmetries in backward signal path timing

3. **Calibrate Board 2 (Forward Echo)**:
   - Enable echo mode: `doexttrigecho[2] = True`, sets `triggertype = 30`
   - Board 1 runs `_get_predata(1)`:
     * Detects `doexttrigecho[2] == True`
     * Echoboard = 2
     * Since echoboard (2) > board (1): **Forward echo**
     * Sends Command `[2, 12, ...]` to read `phase_diff`
   - Delay calculation:
     ```python
     if res[0] == res[1]:
         lvdstrigdelay = (res[0] + res[1]) / 4
         # No tuning factor for forward echo
     ```
   - Once stable, store and disable echo mode

4. **Calibration complete**: Function returns with both delays

### N Boards (General Case)

#### Principles

1. **Single Echo Source**: Only one board has `doexttrigecho[i] = True` at a time
2. **Self-Triggering Board**: The board with `doexttrig[i] = False` generates triggers
3. **All Others Use Ext Trig**: All other boards have `doexttrig[i] = True`

#### Topology

```
Board 0 <---> Board 1 <---> ... <---> Board k <---> ... <---> Board N-1
(ext trig)    (ext trig)             (SELF-TRIG)              (ext trig)
```

Board k is the self-triggering board that generates triggers for all others.

#### Systematic Calibration (Recommended Method)

When `calibrate_lvds_delays()` is called from the menu:

**Step 1: Validation**
```python
# Find exactly one self-triggering board
self_trig_boards = [i for i in range(num_board) if not doexttrig[i]]
assert len(self_trig_boards) == 1, "Must have exactly one self-triggering board"
trigger_board = self_trig_boards[0]

# Get list of boards to calibrate
ext_trig_boards = [i for i in range(num_board) if doexttrig[i]]
```

**Step 2: Iterate Through Each Board**
```python
for board_idx in ext_trig_boards:
    # Enable echo mode for this board only
    doexttrigecho[board_idx] = True
    lastlvdstrigdelay[board_idx] = -999  # Force fresh measurement

    # Run acquisition cycles until measurement is stable
    cycles = 0
    while doexttrigecho[board_idx] and cycles < 50:
        # _get_channels(trigger_board) sends trigger command
        # _get_predata(trigger_board) measures delay and auto-disables echo when stable
        if _get_channels(trigger_board):
            _get_predata(trigger_board)
        cycles += 1

    # Echo mode is now disabled, delay is stored in lvdstrigdelay[board_idx]
    print(f"Board {board_idx}: {lvdstrigdelay[board_idx]:.2f} cycles")
```

**Step 3: Measurement Details**

The self-triggering board k runs `_get_predata(k)` and:

1. Detects which board is in echo mode (should only be one)
2. Determines direction:
   - If echoboard > k: **Forward echo** → Use Command 2,12 (phase_diff)
   - If echoboard < k: **Backward echo** → Use Command 2,13 (phase_diff_b)

3. Measures delay:
   ```python
   lvdstrigdelay = (res[0] + res[1]) / 4
   if echoboard < k:
       # Backward echo needs tuning adjustment - this has to be tuned a little experimentally
       lvdstrigdelay += round(lvdstrigdelay / 11.5, 1)
   ```

4. Waits for stable measurement (two consecutive identical values)
5. Stores delay and disables echo mode: `doexttrigecho[echoboard] = False`
6. Returns to Step 2 for next board

#### Example: 4 Boards, Board 1 Self-Triggering

```
Initial config:
  Board 0: ext trig, delay=unknown
  Board 1: SELF-TRIG
  Board 2: ext trig, delay=unknown
  Board 3: ext trig, delay=unknown

Calibration sequence:
  1. Enable echo on Board 0 → measure echo return (1 hop backward) → disable echo
  2. Enable echo on Board 2 → measure echo return (1 hop backward) → disable echo
  3. Enable echo on Board 3 → measure echo return (2 hops backward) → disable echo

Final state:
  Board 0: ext trig, delay=4.2 (backward, 1 hop)
  Board 1: SELF-TRIG
  Board 2: ext trig, delay=3.8 (backward, 1 hop)
  Board 3: ext trig, delay=7.5 (backward, 2 hops - total echo path)
```

**Note**: Board 3's delay of 7.5 reflects the **total 2-hop echo path** (Board 3 → Board 2 → Board 1), which is roughly double the single-hop delays of Boards 0 and 2.

#### Propagation Distance and Multi-Hop Delays

The measured delay reflects the **total echo propagation path** from the echo board back to the self-triggering board, including all intermediate boards.

For example, with 4 boards where Board 1 is self-triggering:
```
Board 0 <---> Board 1 <---> Board 2 <---> Board 3
              (SELF)
```

**Measured delays:**
- `lvdstrigdelay[0]`: Board 0 → Board 1 (backward, 1 hop)
  - Typical: ~3-5 LVDS cycles (7.5-12.5 ns)
- `lvdstrigdelay[2]`: Board 2 → Board 1 (backward through Board 2's internal routing)
  - Typical: ~3-5 LVDS cycles (7.5-12.5 ns)
- `lvdstrigdelay[3]`: Board 3 → Board 2 → Board 1 (backward, 2 hops)
  - Typical: ~6-10 LVDS cycles (15-25 ns)
  - This is the **total 2-hop delay**, not just the last hop!

**Signal path for Board 3 calibration:**
1. Board 1 generates trigger
2. Trigger propagates forward: Board 1 → Board 2 → Board 3
3. Board 3 (in echo mode) sends echo back via lvdsout_trig_b
4. Echo propagates backward: Board 3 → Board 2 → Board 1
5. Board 1's phase_diff measures the total echo return time

The echo signal physically travels through all intermediate boards, so the measurement includes:
- Cable delays (both hops)
- Internal FPGA routing delays (Board 2)
- LVDS driver/receiver delays

**Key insight**: Delays scale roughly linearly with number of hops, but each hop adds cable delay + board internal delay (typically 2-5 ns per hop).

## Delay Compensation in Data Processing

Once calibrated, the delays are used in `data_processor.py` and `hardware_controller.py`:

### Trigger Position Adjustment

From `hardware_controller.py:223`:
```python
triggerpos += int(8 * state.lvdstrigdelay[board_idx] / 40 / state.downsamplefactor / factor)
```

This adjusts the trigger position in the captured waveform to account for the LVDS propagation delay.

### Phase Correction

From `data_processor.py:243`:
```python
8 * state.lvdstrigdelay[board_idx] / state.downsamplefactor / factor) % 40
```

Applied to align waveform samples across boards accounting for trigger arrival time differences.

## Calibration Timing

Calibration must be triggered explicitly by the user via the **Calibration → Board LVDS delays** menu:

```python
controller.calibrate_lvds_delays()
```

This function:
1. **Validates configuration**: Exactly one board must be self-triggering, all others must use external trigger
2. **Systematically iterates** through all external trigger boards
3. **Enables echo mode** for one board at a time: `doexttrigecho[board_idx] = True`
4. **Runs acquisition cycles** until stable measurement obtained
5. **Disables echo mode** once delay is locked in
6. **Moves to next board** and repeats

**Characteristics**:
- Works reliably for any number of boards (N ≥ 2)
- Can be re-run at any time to verify/update delays
- Validates configuration before starting
- Provides clear progress and results
- Maximum 50 cycles per board (typically completes in 5-10 cycles)
- Phase alignment adjustments only occur after PLL calibration completes (when `all(plljustreset <= -10)`)

**Important**: The PLL calibration guard prevents trigger clock phase adjustments from interfering with ADC sampling clock phase calibration, which could cause bad signal capture and incorrect timing measurements.

## Error Handling

### Phase Instability

If `res[0] != res[1]`:
- Indicates clock phase misalignment between boards
- **Only after PLL calibration completes** (`all(plljustreset <= -10)`), system automatically adjusts PLL phases:
  - `dophase(board, plloutnum=0, updown=1)` - Adjust data clock
  - `dophase(board, plloutnum=1, updown=1)` - Adjust trigger clock
- This guard prevents interference with ADC sampling phase calibration
- If PLL calibration is still running, phase adjustment is deferred to next cycle
- Retries measurement on next cycle

### Measurement Inconsistency

If `lvdstrigdelay != lastlvdstrigdelay`:
- Current measurement doesn't match previous
- Possible causes: noise, thermal drift, cable movement
- System continues measuring until two consecutive identical values
- Once stable, delay is locked in and echo mode disabled

### Assertion Failures

The code includes safety checks:
- `assert doexttrigecho.count(True) == 1`: Only one echo source
- `assert echoboard != board_idx`: Not echoing from self
- These catch configuration errors during development

## Performance Considerations

### Calibration Time

- Single measurement: 1 acquisition cycle (~10-100 ms depending on sample depth)
- Stability requirement: 2 consecutive identical measurements
- Typical total time: 20-200 ms per board
- Phase adjustment adds 1-5 extra cycles if needed

### Accuracy

- Phase counters: 16-bit resolution
- LVDS clock: 400 MHz (2.5 ns period)
- Theoretical resolution: 2.5 ns / 65536 ≈ 38 femtoseconds
- Practical accuracy: ±1 LVDS cycle (±2.5 ns) due to jitter and measurement noise

### Stability

- Delay is measured during every acquisition while in echo mode
- Once stable, echo mode is disabled and delay is fixed
- Remains valid until:
  - PLL reset occurs
  - External trigger configuration changes
  - Cables are disconnected/reconnected

## Debugging

### Verbose Output

When calibration completes, the system prints:
```
lvdstrigdelay from board X to echoboard Y is Z.Z
```

This confirms successful calibration.

### Manual Phase Adjustment

The `dophase()` function can be called manually for debugging:
```python
controller.dophase(board_idx, plloutnum=0, updown=1, quiet=False)
```

This prints: `"Adjusted phase up for PLL0 output 0 on board X"`

### Checking Current State

Monitor these state variables:
```python
state.doexttrigecho      # Which board is currently echoing
state.lvdstrigdelay      # Measured delays for each board
state.lastlvdstrigdelay  # Previous measurements for comparison
```

## Limitations

1. **Single Echo Source**: Only one board can echo at a time
2. **Adjacent Measurement Only**: Phase detectors measure next-hop delay, not total propagation
3. **Calibration Required**: Must run after PLL reset or trigger config change
4. **No Real-Time Update**: Delay fixed after calibration; doesn't track dynamic changes
5. **Backward Tuning Factor**: The `/11.5` factor is empirically derived and may need adjustment for different hardware revisions or cable types
6. **PLL Calibration Dependency**: Phase alignment adjustments only occur after PLL calibration completes to avoid interfering with ADC sampling phase calibration

## Future Enhancements

Potential improvements:
- **Multi-hop delay accumulation**: Calculate total delays for non-adjacent boards
- **Continuous calibration**: Monitor and update delays during acquisition
- **Automatic tuning factor**: Self-calibrate the backward echo adjustment
- **Temperature compensation**: Adjust delays based on board temperature
- **Cable length estimation**: Report physical cable length from delay measurements
