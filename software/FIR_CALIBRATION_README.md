# FIR Frequency Response Calibration

## Overview

This feature corrects for the non-flat frequency response of the Haasoscope Pro hardware by applying a calibrated FIR (Finite Impulse Response) filter to measured waveforms. The calibration is based on a known 10 MHz square wave input signal.

## How It Works

1. **Calibration Signal**: Uses a 10 MHz square wave as reference
2. **Measurement**: Captures and averages 50 waveforms to reduce noise
3. **Analysis**: Computes frequency response H(f) = FFT(measured) / FFT(ideal)
4. **Filter Design**: Creates a 64-tap FIR filter to invert the frequency response
5. **Application**: Applies the filter in real-time using zero-phase filtering (same as LPF)

## Pipeline Integration

The FIR correction is applied in the waveform processing pipeline at this location:

```
Hardware → DataProcessor (unpack, scale, LPF)
    → Board Trigger Stabilizer
    → PlotManager → Extra Trigger Stabilizer
    → Time Skew Correction
    → **FIR Frequency Response Correction** ← NEW
    → Display
```

This ensures corrections are applied after trigger stabilization but before display.

## Usage Instructions

### Operating Modes: Normal, Oversampling, and Interleaved

The FIR calibration system automatically detects the current operating mode and applies the appropriate calibration:

- **Normal Mode**: Single calibration applies to all boards/channels at base sample rate (3.2 GHz)

- **Oversampling Mode** (not interleaved): Board pair (N and N+1) are calibrated separately at base sample rate
  - Determined by checking `state.dooversample[activeboard]`
  - Board N and Board N+1 each get independent FIR coefficients
  - Hardware duplicates the 10 MHz signal to both boards automatically
  - Both boards are calibrated simultaneously from the same capture session
  - Corrections are automatically applied per-board during acquisition

- **Interleaved Oversampling Mode** (both oversampling AND interleaving enabled): Interleaved waveform calibrated at 2x sample rate (6.4 GHz)
  - Determined by checking both `state.dooversample[activeboard]` and `state.dointerleaved[activeboard]`
  - Single calibration for the interleaved waveform combining both boards
  - Sample rate is 2x the base rate (6.4 GHz instead of 3.2 GHz)
  - Captures both boards simultaneously and interleaves them during calibration
  - Hardware automatically duplicates the 10 MHz signal to both boards
  - Correction is applied to the already-interleaved waveform during plotting

### 1. Connect Calibration Signal
- Connect a **10 MHz square wave** to the input
- **Normal Mode**: Signal goes to Board 0, Channel 0
- **Oversampling Mode** (not interleaved): Hardware automatically duplicates signal to both Board N and Board N+1
  - Both boards are calibrated separately but simultaneously from the same signal
  - No need to move the signal between boards
- **Interleaved Mode**: Hardware automatically duplicates signal to both Board N and Board N+1
  - The interleaved waveform at 6.4 GHz is calibrated as a single entity
  - Both boards contribute to the same calibration
- The signal should have good amplitude and clean edges
- Ensure the scope is triggered and acquiring stable waveforms

### 2. Set Maximum Sample Rate
- **IMPORTANT**: Set **Downsample to 0** (maximum sample rate) before calibration
- Calibration must be performed at maximum sample rate for best results
- After calibration, corrections can be used at downsampled rates (though with reduced accuracy)
- **Depth**: The software automatically increases depth to 1000 samples during calibration for optimal frequency resolution
  - Your current depth setting is temporarily changed and then restored
  - This gives the finest possible frequency resolution (Δf = sample_rate / 1000)
  - After calibration, you can use any depth - the FIR filter works identically at all depths

### 3. Capture Calibration
- Start acquisition (unpause the scope)
- Go to menu: **Calibration → Measure 10 MHz square FIR**
- If downsample > 0, you'll get a warning to set it to 0 first
- The software will:
  - Capture 50 waveforms (takes ~1-2 seconds)
  - Average them to reduce noise
  - Compute the frequency response
  - Design the 64-tap FIR correction filter
  - Display a success message with improvement in dB

### 4. Apply Correction
- The correction is automatically enabled after successful calibration
- You can toggle it on/off using: **Calibration → Apply FIR corrections** (checkbox)
- The correction applies to **all channels** (not per-channel)

### 5. Verify Results
- View the corrected waveforms
- The 10 MHz square wave should now have better-defined edges and harmonics
- You can toggle the correction on/off to see the difference

