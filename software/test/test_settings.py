#!/usr/bin/env python3
"""
HaasoscopeProQt Settings Save/Load Test

Comprehensive functional test that:
1. Launches HaasoscopeProQt
2. Changes multiple GUI settings via simulated user interaction
3. Saves settings to a file
4. Takes baseline screenshots
5. Restarts the program
6. Loads the settings file
7. Compares screenshots to verify settings were restored correctly

This tests the complete save/load settings workflow.

Usage:
    cd test
    python test_settings.py

Requirements:
    pip install pyautogui pillow pygetwindow numpy

    Windows only (for GUI automation):
    pip install pywinauto
"""
import os
import sys
import time
import subprocess
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from datetime import datetime

# For screenshots
import pyautogui
from PIL import Image, ImageChops
import numpy as np

# Try to import pywinauto for advanced GUI automation
try:
    from pywinauto import Application
    from pywinauto.findwindows import ElementNotFoundError
    PYWINAUTO_AVAILABLE = True
except ImportError:
    PYWINAUTO_AVAILABLE = False
    print("Warning: pywinauto not available. Install with: pip install pywinauto")
    print("         This test requires pywinauto for GUI automation on Windows.")


# === Configuration ===
DEFAULT_CONFIG = {
    "port": 9999,
    "host": "localhost",
    "init_wait": 5.0,  # seconds to wait for GUI initialization
    "action_wait": 0.5,  # seconds to wait between GUI actions
    "screenshot_dir": "screenshots/settings_test",
    "settings_file": "test_settings.haasoscope",
    "border_adjustment": 8,
    "comparison_threshold": 0.02,  # 2% difference allowed (stricter than basic test)
}


# === Helper Classes ===

