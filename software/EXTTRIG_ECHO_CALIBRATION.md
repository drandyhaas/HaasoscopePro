# External Trigger Echo Delay Calibration

## Overview

The Haasoscope Pro supports daisy-chaining multiple boards via LVDS connections. When multiple boards are synchronized, one board can generate triggers that propagate to other boards through the LVDS chain. However, LVDS signal propagation introduces delays that vary based on cable length and board position in the chain.

The **doexttrigecho** mechanism automatically measures and compensates for these trigger propagation delays, ensuring that trigger timing is accurately known at each board.

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
Enables/disables external trigger mode for a board. When enabling:
- Disables echo mode on all other boards
- Enables echo mode on the specified board
- This marks which board is the trigger source

#### `pllreset(board_idx)`
During PLL calibration after reset:
- If `num_board > 1` and `doexttrig[board_idx]` is True
- Sets `doexttrigecho[board_idx] = True`
- This initiates delay calibration during clock phase calibration

#### `_get_predata(board_idx)`
Called during data acquisition for each board. Contains the calibration logic (lines 441-484).

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
doexttrigecho[0] = False       doexttrigecho[1] = True  (during calibration)
triggertype = 0-2              triggertype = 30 (echo mode)
```

#### Calibration Process

1. **Board 1 is in echo mode** during PLL reset/calibration
2. **Board 0** (non-ext-trig board) runs `_get_predata(0)`:
   - Detects that `doexttrigecho[1] == True`
   - Echoboard = 1 (the board generating triggers)
   - Since echoboard (1) > board (0): **Forward echo**
   - Sends Command `[2, 12, ...]` to read `phase_diff`

3. **Firmware on Board 0** returns phase measurement:
   - `res[0]` and `res[1]` contain phase counts
   - These measure the delay of trigger signal traveling from Board 1 to Board 0

4. **Software calculates delay**:
   ```python
   if res[0] == res[1]:  # Phase is stable
       lvdstrigdelay = (res[0] + res[1]) / 4  # Convert to LVDS clock cycles
       # No adjustment needed for forward echo
   ```

5. **Stability check**:
   - If `lvdstrigdelay == lastlvdstrigdelay[1]`: measurement is stable
   - Store final value: `state.lvdstrigdelay[1] = lvdstrigdelay`
   - Disable echo mode: `state.doexttrigecho[1] = False`
   - Print: `"lvdstrigdelay from board 0 to echoboard 1 is X.X"`

6. **If phase unstable** (res[0] != res[1]):
   - Adjust clock phases on Board 0 to align signals:
   ```python
   self.dophase(0, plloutnum=0, updown=1, quiet=True)  # Adjust clklvds
   self.dophase(0, plloutnum=1, updown=1, quiet=True)  # Adjust clklvdsout
   ```
   - Retry on next acquisition cycle

#### Physical Interpretation

The delay represents LVDS cable propagation time:
- Measured in LVDS clock cycles (typically 400 MHz = 2.5 ns per cycle)
- Example: `lvdstrigdelay = 4.5` means 11.25 ns propagation delay
- Used to correct trigger timestamp when processing data from Board 0

### Three Boards (N=3)

**Scenario**: Board 1 generates triggers → Board 0 and Board 2 receive triggers

#### Configuration
```
Board 0 (ext trigger)          Board 1 (self-triggering)      Board 2 (ext trigger)
doexttrig[0] = True            doexttrig[1] = False            doexttrig[2] = True
doexttrigecho[0] = True*       doexttrigecho[1] = False        doexttrigecho[2] = True*
triggertype = 30*              triggertype = 0-2               triggertype = 30*
```
*During calibration only

#### Calibration Process

Board 1 (self-triggering) generates triggers that propagate both directions:
- **Backward** to Board 0 via lvdsout_trig_b
- **Forward** to Board 2 via lvdsout_trig

##### Calibration on Board 0 (Backward Echo)

Board 0 is ext-trig, Board 1 is echoing.

When **Board 1** runs `_get_predata(1)`:
- Detects `doexttrigecho[0] == True`
- Echoboard = 0
- Since echoboard (0) < board (1): **Backward echo**
- Sends Command `[2, 13, ...]` to read `phase_diff_b`

Delay calculation:
```python
if res[0] == res[1]:
    lvdstrigdelay = (res[0] + res[1]) / 4
    # Backward echo needs tuning adjustment - this has to be tuned a little experimentally
    lvdstrigdelay += round(lvdstrigdelay / 11.5, 1)
```

The tuning factor (`/11.5`) accounts for asymmetries in backward signal path timing. This value is empirically derived and may need adjustment for different hardware revisions or cable types.

##### Calibration on Board 2 (Forward Echo)

Board 2 is ext-trig, Board 1 is echoing.

When **Board 1** runs `_get_predata(1)`:
- Detects `doexttrigecho[2] == True`
- Echoboard = 2
- Since echoboard (2) > board (1): **Forward echo**
- Sends Command `[2, 12, ...]` to read `phase_diff`

Delay calculation:
```python
if res[0] == res[1]:
    lvdstrigdelay = (res[0] + res[1]) / 4
    # No tuning factor for forward echo
```

#### Order of Calibration

Calibration happens opportunistically during normal acquisition:
- Both Board 0 and Board 2 start in echo mode after PLL reset
- Board 1 measures delays to both neighbors
- Each measurement completes independently when stable
- Echo mode disabled for each board after successful measurement

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

#### Calibration Pattern

**For each non-self-triggering board i where i ≠ k:**

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
5. Stores delay and disables echo mode for that board
6. Next board's echo mode is enabled (if needed)

#### Propagation Distance

The measured delay increases with distance from the self-triggering board:
- Adjacent boards: ~1-5 LVDS cycles (2.5-12.5 ns)
- 2 hops away: ~2-10 LVDS cycles (5-25 ns)
- 3 hops away: ~3-15 LVDS cycles (7.5-37.5 ns)
- N hops away: scales approximately linearly with cable length

#### Multi-Hop Delays

**Important**: The phase_diff measurement reflects the **direct cable delay** between adjacent boards, not the total trigger propagation time.

For example, with 4 boards where Board 1 is self-triggering:
```
Board 0 <---> Board 1 <---> Board 2 <---> Board 3
              (SELF)
```

- `lvdstrigdelay[0]`: Delay from Board 1 to Board 0 (backward, 1 hop)
- `lvdstrigdelay[2]`: Delay from Board 1 to Board 2 (forward, 1 hop)
- `lvdstrigdelay[3]`: Delay from Board 1 to Board 3 (forward, but measures 1 hop only!)

**Note**: For non-adjacent boards, the firmware can only measure the delay to the **next board in chain**, not the total end-to-end delay. This is a hardware limitation of the current phase detector implementation.

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

Calibration occurs in two scenarios:

### 1. During PLL Reset

When `pllreset(board_idx)` is called:
- If multi-board system and board uses external trigger
- Sets `doexttrigecho[board_idx] = True`
- Calibration runs during the clock phase calibration sequence
- Typically completes within 10-20 acquisition cycles

**Important**: Phase alignment adjustments (via `dophase()`) only occur **after** PLL calibration completes (when `all(plljustreset <= -10)`). This prevents the trigger clock phase adjustments from interfering with the ADC sampling clock phase calibration, which could cause bad signal capture and incorrect timing measurements.

### 2. Manual Trigger Setup

When user enables external trigger on a board:
- `set_exttrig(board_idx, True)` is called
- Echo mode is enabled immediately
- Calibration starts on next acquisition cycle
- Runs continuously until stable measurement obtained

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