### 6. Save/Load Calibration
- Calibration data is saved to **separate .fir files** (not in the main setup file)
- Use: **Calibration → Save FIR filter** to export calibration to a file
- Use: **Calibration → Load FIR filter** to import calibration from a file
- **Calibration Storage**:
  - A single .fir file can contain **all three** calibration types: normal, oversampling, and interleaved
  - When saving: All available calibrations are saved to the same file
  - When loading: Software automatically detects which calibrations are present and loads them
  - The appropriate calibration is selected automatically based on current mode during acquisition
- The saved .fir file (JSON format) contains:
  - **Normal Mode data** (if calibrated): FIR coefficients (64-256 taps), sample rate (3.2 GHz), frequency response, metadata
  - **Oversampling Mode data** (if calibrated): Two sets of FIR coefficients (one per board), sample rates (3.2 GHz each), frequency responses, metadata
  - **Interleaved Mode data** (if calibrated): FIR coefficients, sample rate (6.4 GHz), frequency response, metadata
- **Sample rate validation**: When loading, the software checks if the base sample rate matches
- **Downsample handling**:
  - Calibration must be done at downsample=0 (maximum sample rate)
  - The calibration can be used at downsampled rates (downsample>0)
  - When loading at downsample>0, you'll be informed that accuracy may be reduced
  - For best results, use downsample=0 when applying corrections
- **Note**: Calibration is specific to the hardware's base sample rate. Different hardware units need separate calibrations
- **Recommended workflow**:
  1. Connect 10 MHz square wave to input
  2. Calibrate in normal mode (no oversampling, no interleaving)
  3. Save calibration file
  4. Enable oversampling on active board (without interleaving)
  5. Run calibration again (will calibrate both boards in pair simultaneously)
  6. Save again (same file now contains both normal and oversampling calibrations)
  7. Enable both oversampling AND interleaving on active board
  8. Run calibration again (will calibrate interleaved waveform at 6.4 GHz)
  9. Save again (same file now contains all three calibration types: normal, oversampling, and interleaved)

## Technical Details

### FIR Filter Specifications
- **Number of taps**: Configurable (default: 64)
  - **64 taps**: Fast, good for most hardware (default)
  - **128 taps**: Better frequency resolution, balanced performance
  - **256 taps**: Best quality, slowest (2-4x processing time)
- **Window**: Blackman window (reduces ringing)
- **Filter method**: `scipy.signal.filtfilt` (zero-phase, no time delay)
- **Regularization**: 0.1% (small epsilon to prevent division by zero, not aggressive damping)
- **Max correction**: ±20 dB (prevents noise amplification)

### Sample Rate Handling
- Calibration is performed at the **current sample rate** (at downsample=0)
  - **Normal mode**: 3.2 GHz (base sample rate)
  - **Oversampling mode** (not interleaved): 3.2 GHz per board
  - **Interleaved mode**: 6.4 GHz (2x base sample rate)
- The filter is stored with the sample rate it was calibrated at
- **Important**: If you change base sample rates, you should re-run calibration
- Can be used at different downsample settings (with reduced accuracy)

### Depth (Sample Count) and Windowing
- **Automatic depth optimization during calibration**: Software temporarily sets depth to 640 samples
  - Chosen so 10 MHz harmonics land exactly on FFT bin centers (avoids spectral leakage)
  - FFT bin spacing:
    - Normal/Oversampling: Δf = 3.2 GHz / 640 = 5 MHz → harmonics at bins 2, 6, 10, 14...
    - Interleaved: Δf = 6.4 GHz / 640 = 10 MHz → harmonics at bins 1, 3, 5, 7...
  - This ensures accurate measurement of harmonic amplitudes without leakage between bins
  - After calibration completes, original depth is restored automatically
- **FIR filter is depth-independent**: Works identically at any depth
  - During calibration: depth affects frequency resolution of H(f) measurement
  - After calibration: freely change depth - correction applies the same way
  - **Why**: FIR filtering is sample-by-sample convolution, not dependent on signal length

### Performance
- FIR filtering uses `filtfilt` (forward-backward filtering)
- Same infrastructure as existing LPF, so minimal performance impact
- Typical overhead: ~10-20% increase in processing time per waveform
- For 1000 samples @ 64 taps: ~64,000 multiplies per channel

### Square Wave Calibration Coverage
- Square wave has **odd harmonics** at 10, 30, 50, 70, ... MHz up to hardware LPF cutoff
- **Hardware LPF cutoff (mode-dependent)**:
  - Normal/Oversampling mode: ~1.4 GHz → ~70 harmonics measured
  - Interleaved mode: ~2.5 GHz → ~125 harmonics measured
