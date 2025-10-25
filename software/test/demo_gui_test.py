#!/usr/bin/env python3
"""
Quick Demo: HaasoscopeProQt GUI Test

This is a minimal example showing how to:
1. Start the dummy server
2. Launch HaasoscopeProQt
3. Wait and observe
4. Take a screenshot
5. Clean up

No special dependencies required beyond PIL/Pillow for screenshots.

Usage:
    cd test
    python demo_gui_test.py
"""

import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime

print("\n" + "="*80)
print(" HaasoscopeProQt GUI Test Demo")
print("="*80 + "\n")

# Configuration
DUMMY_SERVER_PORT = 9999
TEST_DURATION = 10  # seconds
SCREENSHOT_DIR = Path("demo_screenshots")

# Create screenshot directory
SCREENSHOT_DIR.mkdir(exist_ok=True)

print(f"Configuration:")
print(f"  - Dummy server port: {DUMMY_SERVER_PORT}")
print(f"  - Test duration: {TEST_DURATION} seconds")
print(f"  - Screenshot directory: {SCREENSHOT_DIR}")
print()

# Step 1: Start dummy server
print("[1/5] Starting dummy server...")
print("  Using --no-noise flag for deterministic, reproducible waveforms")
dummy_server_path = Path(__file__).parent.parent / "dummy_scope" / "dummy_server.py"

if not dummy_server_path.exists():
    print(f"ERROR: Dummy server not found at {dummy_server_path}")
    sys.exit(1)

# Start dummy server with --no-noise for deterministic testing
# This removes randomness: no noise, fixed phase, fixed pulse amplitudes
server_process = subprocess.Popen(
    [sys.executable, str(dummy_server_path), "--port", str(DUMMY_SERVER_PORT), "--no-noise"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
)

# Wait for server to initialize
time.sleep(2)

if server_process.poll() is not None:
    print("ERROR: Dummy server failed to start")
    stdout, stderr = server_process.communicate()
    print(stderr.decode())
    sys.exit(1)

print(f"  ✓ Dummy server running (PID {server_process.pid})")
print()

# Step 2: Launch GUI
print("[2/5] Launching HaasoscopeProQt GUI...")
print("  Using --testing flag for stable status bar (no fps/events/Hz/MB/s)")
gui_script = Path(__file__).parent.parent / "HaasoscopeProQt.py"

if not gui_script.exists():
    print(f"ERROR: GUI script not found at {gui_script}")
    server_process.terminate()
    sys.exit(1)

gui_process = subprocess.Popen(
    [
        sys.executable,
        str(gui_script),
        "--socket", f"localhost:{DUMMY_SERVER_PORT}",
        "--max-devices", "0",
        "--testing"  # Disable dynamic status bar updates for stable screenshots
    ],
    creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
)

print(f"  ✓ GUI launched (PID {gui_process.pid})")
print()

# Step 3: Wait for initialization
print("[3/5] Waiting for initialization...")
print(f"  Waiting {TEST_DURATION} seconds for GUI to initialize and run...")
print()
print("  Please verify in the GUI window:")
print("    - Main window opened successfully")
print("    - Waveforms are being displayed")
print("    - No error messages")
print("    - GUI is responsive")
print()

for i in range(TEST_DURATION):
    remaining = TEST_DURATION - i
    print(f"  Time remaining: {remaining}s  ", end='\r')
    time.sleep(1)

print(f"  Time remaining: 0s   ")
print()

# Step 4: Take screenshot
print("[4/5] Taking screenshot...")

try:
    from window_capture import capture_haasoscope_windows

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_dir = SCREENSHOT_DIR / timestamp
    screenshot_dir.mkdir(exist_ok=True, parents=True)

    # Capture all HaasoscopeProQt windows (main window and any child windows)
    screenshots = capture_haasoscope_windows(screenshot_dir, prefix="demo")

    if screenshots:
        print(f"  ✓ {len(screenshots)} screenshot(s) saved to: {screenshot_dir}")
        for screenshot_path in screenshots:
            print(f"    - {screenshot_path.name}")
    else:
        print("  ⚠ No screenshots captured")
    print()

except ImportError as e:
    print(f"  ⚠ Required module not installed: {e}")
    print("  Install with: pip install pyautogui pygetwindow")
    print()

# Step 5: Clean up
print("[5/5] Cleaning up...")

# Stop GUI
if gui_process.poll() is None:
    print("  Stopping GUI...")
    gui_process.terminate()
    try:
        gui_process.wait(timeout=5)
        print("  ✓ GUI stopped")
    except subprocess.TimeoutExpired:
        print("  GUI didn't stop, killing...")
        gui_process.kill()
        gui_process.wait()
        print("  ✓ GUI killed")

# Stop server
if server_process.poll() is None:
    print("  Stopping dummy server...")
    server_process.terminate()
    try:
        server_process.wait(timeout=5)
        print("  ✓ Dummy server stopped")
    except subprocess.TimeoutExpired:
        print("  Dummy server didn't stop, killing...")
        server_process.kill()
        server_process.wait()
        print("  ✓ Dummy server killed")

print()

# Summary
print("="*80)
print(" TEST COMPLETE")
print("="*80)
print()
print("Summary:")
print(f"  • Dummy server ran successfully (deterministic mode)")
print(f"  • GUI launched and ran for {TEST_DURATION} seconds (testing mode)")
print(f"  • Screenshots saved to: {SCREENSHOT_DIR}")
print(f"  • Captured HaasoscopeProQt windows only (not full screen)")
print()
print("Next steps:")
print("  1. Review the screenshots to verify GUI appearance")
print("  2. Try the full test scripts:")
print("     - python test_gui_standalone.py")
print("     - python test_gui_automated.py --baseline")
print("  3. Read TEST_GUI_README.md for detailed documentation")
print()
print("="*80)
