# HaasoscopeProQt GUI Testing

This directory contains automated GUI testing scripts for HaasoscopeProQt. The tests use a dummy server to simulate hardware, allowing comprehensive GUI testing without physical oscilloscope hardware.

## Overview

Three test scripts are provided, each with different capabilities and complexity:

1. **test_gui_standalone.py** - Simple subprocess-based test (easiest to use)
2. **test_gui_automated.py** - Advanced automated testing with screenshots and comparison
3. **test_gui.py** - Full pytest-qt framework for comprehensive GUI testing

## Quick Start

**Important:** All commands should be run from the `software/test/` directory:

```bash
cd software/test
```

### 1. Install Test Dependencies

```bash
pip install -r test_requirements.txt
```

Minimum requirements:
```bash
pip install pytest pytest-qt pillow pyautogui numpy
```

For full automation on Windows:
```bash
pip install pywinauto
```

### 2. Run a Simple Test

The easiest way to get started:

```bash
python test_gui_standalone.py
```

This will:
- Start the dummy server on port 9999
- Launch HaasoscopeProQt connected to the dummy server
- Run for 5 seconds
- Take a screenshot
- Clean up and generate a report

### 3. Run Automated Tests with Baseline Comparison

First, create baseline screenshots:

```bash
python test_gui_automated.py --baseline --verbose
```

Then run comparison tests:

```bash
python test_gui_automated.py --verbose
```

The tests will compare current screenshots against baselines and report differences.

## Test Scripts

### test_gui_standalone.py

**Purpose:** Simple test that launches GUI and dummy server, verifies they run.

**Features:**
- Starts dummy server automatically
- Launches GUI in subprocess
- Waits for specified duration
- Optional screenshot capture
- Clean shutdown

**Usage:**
```bash
# Basic test (5 seconds)
python test_gui_standalone.py

# Run for 10 seconds
python test_gui_standalone.py --duration 10

# Skip screenshots
python test_gui_standalone.py --no-screenshots

# Use different port
python test_gui_standalone.py --port 8888
```

**Pros:**
- Simple and easy to understand
- No complex dependencies
- Good for quick smoke tests

**Cons:**
- Limited automation
- Requires manual verification
- No GUI interaction

---

### test_gui_automated.py

**Purpose:** Automated testing with screenshot comparison and regression detection.

**Features:**
- Automated dummy server management
- Screenshot capture of GUI states
- Baseline comparison (detects visual regressions)
- Pixel-by-pixel difference detection
- Optional pywinauto integration for GUI control
- Comprehensive test reporting

**Usage:**
```bash
# Create baseline screenshots (first run)
python test_gui_automated.py --baseline

# Run tests and compare to baseline
python test_gui_automated.py

# Verbose output
python test_gui_automated.py --verbose

# Create new baselines with verbose output
python test_gui_automated.py --baseline --verbose
```

**Test Flow:**
1. Start dummy server
2. Launch GUI application
3. Wait for initialization
4. Take screenshots at various test points
5. Compare to baseline (or create baseline)
6. Generate test report
7. Clean up

**Pros:**
- Automated screenshot comparison
- Detects visual regressions
- Can run unattended
- Generates detailed reports

**Cons:**
- Requires baseline screenshots
- Screenshots may differ due to timing/data variations
- Limited GUI interaction without pywinauto

---

### test_gui.py

**Purpose:** Full pytest-qt framework for comprehensive GUI testing.

**Features:**
- pytest integration for test management
- pytest-qt for Qt widget testing
- Screenshot capture and comparison
- Fixture-based test structure
- Extensible test cases
- Detailed test reporting

**Usage:**
```bash
# Run all tests
pytest test_gui.py -v

# Run specific test
pytest test_gui.py -v -k test_basic_startup

# Run with HTML report
pytest test_gui.py -v --html=report.html

# Run tests and keep screenshots on success
pytest test_gui.py -v --screenshots
```