- Calibration is limited to frequencies below the hardware LPF cutoff
- Frequencies above the cutoff are intentionally filtered by hardware and not corrected
- The FIR filter interpolates smoothly between measured harmonics
- This provides correction across the usable hardware bandwidth

### Calibration Quality
- The calibration quality depends on:
  - Signal-to-noise ratio of input square wave
  - Stability of trigger (use trigger stabilizers)
  - Number of averages (default 200)
  - Cleanliness of square wave edges
- The success message shows improvement in dB (typically 3-10 dB for hardware with already-flat response)
- **Note**: If your hardware already has good frequency response (H(f) ≈ 1.0 at most frequencies), improvement will be modest. This is actually a good sign!

## File Format (.fir)

FIR calibration files use JSON format with the following structure:

```json
{
  "fir_coefficients": [0.0123, 0.0234, ... 64 values],
  "calibration_samplerate_hz": 3200000000.0,
  "calibration_downsample": 0,
  "num_taps": 64,
  "calibration_type": "10MHz_square_wave",
  "software_version": 31.08,
  "frequency_response": {
    "freqs": [0, 1e6, 2e6, ... frequency bins in Hz],
    "magnitude": [1.0, 0.98, ... magnitude at each frequency],
    "phase": [0.0, -0.01, ... phase in radians]
  }
}
```

**File Size:** ~10-20 KB per .fir file

## Files Modified/Created

### New Files
- `frequency_calibration.py` - Core calibration logic, FIR filter design, save/load functions

### Modified Files
- `scope_state.py` - Added FIR calibration state variables (lines 114-118)
- `plot_manager.py` - Added FIR filter application (lines 437-441)
- `main_window.py` - Added handlers and calibration capture (lines 521-637)
- `HaasoscopePro.ui` - UI actions for measure, apply, save, load (lines 2357-2360, 2994-3021)

## State Variables

The calibration state is stored in `ScopeState`:

```python
state.fir_correction_enabled          # bool: Enable/disable correction
state.fir_coefficients                # np.array: 64-tap FIR filter
state.fir_calibration_samplerate      # float: Sample rate during calibration (Hz)
state.fir_freq_response              # dict: Measured H(f) for display/analysis
```

## Future Enhancements

1. **Per-channel calibration**: Currently applies same correction to all channels
2. **Chirp calibration**: Use frequency sweep for continuous coverage
3. **Display H(f)**: Show frequency response plot in a dialog
4. **Auto-detect sample rate change during session**: Warn if sample rate changed after calibration was performed
5. **Multi-frequency calibration**: Use 1 MHz, 5 MHz, 10 MHz, 20 MHz square waves
6. **Calibration validation**: Show before/after FFT comparison in a dialog
7. **Calibration library**: Manage multiple calibrations for different sample rates in one place

## Troubleshooting

**"No calibration data available"**
- Run "Measure 10 MHz square FIR" first with a 10 MHz square wave connected

**"FIR calibration must be performed at maximum sample rate"**
- Set Downsample to 0 before running calibration
- The downsample control should show 0 (no downsampling)
- After calibration, you can use any downsample setting, but accuracy is best at downsample=0

**"Only captured N waveforms"**
- Ensure scope is acquiring (not paused)
- Check that trigger is stable
- Verify signal is connected to Channel 0

**Poor calibration results**
- Improve signal quality (cleaner square wave)
- Enable trigger stabilizers for better alignment
- Increase number of averages in `frequency_calibration.py` (line 12)
- Check that signal frequency is exactly 10 MHz

**Correction makes signal worse**
- Input signal may not be a 10 MHz square wave
- Re-run calibration with correct signal
- Try disabling "Apply FIR corrections" and verify input signal is correct

**Very small improvement (< 1 dB)**
- This is often **normal and good** - it means your hardware already has flat frequency response!
- Check the diagnostic output: if H(f) magnitude ≈ 1.0 at most frequencies, hardware is working well
- Example: H(f) = 1.01 at 10 MHz means only 1% deviation (excellent)
- Corrections will be subtle but still improve edges at frequencies that need it
- If H(f) shows large deviations (e.g., 0.5 or 2.0) but improvement is still small:
  - Check that signal is a clean 10 MHz square wave
  - Verify trigger is stable (use trigger stabilizers)
  - Ensure sufficient signal amplitude and SNR
  - Try increasing number of taps to 128 or 256 (see main_window.py line 554)
    - More taps = better frequency resolution and smoother corrections
    - Especially helpful if you have sharp frequency response variations