class DummyServerManager:
    """Manages the dummy oscilloscope server."""

    def __init__(self, port: int, host: str = "localhost"):
        self.port = port
        self.host = host
        self.process: Optional[subprocess.Popen] = None

    def start(self):
        """Start the dummy server."""
        dummy_server_path = Path(__file__).parent.parent / "dummy_scope" / "dummy_server.py"
        if not dummy_server_path.exists():
            raise FileNotFoundError(f"Dummy server not found at {dummy_server_path}")

        print(f"[SERVER] Starting on {self.host}:{self.port} (deterministic mode)")

        self.process = subprocess.Popen(
            [sys.executable, str(dummy_server_path), "--port", str(self.port), "--no-noise"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )

        time.sleep(2.0)

        if self.process.poll() is not None:
            stdout, stderr = self.process.communicate()
            raise RuntimeError(f"Dummy server failed:\n{stderr.decode()}")

        print(f"[SERVER] Running (PID {self.process.pid})")

    def stop(self):
        """Stop the dummy server."""
        if self.process:
            print(f"[SERVER] Stopping (PID {self.process.pid})")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None


class ScreenshotManager:
    """Manages screenshots and comparisons."""

    def __init__(self, screenshot_dir: str, border_adjustment: int = 8):
        self.screenshot_dir = Path(screenshot_dir)
        self.border_adjustment = border_adjustment
        self.screenshot_dir.mkdir(exist_ok=True, parents=True)
        self.screenshots = {}

    def capture_windows(self, name: str) -> List[Path]:
        """Capture all HaasoscopeProQt windows."""
        try:
            from window_capture import capture_haasoscope_windows

            screenshots = capture_haasoscope_windows(
                self.screenshot_dir, prefix=name, border_adjustment=self.border_adjustment
            )

            # Store first screenshot for comparison
            if screenshots:
                self.screenshots[name] = screenshots[0]

            return screenshots

        except Exception as e:
            print(f"[SCREENSHOT] Warning: {e}")
            return []

    def compare_screenshots(self, name1: str, name2: str, threshold: float = 0.02) -> Dict:
        """Compare two screenshots."""
        if name1 not in self.screenshots or name2 not in self.screenshots:
            return {'error': 'Screenshots not found'}

        path1 = self.screenshots[name1]
        path2 = self.screenshots[name2]

        # Load images
        img1 = Image.open(path1).convert('RGB')
        img2 = Image.open(path2).convert('RGB')

        if img1.size != img2.size:
            return {
                'match': False,
                'difference_percent': 100.0,
                'within_threshold': False,
                'error': f"Size mismatch: {img1.size} vs {img2.size}"
            }

        # Calculate pixel difference
        diff = ImageChops.difference(img1, img2)
        diff_array = np.array(diff)

        total_pixels = diff_array.size
        different_pixels = np.count_nonzero(diff_array)
        difference_percent = (different_pixels / total_pixels) * 100

        # Save diff image
        diff_path = self.screenshot_dir / f"diff_{name1}_vs_{name2}.png"
        diff.save(str(diff_path))

        within_threshold = difference_percent < (threshold * 100)

        return {
            'match': difference_percent == 0,
            'difference_percent': difference_percent,
            'within_threshold': within_threshold,
            'diff_image': diff_path
        }


class GUIController:
    """Controls GUI interactions using pywinauto."""

    def __init__(self, gui_process: subprocess.Popen, action_wait: float = 0.5):
        if not PYWINAUTO_AVAILABLE:
            raise RuntimeError("pywinauto is required for GUI automation")

        self.gui_process = gui_process
        self.action_wait = action_wait
        self.app = None
        self.main_window = None

    def connect(self, timeout: int = 10):
        """Connect to the running GUI application."""
        print("[GUI] Connecting to HaasoscopeProQt window...")

        # Wait for window to appear
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                self.app = Application(backend="uia").connect(process=self.gui_process.pid)
                self.main_window = self.app.window(title_re=".*Haasoscope.*")

                # Verify window is visible
                if self.main_window.exists():
                    print(f"[GUI] Connected to window: {self.main_window.window_text()}")
                    time.sleep(self.action_wait)
                    return True
            except Exception as e:
                time.sleep(0.5)

        raise RuntimeError("Could not connect to GUI window")

    def change_settings(self):
        """
        Change various GUI settings to create a different configuration.
        This simulates user interaction.
        """
        print("[GUI] Changing settings...")

        try:
            # Give window focus
            self.main_window.set_focus()
            time.sleep(self.action_wait)

            # Change 1: Adjust time scale using timefast button (increases downsample)
            try:
                print("[GUI]   - Clicking timefast button (3 times)...")
                timefast_btn = self.main_window.child_window(auto_id="timefast", control_type="Button")
                if timefast_btn.exists():
                    for i in range(3):
                        timefast_btn.click()
                        time.sleep(self.action_wait * 0.5)
            except Exception as e:
                print(f"[GUI]     Note: Could not click timefast ({e})")

            # Change 2: Adjust trigger threshold using threshold slider
            try:
                print("[GUI]   - Setting trigger threshold slider to 128...")
                threshold_slider = self.main_window.child_window(auto_id="threshold", control_type="Slider")
                if threshold_slider.exists():
                    threshold_slider.set_value(128)
                    time.sleep(self.action_wait)
            except Exception as e:
                print(f"[GUI]     Note: Could not set threshold slider ({e})")

            # Change 3: Adjust trigger position using thresholdPos slider
            try:
                print("[GUI]   - Setting trigger position slider to 200...")
                pos_slider = self.main_window.child_window(auto_id="thresholdPos", control_type="Slider")
                if pos_slider.exists():
                    pos_slider.set_value(200)
                    time.sleep(self.action_wait)
            except Exception as e:
                print(f"[GUI]     Note: Could not set thresholdPos slider ({e})")

            # Change 4: Toggle persist mode checkbox (use index to disambiguate)
            try:
                print("[GUI]   - Toggling persist mode...")
                # Get all persist checkboxes and use the first one
                persist_checks = self.main_window.children(title_re=".*Persist.*", control_type="CheckBox")
                if persist_checks and len(persist_checks) > 0:
                    persist_checks[0].click()
                    time.sleep(self.action_wait)
            except Exception as e:
                print(f"[GUI]     Note: Could not toggle persist ({e})")

            # Change 5: Use keyboard shortcuts
            print("[GUI]   - Using keyboard shortcuts...")
            self.main_window.set_focus()

            # Press 'r' for run/stop
            pyautogui.press('r')
            time.sleep(self.action_wait)

            # Press 'r' again to toggle back
            pyautogui.press('r')
            time.sleep(self.action_wait)

            print("[GUI] Settings changed successfully")
            return True

        except Exception as e:
            print(f"[GUI] Warning: Some settings could not be changed: {e}")
            return False

    def save_settings(self, filename: str):
        if os.path.exists(filename):
            os.remove(filename)
            print(f"File '{filename}' removed successfully.")
        else:
            print(f"File '{filename}' does not exist.")

        """Save settings via File menu."""
        print(f"[GUI] Saving settings to {filename}...")

        try:
            # Set focus
            self.main_window.set_focus()
            time.sleep(self.action_wait)

            # Use keyboard shortcut Ctrl+S or File menu
            # Try keyboard shortcut first
            print("[GUI]   - Using Ctrl+S...")
            pyautogui.hotkey('ctrl', 's')
            time.sleep(self.action_wait * 2)

            # Type filename (the save dialog should be open)
            print(f"[GUI]   - Typing filename: {filename}")
            pyautogui.write(str(filename), interval=0.05)
            time.sleep(self.action_wait)

            # Press Enter to save
            print("[GUI]   - Pressing Enter to save...")
            pyautogui.press('enter')
            time.sleep(self.action_wait * 2)

            # Check if file was created
            settings_path = Path(filename)
            if settings_path.exists():
                print(f"[GUI] Settings saved successfully: {settings_path}")
                return True
            else:
                print(f"[GUI] Warning: Settings file not found at {settings_path}")
                return False

        except Exception as e:
            print(f"[GUI] Error saving settings: {e}")
            import traceback
            traceback.print_exc()
            return False

    def load_settings(self, filename: str):
        """Load settings via File menu."""
        print(f"[GUI] Loading settings from {filename}...")

        try:
            # Set focus
            self.main_window.set_focus()
            time.sleep(self.action_wait)

            # Use keyboard shortcut Ctrl+O or File menu
            print("[GUI]   - Using Ctrl+O...")
            pyautogui.hotkey('ctrl', 'o')
            time.sleep(self.action_wait * 2)

            # Type filename
            print(f"[GUI]   - Typing filename: {filename}")
            pyautogui.write(str(filename), interval=0.05)
            time.sleep(self.action_wait)

            # Press Enter to load, then again to accept "OK" dialog box
            print("[GUI]   - Pressing Enter to load...")
            pyautogui.press('enter')
            time.sleep(self.action_wait * 2)
            pyautogui.press('enter')
            time.sleep(self.action_wait * 1)

            print("[GUI] Settings loaded")

            return True

        except Exception as e:
            print(f"[GUI] Error loading settings: {e}")
            import traceback
            traceback.print_exc()
            return False


# === Main Test Class ===

class SettingsTest:
    """Settings save/load test runner."""

    def __init__(self, config: Dict):
        self.config = config
        self.dummy_server: Optional[DummyServerManager] = None
        self.gui_process: Optional[subprocess.Popen] = None
        self.gui_controller: Optional[GUIController] = None
        self.screenshot_manager = ScreenshotManager(
            config["screenshot_dir"],
            border_adjustment=config["border_adjustment"]
        )

    def run(self):
        """Run the complete settings test."""
        print("\n" + "=" * 80)
        print(" HaasoscopeProQt Settings Save/Load Test")
        print("=" * 80 + "\n")

        if not PYWINAUTO_AVAILABLE:
            print("[ERROR] This test requires pywinauto for GUI automation")
            print("[ERROR] Install with: pip install pywinauto")
            return False

        try:
            # Phase 1: Create baseline
            print("\n" + "-" * 80)
            print(" Phase 1: Create Baseline with Custom Settings")
            print("-" * 80 + "\n")

            self._start_server()
            self._launch_gui()

            # Connect to GUI
            self.gui_controller = GUIController(self.gui_process, self.config["action_wait"])
            self.gui_controller.connect()

            # Change settings
            self.gui_controller.change_settings()
            time.sleep(1.0)

            # Take baseline screenshot
            print("[TEST] Taking baseline screenshots...")
            baseline_screenshots = self.screenshot_manager.capture_windows("baseline")
            if not baseline_screenshots:
                print("[ERROR] Failed to capture baseline screenshots")
                return False
            print(f"[TEST] Captured {len(baseline_screenshots)} baseline screenshot(s)")

            # Save settings
            settings_file = self.config["settings_file"]+".json"
            if not self.gui_controller.save_settings(settings_file):
                print("[ERROR] Failed to save settings")
                return False

            # Verify settings file exists
            settings_path = Path(settings_file)
            if not settings_path.exists():
                print(f"[ERROR] Settings file not found: {settings_file}")
                return False

            print(f"[TEST] Settings file created: {settings_path} ({settings_path.stat().st_size} bytes)")

            # Clean up
            self._cleanup()

            # Phase 2: Load and verify
            print("\n" + "-" * 80)
            print(" Phase 2: Restart, Load Settings, and Verify")
            print("-" * 80 + "\n")

            time.sleep(2.0)  # Wait before restarting

            self._start_server()
            self._launch_gui()

            # Connect to GUI again
            self.gui_controller = GUIController(self.gui_process, self.config["action_wait"])
            self.gui_controller.connect()

            # Load settings
            if not self.gui_controller.load_settings(str(settings_path)):
                print("[ERROR] Failed to load settings")
                return False

            time.sleep(1.0)  # Wait for settings to apply

            # Take post-load screenshot
            print("[TEST] Taking post-load screenshots...")
            loaded_screenshots = self.screenshot_manager.capture_windows("loaded")
            if not loaded_screenshots:
                print("[ERROR] Failed to capture loaded screenshots")
                return False
            print(f"[TEST] Captured {len(loaded_screenshots)} loaded screenshot(s)")

            # Compare screenshots
            print("\n" + "-" * 80)
            print(" Phase 3: Compare Results")
            print("-" * 80 + "\n")

            result = self.screenshot_manager.compare_screenshots(
                "baseline", "loaded", threshold=self.config["comparison_threshold"]
            )

            print(f"[TEST] Baseline vs Loaded:")
            print(f"[TEST]   Difference: {result['difference_percent']:.2f}%")
            print(f"[TEST]   Threshold: {self.config['comparison_threshold'] * 100:.2f}%")

            if result['within_threshold']:
                print("\n" + "=" * 80)
                print(" ✓ TEST PASSED")
                print("=" * 80)
                print("\nSettings were saved and restored correctly!")
                print(f"Screenshots match within {self.config['comparison_threshold'] * 100}% threshold")
                return True
            else:
                print("\n" + "=" * 80)
                print(" ✗ TEST FAILED")
                print("=" * 80)
                print("\nSettings were NOT restored correctly!")
                print(f"Difference ({result['difference_percent']:.2f}%) exceeds threshold")
                print(f"Diff image: {result.get('diff_image', 'N/A')}")
                return False

        except Exception as e:
            print(f"\n[ERROR] Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            return False

        finally:
            self._cleanup()

    def _start_server(self):
        """Start the dummy server."""
        self.dummy_server = DummyServerManager(
            port=self.config["port"],
            host=self.config["host"]
        )
        self.dummy_server.start()

    def _launch_gui(self):
        """Launch the GUI application."""
        print("[GUI] Launching HaasoscopeProQt...")

        gui_script = Path(__file__).parent.parent / "HaasoscopeProQt.py"
        if not gui_script.exists():
            raise FileNotFoundError(f"GUI script not found at {gui_script}")

        socket_addr = f"{self.config['host']}:{self.config['port']}"

        self.gui_process = subprocess.Popen(
            [sys.executable, str(gui_script), "--socket", socket_addr, "--max-devices", "0", "--testing"],
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )

        print(f"[GUI] Launched (PID {self.gui_process.pid})")
        print(f"[GUI] Waiting {self.config['init_wait']}s for initialization...")
        time.sleep(self.config['init_wait'])

    def _cleanup(self):
        """Clean up processes."""
        print("\n[CLEANUP] Stopping processes...")

        # Stop GUI
        if self.gui_process and self.gui_process.poll() is None:
            print("[CLEANUP] Stopping GUI...")
            self.gui_process.terminate()
            try:
                self.gui_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("[CLEANUP] GUI didn't stop, killing...")
                self.gui_process.kill()
                self.gui_process.wait()

        # Stop server
        if self.dummy_server:
            self.dummy_server.stop()

        self.gui_controller = None
        time.sleep(1.0)


# === Main ===

def main():
    parser = argparse.ArgumentParser(
        description='Settings save/load test for HaasoscopeProQt',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This test:
1. Starts HaasoscopeProQt
2. Changes GUI settings
3. Saves settings to a file
4. Takes baseline screenshots
5. Restarts the program
6. Loads the settings file
7. Compares screenshots to verify settings were restored

Requires: pywinauto (Windows only)
        """
    )

    parser.add_argument('--port', type=int, default=DEFAULT_CONFIG["port"],
                        help=f'Dummy server port (default: {DEFAULT_CONFIG["port"]})')
    parser.add_argument('--border', type=int, default=DEFAULT_CONFIG["border_adjustment"],
                        help=f'Border adjustment in pixels (default: {DEFAULT_CONFIG["border_adjustment"]})')
    parser.add_argument('--threshold', type=float, default=DEFAULT_CONFIG["comparison_threshold"],
                        help=f'Comparison threshold 0-1 (default: {DEFAULT_CONFIG["comparison_threshold"]})')
    parser.add_argument('--settings-file', type=str, default=DEFAULT_CONFIG["settings_file"],
                        help=f'Settings filename (default: {DEFAULT_CONFIG["settings_file"]})')

    args = parser.parse_args()

    # Build config
    config = DEFAULT_CONFIG.copy()
    config.update({
        "port": args.port,
        "border_adjustment": args.border,
        "comparison_threshold": args.threshold,
        "settings_file": args.settings_file,
    })

    # Run test
    test = SettingsTest(config)
    success = test.run()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