**Test Cases:**
- `test_dummy_server_starts` - Verify dummy server starts
- `test_basic_startup` - Verify GUI launches and main window appears
- `test_menu_interactions` - Test menu navigation
- `test_trigger_settings` - Test trigger control interactions
- `test_channel_controls` - Test channel settings
- `test_fft_window` - Test FFT window opening
- `test_screenshot_comparison` - Regression testing with baselines

**Pros:**
- Full pytest framework
- Easy to extend with new tests
- Good for CI/CD integration
- Standard testing practices

**Cons:**
- More complex setup
- Requires pytest knowledge
- May need Qt widget inspection to write tests

## Test Architecture

### Dummy Server

All tests use the dummy oscilloscope server located in `dummy_scope/dummy_server.py`. This server:

- Simulates HaasoscopePro board communication
- Generates realistic waveforms (sine, square, pulse)
- Responds to all opcodes (0-12)
- Supports trigger simulation
- Runs on TCP socket (default port 9999)

The dummy server allows testing without hardware by providing:
- Configurable waveform generation
- Trigger position tracking
- Multi-channel simulation
- Realistic timing and data flow

### Screenshot Management

Screenshots are saved to:
- **Current run:** `test_screenshots/`
- **Baselines:** `test_screenshots/baseline/`
- **Differences:** `test_screenshots/diff_*.png`

Screenshot comparison:
- Pixel-by-pixel difference calculation
- Configurable threshold (default 5%)
- Visual diff images for debugging
- Automatic baseline creation on first run

### Test Configuration

Configuration in `test_gui.py` and `test_gui_automated.py`:

```python
TEST_CONFIG = {
    "dummy_server_port": 9999,
    "dummy_server_host": "localhost",
    "init_wait_time": 3.0,  # seconds
    "screenshot_dir": "test_screenshots",
    "baseline_dir": "test_screenshots/baseline",
    "comparison_threshold": 0.05,  # 5% difference allowed
}
```

Adjust these values based on your needs.

## Writing New Tests

### Adding Tests to test_gui.py

```python
def test_my_feature(haasoscope_app, screenshot_manager, qtbot):
    """Test my new feature."""
    app = haasoscope_app["app"]
    main_window = haasoscope_app["main_window"]

    # 1. Perform actions
    # Find widget: widget = main_window.findChild(QtWidgets.QPushButton, "my_button")
    # Click button: qtbot.mouseClick(widget, QtCore.Qt.LeftButton)

    # 2. Wait for response
    qtbot.wait(500)  # Wait 500ms

    # 3. Take screenshot
    screenshot_manager.capture_widget(main_window, "test_my_feature")

    # 4. Assert expected state
    assert some_condition, "Feature did not work as expected"
```

### Adding Tests to test_gui_automated.py

```python
def test_my_feature(self):
    """Test: My new feature."""
    test_name = "my_feature"
    self.log(f"Running test: {test_name}")

    # Perform test actions
    time.sleep(1.0)  # Wait if needed

    # Take screenshot
    self.screenshot_manager.capture_screen_region(name="04_my_feature")

    # Compare or create baseline
    if self.create_baseline:
        self.screenshot_manager.save_as_baseline("04_my_feature")
        result = {"test": test_name, "status": "baseline_created"}
    else:
        comparison = self.screenshot_manager.compare_to_baseline("04_my_feature")
        result = {
            "test": test_name,
            "status": "pass" if comparison['within_threshold'] else "fail",
            "difference": comparison['difference_percent']
        }

    self.test_results.append(result)
    return result
```

Then add it to the `run()` method:
```python
def run(self):
    # ... existing tests ...
    self.test_my_feature()
```

## Advanced Usage

### GUI Automation with pywinauto (Windows)

For full GUI automation, install pywinauto:

```bash
pip install pywinauto
```

Then you can interact with GUI elements:

```python
from pywinauto import Application

# Connect to running application
app = Application().connect(process=gui_process.pid)

# Find and click a button
app.window(title="Haasoscope").Button("Run").click()

# Access menu items
app.window(title="Haasoscope").menu_select("File->Open")

# Type in text fields
app.window(title="Haasoscope").Edit("frequency").set_text("1000")
```

### Inspecting Qt Widgets

To find widget names for testing:

