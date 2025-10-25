#!/usr/bin/env python3
"""
HaasoscopeProQt GUI Test Script

Automated testing for HaasoscopeProQt using the dummy oscilloscope server.
Tests the GUI with deterministic, reproducible waveforms for reliable screenshot comparison.

Usage:
    cd test

    # Run basic test (launches GUI for 10 seconds, takes screenshots)
    python test_gui.py

    # Create baseline screenshots for comparison
    python test_gui.py --baseline

    # Run comparison test (compare to baseline)
    python test_gui.py --compare

    # Customize options
    python test_gui.py --duration 20 --port 9999 --border 10

Requirements:
    pip install pyautogui pillow pygetwindow

Optional:
    pip install pywinauto  # For advanced GUI automation (Windows only)
"""

import sys
import time
import subprocess
import argparse
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime

# For screenshots
import pyautogui
from PIL import Image, ImageChops
import numpy as np


# === Configuration ===
DEFAULT_CONFIG = {
    "port": 9999,
    "host": "localhost",
    "init_wait": 3.0,  # seconds to wait for GUI initialization
    "duration": 10.0,  # seconds to run test
    "screenshot_dir": "screenshots",
    "baseline_dir": "screenshots/baseline",
    "border_adjustment": 8,  # pixels to remove from window edges (Windows shadow)
    "comparison_threshold": 0.05,  # 5% difference allowed
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

    def __init__(self, screenshot_dir: str, baseline_dir: str, border_adjustment: int = 8):
        self.screenshot_dir = Path(screenshot_dir)
        self.baseline_dir = Path(baseline_dir)
        self.border_adjustment = border_adjustment
        self.screenshot_dir.mkdir(exist_ok=True, parents=True)
        self.baseline_dir.mkdir(exist_ok=True, parents=True)
        self.screenshots = {}

    def capture_windows(self, name: str = "test") -> List[Path]:
        """Capture all HaasoscopeProQt windows."""
        try:
            from window_capture import capture_haasoscope_windows

            screenshots = capture_haasoscope_windows(
                self.screenshot_dir, prefix=name, border_adjustment=self.border_adjustment
            )

            # Store first screenshot for baseline comparison
            if screenshots:
                self.screenshots[name] = screenshots[0]

            return screenshots

        except Exception as e:
            print(f"[SCREENSHOT] Warning: Window capture failed: {e}")
            # Fallback to full screen
            return self._capture_fullscreen(name)

    def _capture_fullscreen(self, name: str) -> List[Path]:
        """Fallback: Capture full screen."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{name}.png"
        filepath = self.screenshot_dir / filename

        screenshot = pyautogui.screenshot()
        screenshot.save(str(filepath))

        self.screenshots[name] = filepath
        return [filepath]

    def save_as_baseline(self, screenshot_name: str):
        """Save a screenshot as the baseline."""
        if screenshot_name not in self.screenshots:
            raise ValueError(f"Screenshot {screenshot_name} not found")

        src = self.screenshots[screenshot_name]
        dst = self.baseline_dir / f"{screenshot_name}.png"

        Image.open(src).save(str(dst))
        print(f"[BASELINE] Saved: {screenshot_name}.png")

    def compare_to_baseline(self, screenshot_name: str, threshold: float = 0.05) -> Optional[Dict]:
        """Compare a screenshot to its baseline."""
        if screenshot_name not in self.screenshots:
            raise ValueError(f"Screenshot {screenshot_name} not found")

        baseline_path = self.baseline_dir / f"{screenshot_name}.png"
        if not baseline_path.exists():
            print(f"[COMPARE] No baseline found for {screenshot_name}")
            return None

        current_path = self.screenshots[screenshot_name]

        # Load images
        img1 = Image.open(baseline_path).convert('RGB')
        img2 = Image.open(current_path).convert('RGB')

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
        diff_path = self.screenshot_dir / f"diff_{screenshot_name}.png"
        diff.save(str(diff_path))

        within_threshold = difference_percent < (threshold * 100)

        return {
            'match': difference_percent == 0,
            'difference_percent': difference_percent,
            'within_threshold': within_threshold,
            'diff_image': diff_path
        }


# === Main Test Class ===

class GUITest:
    """Main GUI test runner."""

    def __init__(self, config: Dict):
        self.config = config
        self.dummy_server: Optional[DummyServerManager] = None
        self.gui_process: Optional[subprocess.Popen] = None
        self.screenshot_manager = ScreenshotManager(
            config["screenshot_dir"],
            config["baseline_dir"],
            border_adjustment=config["border_adjustment"]
        )

    def run(self, mode: str = "test"):
        """
        Run the test.

        Args:
            mode: "test" (basic test), "baseline" (create baselines), or "compare" (compare to baseline)
        """
        print("\n" + "=" * 80)
        print(f" HaasoscopeProQt GUI Test - Mode: {mode.upper()}")
        print("=" * 80 + "\n")

        try:
            # Start dummy server
            self._start_server()

            # Launch GUI
            self._launch_gui()

            # Wait for initialization
            print(f"[TEST] Waiting {self.config['init_wait']}s for initialization...")
            time.sleep(self.config['init_wait'])

            # Check GUI is running
            if self.gui_process.poll() is not None:
                print("[TEST] ERROR: GUI process terminated unexpectedly")
                return False

            # Run test
            print(f"[TEST] Running for {self.config['duration']}s...")
            time.sleep(self.config['duration'])

            # Take screenshots
            print("[TEST] Capturing screenshots...")
            screenshots = self.screenshot_manager.capture_windows(name="gui_test")

            if screenshots:
                print(f"[TEST] Captured {len(screenshots)} screenshot(s)")
                for screenshot in screenshots:
                    print(f"  - {screenshot.name}")
            else:
                print("[TEST] No screenshots captured")
                return False

            # Handle different modes
            if mode == "baseline":
                self.screenshot_manager.save_as_baseline("gui_test")
                print("[TEST] Baseline created successfully")
                return True

            elif mode == "compare":
                print("[TEST] Comparing to baseline...")
                result = self.screenshot_manager.compare_to_baseline(
                    "gui_test", threshold=self.config["comparison_threshold"]
                )

                if result is None:
                    print("[TEST] No baseline available for comparison")
                    return False

                print(f"[TEST] Difference: {result['difference_percent']:.2f}%")
                print(f"[TEST] Threshold: {self.config['comparison_threshold'] * 100:.2f}%")

                if result['within_threshold']:
                    print("[TEST] ✓ PASS - Within threshold")
                    return True
                else:
                    print("[TEST] ✗ FAIL - Exceeds threshold")
                    print(f"[TEST] Diff image saved: {result['diff_image']}")
                    return False

            else:  # mode == "test"
                print("[TEST] Test completed successfully")
                return True

        except Exception as e:
            print(f"[TEST] ERROR: {e}")
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

        print("[CLEANUP] Done\n")


# === Main ===

def main():
    parser = argparse.ArgumentParser(
        description='Automated GUI testing for HaasoscopeProQt',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_gui.py                    # Run basic test
  python test_gui.py --baseline         # Create baseline screenshots
  python test_gui.py --compare          # Compare to baseline
  python test_gui.py --duration 20      # Run for 20 seconds
  python test_gui.py --border 10        # Adjust window border (if seeing extra pixels)
        """
    )

    parser.add_argument('--baseline', action='store_true',
                        help='Create baseline screenshots (for future comparisons)')
    parser.add_argument('--compare', action='store_true',
                        help='Compare screenshots to baseline')
    parser.add_argument('--duration', type=float, default=DEFAULT_CONFIG["duration"],
                        help=f'Test duration in seconds (default: {DEFAULT_CONFIG["duration"]})')
    parser.add_argument('--port', type=int, default=DEFAULT_CONFIG["port"],
                        help=f'Dummy server port (default: {DEFAULT_CONFIG["port"]})')
    parser.add_argument('--border', type=int, default=DEFAULT_CONFIG["border_adjustment"],
                        help=f'Border adjustment in pixels (default: {DEFAULT_CONFIG["border_adjustment"]})')
    parser.add_argument('--threshold', type=float, default=DEFAULT_CONFIG["comparison_threshold"],
                        help=f'Comparison threshold 0-1 (default: {DEFAULT_CONFIG["comparison_threshold"]})')

    args = parser.parse_args()

    # Determine mode
    if args.baseline:
        mode = "baseline"
    elif args.compare:
        mode = "compare"
    else:
        mode = "test"

    # Build config
    config = DEFAULT_CONFIG.copy()
    config.update({
        "duration": args.duration,
        "port": args.port,
        "border_adjustment": args.border,
        "comparison_threshold": args.threshold,
    })

    # Run test
    test = GUITest(config)
    success = test.run(mode=mode)

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
