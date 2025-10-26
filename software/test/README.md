# HaasoscopeProQt GUI Testing

Automated GUI testing for HaasoscopeProQt using the dummy oscilloscope server.

## Quick Start

### 1. Install Dependencies

**Option 1: Using requirements file (recommended)**
```bash
cd software/test
pip install -r test_requirements.txt
```

**Option 2: Manual installation**
```bash
cd software/test
pip install pyautogui pillow numpy

# Platform-specific:
# macOS: PyObjC for window detection (test_gui.py only)
pip install pyobjc-framework-Quartz

# Windows: pygetwindow and pywinauto (required for test_settings.py)
pip install pygetwindow pywinauto

# Linux: pygetwindow
pip install pygetwindow
```

**Note:** `test_settings.py` requires pywinauto and only works on Windows.

### 2. Run a Test

**Basic GUI Test:**
```bash
# Basic test (runs GUI for 10 seconds, takes screenshots)
python test_gui.py

# Create baseline screenshots
python test_gui.py --baseline

# Compare to baseline (regression testing)
python test_gui.py --compare
```

**Settings Save/Load Test (Comprehensive):**
```bash
# Full functional test - changes settings, saves, reloads, verifies
# NOTE: Windows only - requires pywinauto for GUI automation
python test_settings.py
```

**⚠️ Platform Support:**
- `test_gui.py` - Supported on Windows, macOS, and Linux
- `test_settings.py` - **Windows only** (requires pywinauto for GUI automation)

## Test Scripts

### test_gui.py - Basic GUI Test

Simple screenshot-based test for quick verification:

1. **Starts dummy server** - Launches the dummy oscilloscope server with `--no-noise` for deterministic waveforms
2. **Launches GUI** - Starts HaasoscopeProQt with `--testing` flag for stable status bar
3. **Waits** - Allows time for initialization
4. **Captures screenshots** - Takes window-specific screenshots (not full screen)
5. **Cleans up** - Stops all processes

### test_settings.py - Settings Save/Load Test

**⚠️ WINDOWS ONLY - This test requires pywinauto for GUI automation and is not supported on macOS or Linux.**

Comprehensive functional test that exercises the complete save/load workflow:

1. **Starts HaasoscopeProQt** - Launches GUI with dummy server
2. **Changes settings** - Simulates user interaction to modify various settings
   - Downsample factor
   - Trigger level
   - Persist mode
   - Other GUI controls
3. **Saves settings** - Uses Ctrl+S to save configuration to file
4. **Takes baseline screenshot** - Captures state with modified settings
5. **Restarts program** - Closes and relaunches HaasoscopeProQt
6. **Loads settings** - Uses Ctrl+O to load saved configuration
7. **Compares screenshots** - Verifies settings were restored correctly

**This is the recommended comprehensive test on Windows** as it validates actual functionality, not just appearance.

## Test Modes

### Basic Test (Default)
```bash
python test_gui.py
```
- Runs GUI for 10 seconds
- Takes screenshots
- Useful for quick verification

### Baseline Mode
```bash
python test_gui.py --baseline
```
- Creates reference screenshots for future comparisons
- Run this first before doing comparison tests
- Screenshots saved to `screenshots/baseline/`

### Compare Mode
```bash
python test_gui.py --compare
```
- Compares current screenshots to baseline
- Reports pixel difference percentage
- Generates visual diff images
- Returns exit code 0 (pass) or 1 (fail)

## Command-Line Options

```bash
python test_gui.py [OPTIONS]
```

**Options:**
- `--baseline` - Create baseline screenshots
- `--compare` - Compare to baseline
- `--duration SECONDS` - Test duration (default: 10)
- `--port PORT` - Dummy server port (default: 9999)
- `--border PIXELS` - Window border adjustment (default: 8)
- `--threshold DECIMAL` - Comparison threshold 0-1 (default: 0.05 = 5%)

**Examples:**
```bash
# Run for 20 seconds
python test_gui.py --duration 20

# Adjust for window shadow (if seeing extra pixels)
python test_gui.py --border 10

# More lenient comparison (allow 10% difference)
python test_gui.py --compare --threshold 0.10
```

## Deterministic Testing

The test automatically enables deterministic mode for reproducible results:

**Dummy Server (`--no-noise`):**
- Fixed phase (always 0.0 radians)
- No random noise
- Fixed pulse amplitudes and positions
- Identical waveforms every run

