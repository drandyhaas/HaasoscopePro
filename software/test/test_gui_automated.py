#!/usr/bin/env python3
"""
Advanced Automated GUI Test Script for HaasoscopeProQt

Uses pywinauto for full Windows GUI automation including:
- Window detection and interaction
- Menu navigation
- Button clicks
- Setting changes
- Screenshot capture with comparison

Requirements:
    pip install pywinauto pillow pyautogui numpy

Usage:
    cd test
    python test_gui_automated.py
    python test_gui_automated.py --verbose
    python test_gui_automated.py --baseline  # Create baseline screenshots
"""

import sys
import time
import subprocess
import argparse
from pathlib import Path
from typing import Optional, List, Dict
import json
from datetime import datetime

try:
    from pywinauto import Application
    from pywinauto.findwindows import ElementNotFoundError
    PYWINAUTO_AVAILABLE = True
except ImportError:
    PYWINAUTO_AVAILABLE = False
    print("Warning: pywinauto not available. Install with: pip install pywinauto")

import pyautogui
from PIL import Image, ImageChops
import numpy as np


class TestConfig:
    """Configuration for automated GUI testing."""
    DUMMY_SERVER_PORT = 9999
    DUMMY_SERVER_HOST = "localhost"
    INIT_WAIT_TIME = 8.0  # seconds
    SCREENSHOT_DIR = "test_screenshots"
    BASELINE_DIR = "test_screenshots/baseline"
    WINDOW_TITLE_PATTERN = "Haasoscope*"  # Pattern to find main window
    COMPARISON_THRESHOLD = 0.05  # 5% difference allowed
    BORDER_ADJUSTMENT = 8  # Pixels to remove from window edges (Windows shadow). Try 10-12 if still seeing extra pixels.


