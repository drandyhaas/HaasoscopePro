# Quick Start: GUI Testing for HaasoscopeProQt

## 🚀 Get Started in 3 Steps

### Step 0: Navigate to Test Directory

All test commands should be run from the `test/` directory:

```bash
cd software/test
```

### Step 1: Install Dependencies

```bash
pip install pillow pyautogui
```

For full testing capabilities:
```bash
pip install -r test_requirements.txt
```

### Step 2: Run the Demo

**Windows:**
```bash
python demo_gui_test.py
```

**Linux/Mac:**
```bash
python3 demo_gui_test.py
```

Or use the menu-driven runner:

**Windows:**
```bash
run_gui_tests.bat
```

**Linux/Mac:**
```bash
chmod +x run_gui_tests.sh
./run_gui_tests.sh
```

### Step 3: Try the Full Tests

**Create baseline screenshots:**
```bash
python test_gui_automated.py --baseline --verbose
```

**Run tests and compare:**
```bash
python test_gui_automated.py --verbose
```

## 📁 What Got Created

| File | Purpose |
|------|---------|
| `demo_gui_test.py` | ⭐ Simple 8-second demo - start here! |
| `test_gui_standalone.py` | Basic smoke test, no complex dependencies |
| `test_gui_automated.py` | Full automated test with screenshot comparison |
| `test_gui.py` | pytest-qt framework for comprehensive testing |
| `run_gui_tests.bat` | Windows menu for easy test selection |
| `run_gui_tests.sh` | Linux/Mac menu for easy test selection |
| `test_requirements.txt` | All testing dependencies |
| `TEST_GUI_README.md` | Complete documentation |
| `QUICK_START_TESTING.md` | This file |

## 🎯 What Each Test Does

### demo_gui_test.py - **Recommended First Test**
```bash
python demo_gui_test.py
```

- Starts dummy server on port 9999
- Launches HaasoscopeProQt GUI
- Runs for 8 seconds
- Takes a screenshot
- Cleans up automatically
- **No pytest needed, minimal dependencies**

### test_gui_standalone.py - **Basic Testing**
```bash
python test_gui_standalone.py --duration 10
```

- Similar to demo but more configurable
- Can specify duration, port, enable/disable screenshots
- Good for quick smoke tests
- Manual verification of GUI

### test_gui_automated.py - **Automated Regression Testing**
```bash
# First run - create baselines
python test_gui_automated.py --baseline --verbose

# Subsequent runs - compare to baseline
python test_gui_automated.py --verbose
```

- Automated screenshot comparison
- Detects visual regressions
- Generates test reports
- Baseline-based testing
- Can use pywinauto for GUI automation (optional)

### test_gui.py - **Full pytest Suite**
```bash
pytest test_gui.py -v
```

- Complete pytest-qt framework
- Multiple test cases
- Extensible and standard
- Good for CI/CD integration

## 🔧 Common Tasks

### Just Want to See if GUI Works?
```bash
python demo_gui_test.py
```

### Setting Up Automated Testing?
```bash
# Install dependencies
pip install -r test_requirements.txt

# Create baselines
python test_gui_automated.py --baseline

# Run tests
python test_gui_automated.py
```

### Running Tests Regularly?
Use the menu scripts:
- Windows: `run_gui_tests.bat`
- Linux/Mac: `./run_gui_tests.sh`

### Adding to CI/CD?
```bash
pytest test_gui.py -v --html=report.html
```

## 📸 Screenshot Locations

- **Current run:** `test_screenshots/`
- **Baselines:** `test_screenshots/baseline/`
- **Differences:** `test_screenshots/diff_*.png`
- **Demo:** `demo_screenshots/`

## ❓ Troubleshooting

**Problem: "Dummy server not found"**
- Make sure you're in the `software/test/` directory
- Check that `../dummy_scope/dummy_server.py` exists (one level up)

**Problem: "GUI doesn't appear"**
- Wait longer - increase test duration
- Check if port 9999 is available
- Run HaasoscopeProQt.py manually first to verify it works

**Problem: "Screenshots always fail comparison"**
- This is normal! Waveforms change constantly
- Increase threshold in code or take screenshots at stable states
- Compare UI elements, not waveform data

**Problem: "pyautogui not found"**
```bash
pip install pyautogui pillow
```

## 📚 More Information

- **Full documentation:** `TEST_GUI_README.md` (in this directory)
- **Dummy server info:** `../dummy_scope/README.md`
- **Main project:** `../../README.md`

## 🎓 Next Steps

1. ✅ Run `demo_gui_test.py` to verify everything works
2. ✅ Read `TEST_GUI_README.md` for detailed information
3. ✅ Create your own tests based on the examples
4. ✅ Integrate into your development workflow

---

**Have fun testing! 🧪**