**GUI (`--testing`):**
- Stable status bar (no fps/events/Hz/MB/s counters)
- Only shows sample rate and connection info
- No constantly changing text

**Result:** Pixel-perfect reproducible screenshots for reliable automated testing.

## Window Capture

Screenshots capture **only HaasoscopeProQt windows**, not the full screen:

- Finds all windows with "Haasoscope" in title
- Captures main window separately
- Captures child windows (FFT, XY, Histogram) individually
- Automatic border adjustment (removes Windows shadow)

**Border Adjustment:**

Windows adds an invisible 7-10 pixel border for shadows. Default adjustment is 8 pixels.

If screenshots still show extra pixels:
```bash
# Try larger adjustment
python test_gui.py --border 10
python test_gui.py --border 12

# Or disable adjustment
python test_gui.py --border 0
```

To test what works best:
```bash
python -m window_capture  # Run with GUI open
```

## File Structure

```
test/
├── README.md              # This file
├── test_gui.py            # Main test script
├── window_capture.py      # Window screenshot utilities
└── screenshots/           # Created by tests
    ├── baseline/          # Reference screenshots
    ├── *.png              # Current test screenshots
    └── diff_*.png         # Difference images
```

## CI/CD Integration

For automated testing pipelines:

```bash
# In your CI/CD script
cd software/test

# First run: create baselines (commit these)
python test_gui.py --baseline

# Subsequent runs: compare to baseline
python test_gui.py --compare
if [ $? -ne 0 ]; then
    echo "GUI regression detected!"
    exit 1
fi
```

The script returns:
- Exit code `0` - Test passed
- Exit code `1` - Test failed

## Troubleshooting

**Problem: Screenshots only show desktop background (macOS)**
- You need to enable Screen Recording permission
- See [MACOS_SCREEN_CAPTURE.md](MACOS_SCREEN_CAPTURE.md) for step-by-step instructions
- Run `python diagnose_macos_capture.py` to check your setup

**Problem: "Dummy server not found"**
- Ensure you're in the `software/test/` directory
- Check that `../dummy_scope/dummy_server.py` exists

**Problem: "No windows found"**
- Make sure HaasoscopeProQt is running (test launches it automatically)
- On Linux, ensure X11 is available
- Test will fall back to full-screen capture if window detection fails

**Problem: "pyautogui not found"**
```bash
pip install pyautogui pillow pygetwindow numpy
```

**Problem: Screenshots differ too much**
- Ensure you're running in deterministic mode (automatic)
- Check that dummy server is using `--no-noise` (automatic)
- Increase threshold: `--threshold 0.10` (10%)
- Verify border adjustment is correct for your system

**Problem: Extra pixels around windows**
- Default border adjustment is 8 pixels
- Try: `--border 10` or `--border 12`
- Test with: `python -m window_capture`

## Advanced Usage

### Custom Test Script

```python
from test_gui import GUITest, DEFAULT_CONFIG

# Customize configuration
config = DEFAULT_CONFIG.copy()
config.update({
    "duration": 30.0,
    "border_adjustment": 10,
})

# Run test
test = GUITest(config)
success = test.run(mode="compare")
```

### Window Capture Utilities

```python
from window_capture import capture_haasoscope_windows
from pathlib import Path

# Capture all HaasoscopeProQt windows
screenshots = capture_haasoscope_windows(
    save_dir=Path("my_screenshots"),
    prefix="test",
    border_adjustment=8
)

# Returns list of Path objects
for screenshot in screenshots:
    print(f"Saved: {screenshot}")
```

## Best Practices

1. **Create baselines on a clean system** - Ensure consistent starting point
2. **Commit baselines to version control** - Track expected appearance
3. **Run tests regularly** - Catch regressions early
4. **Review diff images** - Understand what changed
5. **Adjust threshold as needed** - Balance sensitivity vs. stability
6. **Use deterministic mode** - Tests do this automatically
7. **Test on target platform** - Window rendering varies by OS/theme

## See Also

- [Dummy Server Documentation](../dummy_scope/README.md) - Details on dummy oscilloscope server
- [Main README](../README.md) - HaasoscopeProQt documentation
- [window_capture.py](window_capture.py) - Window screenshot utilities source

## Support

For issues or questions about testing, check:
- This README for common problems
- Test script help: `python test_gui.py --help`
- Window capture test: `python -m window_capture`