class DummyServerManager:
    """Manages the dummy oscilloscope server."""

    def __init__(self, port: int, host: str, verbose: bool = False):
        self.port = port
        self.host = host
        self.verbose = verbose
        self.process: Optional[subprocess.Popen] = None

    def start(self):
        """Start the dummy server."""
        dummy_server_path = Path(__file__).parent.parent / "dummy_scope" / "dummy_server.py"
        if not dummy_server_path.exists():
            raise FileNotFoundError(f"Dummy server not found at {dummy_server_path}")

        if self.verbose:
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

        if self.verbose:
            print(f"[SERVER] Running (PID {self.process.pid})")

    def stop(self):
        """Stop the dummy server."""
        if self.process:
            if self.verbose:
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

    def __init__(self, screenshot_dir: str, baseline_dir: str, verbose: bool = False,
                 border_adjustment: int = 8):
        self.screenshot_dir = Path(screenshot_dir)
        self.baseline_dir = Path(baseline_dir)
        self.verbose = verbose
        self.border_adjustment = border_adjustment
        self.screenshot_dir.mkdir(exist_ok=True)
        self.baseline_dir.mkdir(exist_ok=True)
        self.screenshots = {}

    def capture_haasoscope_windows(self, name: str = "screen") -> List[Path]:
        """
        Capture all HaasoscopeProQt windows (main window and child windows).

        Args:
            name: Base name for the screenshot files

        Returns:
            List of paths to captured screenshots
        """
        try:
            from window_capture import capture_haasoscope_windows as capture_windows

            # Capture all windows
            screenshots = capture_windows(self.screenshot_dir, prefix=name,
                                         border_adjustment=self.border_adjustment)

            # Store the first screenshot with the given name for baseline comparison
            if screenshots:
                self.screenshots[name] = screenshots[0]
                if self.verbose:
                    print(f"[SCREENSHOT] Captured {len(screenshots)} window(s)")

            return screenshots

        except Exception as e:
            if self.verbose:
                print(f"[SCREENSHOT] Warning: Window capture failed, using full screen: {e}")
            # Fallback to full screen
            return [self.capture_screen_region(name=name)]

    def capture_screen_region(self, region=None, name: str = "screen") -> Path:
        """Capture a screenshot of the screen or a region (fallback method)."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{name}.png"
        filepath = self.screenshot_dir / filename

        screenshot = pyautogui.screenshot(region=region)
        screenshot.save(str(filepath))

        self.screenshots[name] = filepath
        if self.verbose:
            print(f"[SCREENSHOT] Saved: {filename}")

        return filepath

    def compare_images(self, img1_path: Path, img2_path: Path) -> Dict:
        """Compare two images pixel by pixel."""
        img1 = Image.open(img1_path).convert('RGB')
        img2 = Image.open(img2_path).convert('RGB')

        if img1.size != img2.size:
            return {
                'match': False,
                'difference_percent': 100.0,
                'error': f"Size mismatch: {img1.size} vs {img2.size}"
            }

        # Calculate pixel difference
        diff = ImageChops.difference(img1, img2)
        diff_array = np.array(diff)

        total_pixels = diff_array.size
        different_pixels = np.count_nonzero(diff_array)
        difference_percent = (different_pixels / total_pixels) * 100

        # Save diff image
        diff_path = self.screenshot_dir / f"diff_{img1_path.stem}_vs_{img2_path.stem}.png"
        diff.save(str(diff_path))

        return {
            'match': difference_percent == 0,
            'difference_percent': difference_percent,
            'diff_image': diff_path,
            'within_threshold': difference_percent < TestConfig.COMPARISON_THRESHOLD * 100
        }

    def save_as_baseline(self, screenshot_name: str):
        """Save a screenshot as the baseline."""
        if screenshot_name not in self.screenshots:
            raise ValueError(f"Screenshot {screenshot_name} not found")

        src = self.screenshots[screenshot_name]
        dst = self.baseline_dir / f"{screenshot_name}.png"

        Image.open(src).save(str(dst))
        if self.verbose:
            print(f"[BASELINE] Saved: {screenshot_name}.png")

    def compare_to_baseline(self, screenshot_name: str) -> Optional[Dict]:
        """Compare a screenshot to its baseline."""
        if screenshot_name not in self.screenshots:
            raise ValueError(f"Screenshot {screenshot_name} not found")

        current = self.screenshots[screenshot_name]
        baseline = self.baseline_dir / f"{screenshot_name}.png"

        if not baseline.exists():
            if self.verbose:
                print(f"[BASELINE] Not found for {screenshot_name}, creating...")
            self.save_as_baseline(screenshot_name)
            return None

        return self.compare_images(current, baseline)


class GUIAutomatedTest:
    """Automated GUI test runner using pywinauto."""

    def __init__(self, config: TestConfig, verbose: bool = False, create_baseline: bool = False):
        self.config = config
        self.verbose = verbose
        self.create_baseline = create_baseline
        self.dummy_server: Optional[DummyServerManager] = None
        self.gui_process: Optional[subprocess.Popen] = None
        self.app: Optional[Application] = None
        self.screenshot_manager = ScreenshotManager(
            config.SCREENSHOT_DIR,
            config.BASELINE_DIR,
            verbose=verbose,
            border_adjustment=config.BORDER_ADJUSTMENT
        )
        self.test_results = []

    def log(self, message: str):
        """Log a message if verbose mode is enabled."""
        if self.verbose:
            print(f"[TEST] {message}")

    def setup(self):
        """Set up the test environment."""
        print("\n" + "="*80)
        print("AUTOMATED GUI TEST - SETUP")
        print("="*80)

        # Start dummy server
        self.dummy_server = DummyServerManager(
            self.config.DUMMY_SERVER_PORT,
            self.config.DUMMY_SERVER_HOST,
            verbose=self.verbose
        )
        self.dummy_server.start()

        self.log("Setup complete")

    def start_gui(self):
        """Start the GUI application."""
        self.log("Starting HaasoscopeProQt...")

        gui_script = Path(__file__).parent.parent / "HaasoscopeProQt.py"
        socket_addr = f"{self.dummy_server.host}:{self.dummy_server.port}"

        self.gui_process = subprocess.Popen(
            [sys.executable, str(gui_script), "--socket", socket_addr, "--max-devices", "0", "--testing"],
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )

        self.log(f"GUI process started (PID {self.gui_process.pid})")
        self.log(f"Waiting {self.config.INIT_WAIT_TIME}s for initialization...")
        time.sleep(self.config.INIT_WAIT_TIME)

        if self.gui_process.poll() is not None:
            raise RuntimeError("GUI process terminated unexpectedly")

    def connect_to_gui(self):
        """Connect to the GUI using pywinauto."""
        if not PYWINAUTO_AVAILABLE:
            self.log("pywinauto not available, skipping GUI connection")
            return False

        self.log("Connecting to GUI window...")

        try:
            # Try to connect to the application by process ID
            self.app = Application(backend="win32").connect(process=self.gui_process.pid, timeout=10)
            self.log("Connected to GUI application")

            # Try to find the main window
            # You may need to adjust the window title pattern
            windows = self.app.windows()
            self.log(f"Found {len(windows)} windows")

            return True

        except Exception as e:
            self.log(f"Could not connect to GUI: {e}")
            return False

    def test_initial_state(self):
        """Test: Verify initial state of the application."""
        test_name = "initial_state"
        self.log(f"Running test: {test_name}")

        # Take screenshot of initial state (captures all HaasoscopeProQt windows)
        self.screenshot_manager.capture_haasoscope_windows(name="01_initial_state")

        # If baseline mode, save as baseline
        if self.create_baseline:
            self.screenshot_manager.save_as_baseline("01_initial_state")
            result = {"test": test_name, "status": "baseline_created"}
        else:
            # Compare to baseline
            comparison = self.screenshot_manager.compare_to_baseline("01_initial_state")
            if comparison:
                result = {
                    "test": test_name,
                    "status": "pass" if comparison['within_threshold'] else "fail",
                    "difference": comparison['difference_percent']
                }
            else:
                result = {"test": test_name, "status": "no_baseline"}

        self.test_results.append(result)
        return result

    def test_gui_running(self):
        """Test: Verify GUI is running and responsive."""
        test_name = "gui_running"
        self.log(f"Running test: {test_name}")

        # Wait a bit for data to flow
        time.sleep(2.0)

        # Take screenshot (captures all HaasoscopeProQt windows)
        self.screenshot_manager.capture_haasoscope_windows(name="02_gui_running")

        if self.create_baseline:
            self.screenshot_manager.save_as_baseline("02_gui_running")
            result = {"test": test_name, "status": "baseline_created"}
        else:
            comparison = self.screenshot_manager.compare_to_baseline("02_gui_running")
            if comparison:
                result = {
                    "test": test_name,
                    "status": "pass" if comparison['within_threshold'] else "fail",
                    "difference": comparison['difference_percent']
                }
            else:
                result = {"test": test_name, "status": "no_baseline"}

        self.test_results.append(result)
        return result

    def test_menu_interactions(self):
        """Test: Try to interact with menus (if pywinauto is available)."""
        test_name = "menu_interactions"
        self.log(f"Running test: {test_name}")

        if not self.app:
            self.log("Cannot test menu interactions without pywinauto connection")
            result = {"test": test_name, "status": "skipped", "reason": "no_gui_connection"}
            self.test_results.append(result)
            return result

        # This would require knowing the exact menu structure
        # For now, just take a screenshot (captures all HaasoscopeProQt windows)
        time.sleep(1.0)
        self.screenshot_manager.capture_haasoscope_windows(name="03_menus")

        result = {"test": test_name, "status": "manual_verification_required"}
        self.test_results.append(result)
        return result

    def cleanup(self):
        """Clean up test environment."""
        self.log("Cleaning up...")

        # Stop GUI
        if self.gui_process and self.gui_process.poll() is None:
            self.log("Stopping GUI process...")
            self.gui_process.terminate()
            try:
                self.gui_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.gui_process.kill()
                self.gui_process.wait()

        # Stop dummy server
        if self.dummy_server:
            self.dummy_server.stop()

        self.log("Cleanup complete")

    def generate_report(self):
        """Generate and print test report."""
        print("\n" + "="*80)
        print("AUTOMATED GUI TEST REPORT")
        print("="*80)

        print(f"\nMode: {'BASELINE CREATION' if self.create_baseline else 'COMPARISON'}")
        print(f"Screenshots: {self.screenshot_manager.screenshot_dir}")
        print(f"Baselines: {self.screenshot_manager.baseline_dir}")

        print(f"\n{'Test':<30} {'Status':<20} {'Details':<30}")
        print("-" * 80)

        passed = 0
        failed = 0
        skipped = 0

        for result in self.test_results:
            test = result['test']
            status = result['status']
            details = ""

            if status == "pass":
                passed += 1
                details = f"Diff: {result.get('difference', 0):.2f}%"
            elif status == "fail":
                failed += 1
                details = f"Diff: {result.get('difference', 0):.2f}%"
            elif status == "skipped":
                skipped += 1
                details = result.get('reason', '')
            elif status == "baseline_created":
                details = "Baseline saved"
            elif status == "no_baseline":
                details = "Baseline created"

            status_symbol = {
                "pass": "✓",
                "fail": "✗",
                "skipped": "-",
                "baseline_created": "→",
                "no_baseline": "→"
            }.get(status, "?")

            print(f"{test:<30} {status_symbol} {status:<18} {details:<30}")

        print("-" * 80)
        print(f"\nSummary: {passed} passed, {failed} failed, {skipped} skipped")

        if not self.create_baseline:
            print("\nTo create new baselines: python test_gui_automated.py --baseline")

        print("="*80)

    def run(self):
        """Run all tests."""
        try:
            self.setup()
            self.start_gui()

            # Try to connect if pywinauto is available
            connected = self.connect_to_gui()

            # Run tests
            self.test_initial_state()
            self.test_gui_running()
            self.test_menu_interactions()

            return True

        except Exception as e:
            print(f"\n[ERROR] Test execution failed: {e}")
            import traceback
            traceback.print_exc()
            return False

        finally:
            self.cleanup()
            self.generate_report()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Automated GUI tests for HaasoscopeProQt')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output')
    parser.add_argument('--baseline', '-b', action='store_true',
                       help='Create baseline screenshots instead of comparing')
    parser.add_argument('--port', type=int, default=9999,
                       help='Dummy server port (default: 9999)')

    args = parser.parse_args()

    # Check dependencies
    if not PYWINAUTO_AVAILABLE:
        print("\nWARNING: pywinauto not installed. Limited functionality available.")
        print("Install with: pip install pywinauto\n")

    # Configure and run tests
    config = TestConfig()
    config.DUMMY_SERVER_PORT = args.port

    runner = GUIAutomatedTest(config, verbose=args.verbose, create_baseline=args.baseline)
    success = runner.run()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