**"Sample Rate Mismatch" warning when loading**
- Calibration was performed at a different base sample rate
- The FIR filter's frequency response is scaled by sample rate ratio
- Options:
  1. Click "No" and re-calibrate at current sample rate
  2. Click "Yes" to use anyway (not recommended - may be inaccurate)
  3. Change scope sample rate to match calibration
- Best practice: Keep separate .fir files for each base sample rate

**"Invalid FIR filter file" error**
- File is corrupted or not a valid .fir file
- Check file format (should be JSON with required fields)
- Try re-saving the calibration

**File dialog cancellation**
- No error occurs if you cancel the save/load dialog
- Simply try again when ready

## Example Workflow

### Initial Calibration:
```
1. User connects 10 MHz square wave to scope
2. User sets Downsample = 0 (maximum sample rate)
3. User starts acquisition and verifies stable trigger
4. User clicks: Calibration → Measure 10 MHz square FIR
   → Software captures 50 waveforms
   → Computes H(f) and designs FIR filter
   → Shows "Calibration successful. Improvement: 15.3 dB"
5. Correction is automatically applied
6. User clicks: Calibration → Save FIR filter
   → Saves to "haasoscope_3.2GHz_DS0.fir"
7. All subsequent waveforms are corrected in real-time
```

### Later Session at Max Rate:
```
1. User starts software at same sample rate (3.2 GS/s, downsample=0)
2. User clicks: Calibration → Load FIR filter
   → Selects "haasoscope_3.2GHz_DS0.fir"
   → Software validates sample rate matches
   → Correction enabled automatically
3. Waveforms now use pre-calibrated correction
```

### Using at Downsampled Rate:
```
1. User has calibration from max rate (downsample=0)
2. User sets Downsample = 2 (slower acquisition for longer time window)
3. User clicks: Calibration → Load FIR filter
   → Selects "haasoscope_3.2GHz_DS0.fir"
   → ℹ️ Info: "Calibration was at downsample=0, you are at downsample=2"
   → Correction enabled with reduced accuracy warning
4. Correction still works, but accuracy may be reduced
   For best results, use downsample=0
```

### Different Base Sample Rate:
```
1. User changes hardware to different base sample rate
2. User clicks: Calibration → Load FIR filter
   → Selects "haasoscope_3.2GHz_DS0.fir"
   → ⚠️ Warning: "Sample rate mismatch"
   → User clicks "No" to re-calibrate
3. User sets downsample=0 and re-runs: Calibration → Measure 10 MHz square FIR
4. User saves new calibration as "haasoscope_1.6GHz_DS0.fir"
```

## Algorithm Details

### Phase Alignment
1. Average 200 captured waveforms to reduce noise
2. Estimate initial phase using first zero crossing
3. Generate ideal square wave with estimated phase
4. Fine-tune alignment using cross-correlation
5. Ensures measured and ideal waveforms are time-aligned

### Amplitude Normalization
- Normalize measured signal to match ideal signal's RMS amplitude
- This separates overall gain from frequency-dependent response
- The FIR filter then corrects only frequency response, preserving input signal amplitude
- **Critical**: Without this step, the filter would include overall gain correction

### Frequency Response Computation (Sparse Spectrum Handling)
Square waves have energy ONLY at odd harmonics (10, 30, 50 MHz...), not at even harmonics or other frequencies.

```python
# Find significant frequency bins (>1% of peak energy)
significant_bins = |FFT(ideal)| > 0.01 * max(|FFT(ideal)|)

# Only compute H(f) where signal has energy (typically 43 bins out of 20,000)
H(f) = 1.0 everywhere  # Default: no correction
H(f)[significant_bins] = FFT(measured)[significant_bins] / FFT(ideal)[significant_bins]

# Force DC to 1.0 (DC offset isn't a frequency response issue)
H(f)[0] = 1.0
```

- **Why**: At non-significant frequencies, both FFTs ≈ 0, giving H(f) = 0/0 = numerical garbage
- Includes both magnitude and phase response at significant frequencies only

### FIR Filter Design (Accounting for filtfilt Double-Pass)
1. Compute desired correction at significant bins: C(f) = 1/(H(f) + ε)
   - Regularization ε = 0.1% of max(H(f)) prevents division by exact zero (numerical stability)
   - **Important**: Should be very small (0.001) to avoid weakening corrections unnecessarily
   - The ±20 dB clipping (step 2) is the real protection against over-boosting