```python
# In test_gui.py
def test_inspect_widgets(haasoscope_app):
    main_window = haasoscope_app["main_window"]

    # List all child widgets
    for widget in main_window.findChildren(QtWidgets.QWidget):
        print(f"{widget.__class__.__name__}: {widget.objectName()}")
```

Or use Qt Designer to inspect the `.ui` files:
- `HaasoscopePro.ui` - Main window layout
- `HaasoscopeProFFT.ui` - FFT window layout

### CI/CD Integration

For continuous integration:

```yaml
# Example GitHub Actions workflow
name: GUI Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r test_requirements.txt
      - name: Run GUI tests
        run: pytest test_gui.py -v --html=report.html
      - name: Upload test results
        uses: actions/upload-artifact@v2
        with:
          name: test-results
          path: report.html
```

## Troubleshooting

### Issue: Dummy server fails to start

**Solution:**
- Check if port 9999 is already in use: `netstat -an | findstr 9999`
- Use a different port: `python test_gui_automated.py --port 8888`
- Check dummy server logs

### Issue: GUI doesn't appear

**Solution:**
- Increase init wait time in config (try 5-10 seconds)
- Check if HaasoscopeProQt.py runs manually
- Verify all dependencies are installed
- Check for errors in console output

### Issue: Screenshot comparison always fails

**Solution:**
- Waveforms change each frame, causing differences
- Increase comparison threshold: `COMPARISON_THRESHOLD = 0.10` (10%)
- Take screenshots at stable UI states (not during active acquisition)
- Use specific widget screenshots instead of full window

### Issue: pywinauto can't find windows

**Solution:**
- Try backend="uia" instead of "win32"
- Use `print_control_identifiers()` to see available controls
- Increase timeout for window detection
- Ensure GUI is fully initialized before connecting

### Issue: Tests hang or don't complete

**Solution:**
- Check for modal dialogs blocking execution
- Reduce test duration if too long
- Add timeout handling
- Check process cleanup is working

## Best Practices

1. **Always create baselines first** before running comparison tests
2. **Use verbose mode** (`--verbose`) when debugging tests
3. **Inspect widget structure** before writing interaction tests
4. **Wait for initialization** - GUI needs time to fully load
5. **Clean up processes** - Ensure tests cleanup on failure
6. **Use stable test states** - Avoid comparing rapidly changing data
7. **Document test expectations** - Explain what each test verifies
8. **Run tests regularly** - Detect regressions early

## File Organization

```
HaasoscopePro/software/
├── test/                            # Test directory (this directory)
│   ├── test_gui.py                  # pytest-qt framework tests
│   ├── test_gui_standalone.py       # Simple standalone test
│   ├── test_gui_automated.py        # Automated test with comparison
│   ├── demo_gui_test.py             # Quick demo test
│   ├── test_requirements.txt        # Test dependencies
│   ├── TEST_GUI_README.md           # This file
│   ├── QUICK_START_TESTING.md       # Quick start guide
│   ├── run_gui_tests.bat            # Windows test runner
│   ├── run_gui_tests.sh             # Linux/Mac test runner
│   ├── test_screenshots/            # Current test screenshots
│   │   ├── baseline/                # Baseline images for comparison
│   │   ├── diff_*.png               # Visual difference images
│   │   └── *.png                    # Test screenshots
│   └── demo_screenshots/            # Demo screenshots
│
├── dummy_scope/                     # Dummy server for testing
│   ├── dummy_server.py              # Oscilloscope simulator
│   ├── USB_Socket.py                # Socket adapter
│   └── dummy_server_config_dialog.py
│
└── HaasoscopeProQt.py               # Main application
```

## Next Steps

1. **Run a simple test** to verify everything works
2. **Create baselines** for automated comparison
3. **Add custom tests** for your specific features
4. **Integrate into CI/CD** for automated testing
5. **Expand test coverage** to all GUI features

## Support

For issues or questions:
1. Check this README for troubleshooting
2. Review test script comments and docstrings
3. Inspect existing test cases for examples
4. Check ../dummy_scope/README.md for server details

## License

Same as HaasoscopePro main project.