2. Clip correction to ±20 dB range (prevents noise amplification)
3. **Take square root**: C(f) = sqrt(C(f))
   - **Critical**: `filtfilt` applies the filter twice (forward + backward pass)
   - Effective correction = C(f)² after filtfilt
   - Without sqrt, we'd get massive over-correction
4. **Skip smoothing** (smoothing would destroy sparse harmonic corrections by averaging with neighboring zero-energy bins)
5. Interpolate correction between ONLY the 43 significant harmonic frequencies (not full 20,000 sparse array)
   - Use linear interpolation (no overshoot, unlike cubic)
   - Extrapolate beyond last harmonic using edge values
6. Inverse FFT to get time-domain impulse response (2048-point FFT)
7. **Center the impulse response** using `fftshift` (critical: impulse peak is centered, not at start)
8. Extract middle 64 taps centered around the peak
9. Apply Blackman window to reduce ringing
10. Normalize to unity DC gain (preserves overall signal amplitude)

### Real-Time Application
```python
for each waveform:
    y_corrected = filtfilt(fir_coefficients, [1.0], y_measured)
```
- Zero-phase filtering (no group delay)
- Applied to both resampled and non-resampled data
- Used for display, math channels, FFT, etc.

## Technical Notes (Implementation Details)

### Critical Design Decisions

**1. Sparse Spectrum Handling**
- Square waves have energy only at 43 out of 20,000 frequency bins
- Computing H(f) = measured/ideal at zero-energy bins gives 0/0 = numerical garbage
- **Solution**: Only compute H(f) at significant bins, set others to 1.0 (no correction)

**2. DC Bin Instability**
- Both measured and ideal square waves have near-zero DC (bipolar signals)
- DC bin division can give huge unstable values (observed: 195 million)
- This pollutes the entire correction via regularization and clipping
- **Solution**: Force H(f)[0] = 1.0 (DC offset isn't a frequency response issue)

**3. Smoothing Incompatible with Sparse Spectrum**
- Traditional FIR design uses median + Savitzky-Golay smoothing
- For sparse spectrum, this averages each harmonic with thousands of 1.0 values
- Result: All corrections averaged to constant ~0.9, destroying correction information
- **Solution**: Skip smoothing entirely for square wave calibration

**4. Interpolation from Sparse Points**
- Cannot interpolate from full 20,000-point array (mostly 1.0 with 43 corrections)
- Interpolation samples mostly 1.0 values, losing corrections
- **Solution**: Extract only the 43 significant frequencies and interpolate between those
- Use linear interpolation (cubic can overshoot between sparse points)

**5. filtfilt Double-Pass Effect**
- `filtfilt` applies filter forward then backward (zero-phase filtering)
- Effective gain = (filter_gain)²
- Example: 1.5x correction → filtfilt applies 1.5² = 2.25x → massive over-correction
- **Solution**: Take sqrt of correction magnitude before filter design
- Filter designed with 1.22x → filtfilt applies 1.22² = 1.5x ✓

**6. Amplitude Normalization**
- Input signal may have different overall amplitude than ideal (e.g., ±2.5 vs ±1.0)
- This isn't a frequency response issue, just signal scaling
- Without normalization: H(f) includes 2.5x gain at all frequencies
- **Solution**: Normalize measured to ideal RMS before computing H(f)
- FIR filter then corrects only frequency-dependent variations, preserving input amplitude

**7. Impulse Response Centering**
- `irfft` produces circular impulse response with peak centered
- Taking first 64 samples captures mostly zeros, producing useless filter
- **Solution**: Use `fftshift` to center, then extract middle 64 taps around peak

**8. Excessive Regularization**
- Original regularization = 5% of max(H(f)) was too aggressive
- For H(f) = 1.0 (flat response): correction = 1.0 / (1.0 + 0.05) = 0.95 (5% attenuation everywhere!)
- This weakened all corrections and prevented proper frequency response flattening
- **Solution**: Reduce to 0.1% (0.001) - just enough to prevent division by exact zero
- Real protection against over-boosting comes from ±20 dB clipping, not regularization

## References

- FIR Filter Design: https://en.wikipedia.org/wiki/Finite_impulse_response
- Frequency Sampling Method: scipy.signal.firwin2
- Zero-Phase Filtering: scipy.signal.filtfilt
- Square Wave Harmonics: Only odd harmonics (1f, 3f, 5f, ...)
