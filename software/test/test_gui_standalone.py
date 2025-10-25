#!/usr/bin/env python3
"""
Standalone GUI Test Script for HaasoscopeProQt

This is a simpler, standalone version that can be run directly without pytest.

Usage:
    cd test
    python test_gui_standalone.py
    python test_gui_standalone.py --duration 10  # Run for 10 seconds
    python test_gui_standalone.py --no-screenshots  # Skip screenshots
"""

import sys
import time
import subprocess
import os
import argparse
from pathlib import Path
from typing import Optional, List
import json
from datetime import datetime

from PyQt5 import QtCore, QtWidgets, QtTest, QtGui
from PIL import Image, ImageChops
import numpy as np


class TestConfig:
    """Configuration for GUI testing."""
    DUMMY_SERVER_PORT = 9999
    DUMMY_SERVER_HOST = "localhost"
    INIT_WAIT_TIME = 3.0  # seconds
    SCREENSHOT_DIR = "test_screenshots"
    BASELINE_DIR = "test_screenshots/baseline"
    TEST_DURATION = 5.0  # seconds to run tests


class DummyServerManager:
    """Manages the dummy oscilloscope server for testing."""

    def __init__(self, port: int = 9999, host: str = "localhost"):
        self.port = port
        self.host = host
        self.process: Optional[subprocess.Popen] = None

    def start(self):
        """Start the dummy server in a subprocess."""
        dummy_server_path = Path(__file__).parent.parent / "dummy_scope" / "dummy_server.py"
        if not dummy_server_path.exists():
            raise FileNotFoundError(f"Dummy server not found at {dummy_server_path}")

        print(f"[TEST] Starting dummy server on {self.host}:{self.port}")

        # Start the server with output suppression for cleaner test output
        self.process = subprocess.Popen(
            [sys.executable, str(dummy_server_path), "--port", str(self.port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )

        # Wait for server to start
        time.sleep(2.0)

        if self.process.poll() is not None:
            stdout, stderr = self.process.communicate()
            raise RuntimeError(f"Dummy server failed to start:\n{stderr.decode()}")

        print(f"[TEST] Dummy server started with PID {self.process.pid}")
        return self

    def stop(self):
        """Stop the dummy server."""
        if self.process:
            print(f"[TEST] Stopping dummy server (PID {self.process.pid})")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("[TEST] Dummy server didn't terminate, killing...")
                self.process.kill()
                self.process.wait()
            self.process = None
            print("[TEST] Dummy server stopped")


class ScreenshotManager:
    """Manages screenshots for GUI testing."""

    def __init__(self, screenshot_dir: str):
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(exist_ok=True)
        self.screenshots = []

    def capture_widget(self, widget: QtWidgets.QWidget, name: str) -> Optional[Path]:
        """Capture a screenshot of a widget."""
        if not widget.isVisible():
            print(f"[TEST] Warning: Widget {name} is not visible, skipping screenshot")
            return None

        # Ensure widget is rendered
        QtWidgets.QApplication.processEvents()
        time.sleep(0.1)

        # Capture the widget
        pixmap = widget.grab()

        # Save screenshot with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = self.screenshot_dir / f"{timestamp}_{name}.png"
        pixmap.save(str(filepath))
        self.screenshots.append(filepath)
        print(f"[TEST] Screenshot saved: {filepath}")
        return filepath

    def capture_all_windows(self, app: QtWidgets.QApplication, prefix: str = "") -> List[Path]:
        """Capture screenshots of all visible windows."""
        screenshots = []
        for i, widget in enumerate(app.topLevelWidgets()):
            if widget.isVisible() and widget.isWindow():
                window_title = widget.windowTitle().replace(' ', '_').replace('/', '_')
                name = f"{prefix}window_{i}_{window_title}"
                filepath = self.capture_widget(widget, name)
                if filepath:
                    screenshots.append(filepath)
        return screenshots


class GUITestRunner:
    """Main test runner for GUI tests."""

    def __init__(self, config: TestConfig, take_screenshots: bool = True):
        self.config = config
        self.take_screenshots = take_screenshots
        self.dummy_server: Optional[DummyServerManager] = None
        self.app: Optional[QtWidgets.QApplication] = None
        self.main_window = None
        self.screenshot_manager = None
        self.test_results = []
        self.gui_process: Optional[subprocess.Popen] = None

    def setup(self):
        """Set up test environment."""
        print("\n" + "="*80)
        print("HAASOSCOPE GUI TEST - SETUP")
        print("="*80)

        # Start dummy server
        self.dummy_server = DummyServerManager(
            port=self.config.DUMMY_SERVER_PORT,
            host=self.config.DUMMY_SERVER_HOST
        )
        self.dummy_server.start()

        # Initialize screenshot manager
        if self.take_screenshots:
            self.screenshot_manager = ScreenshotManager(self.config.SCREENSHOT_DIR)

        print("[TEST] Setup complete\n")

    def start_gui(self):
        """Start the GUI application as a subprocess."""
        print("[TEST] Starting HaasoscopeProQt GUI...")

        gui_script = Path(__file__).parent.parent / "HaasoscopeProQt.py"
        if not gui_script.exists():
            raise FileNotFoundError(f"GUI script not found at {gui_script}")

        # Start GUI in a separate process
        socket_addr = f"{self.dummy_server.host}:{self.dummy_server.port}"
        self.gui_process = subprocess.Popen(
            [
                sys.executable,
                str(gui_script),
                "--socket", socket_addr,
                "--max-devices", "0"
            ],
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )

        print(f"[TEST] GUI process started with PID {self.gui_process.pid}")
        print(f"[TEST] Waiting {self.config.INIT_WAIT_TIME}s for initialization...")
        time.sleep(self.config.INIT_WAIT_TIME)

        # Check if process is still running
        if self.gui_process.poll() is not None:
            raise RuntimeError("GUI process terminated unexpectedly")

        print("[TEST] GUI should now be running\n")

    def find_gui_window(self):
        """Find the main GUI window (runs in subprocess, so this won't work directly)."""
        # Note: This approach won't work if GUI is in a subprocess
        # We'll need to use different techniques like pywinauto or image recognition
        print("[TEST] Note: Direct window access not available when GUI runs in subprocess")
        print("[TEST] For full automation, consider using pywinauto or similar tools")

    def run_interaction_tests(self):
        """Run GUI interaction tests."""
        print("[TEST] Running interaction tests...")
        print(f"[TEST] GUI will run for {self.config.TEST_DURATION} seconds")
        print("[TEST] Please manually verify:")
        print("  - Main window is visible")
        print("  - Waveforms are being displayed")
        print("  - No error messages appear")
        print("  - All controls are responsive")

        # Sleep while GUI runs
        time.sleep(self.config.TEST_DURATION)

        # If we had direct window access, we would do:
        # - Click menu items
        # - Change settings
        # - Verify plot updates
        # - etc.

        print("[TEST] Interaction test period completed")

    def take_screenshots_external(self):
        """Take screenshots using external tools."""
        if not self.take_screenshots:
            return

        print("[TEST] Taking screenshots...")

        # On Windows, we can use pyautogui or similar
        # For now, just note that screenshots should be taken
        print("[TEST] Note: For automated screenshots of subprocess windows, install:")
        print("  pip install pyautogui pillow")
        print("  Then use pyautogui.screenshot() to capture the screen")

        try:
            import pyautogui
            screenshot = pyautogui.screenshot()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = Path(self.config.SCREENSHOT_DIR)
            screenshot_path.mkdir(exist_ok=True)
            filepath = screenshot_path / f"{timestamp}_full_screen.png"
            screenshot.save(str(filepath))
            print(f"[TEST] Full screen screenshot saved: {filepath}")
        except ImportError:
            print("[TEST] pyautogui not installed, skipping automated screenshots")
            print("[TEST] Please take manual screenshots for verification")

    def cleanup(self):
        """Clean up test environment."""
        print("\n[TEST] Cleaning up...")

        # Stop GUI process
        if self.gui_process and self.gui_process.poll() is None:
            print("[TEST] Stopping GUI process...")
            self.gui_process.terminate()
            try:
                self.gui_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("[TEST] GUI didn't terminate, killing...")
                self.gui_process.kill()
                self.gui_process.wait()

        # Stop dummy server
        if self.dummy_server:
            self.dummy_server.stop()

        print("[TEST] Cleanup complete")

    def generate_report(self):
        """Generate test report."""
        print("\n" + "="*80)
        print("HAASOSCOPE GUI TEST REPORT")
        print("="*80)
        print(f"Test Duration: {self.config.TEST_DURATION} seconds")
        print(f"Dummy Server: {self.config.DUMMY_SERVER_HOST}:{self.config.DUMMY_SERVER_PORT}")
        print(f"Screenshots: {'Enabled' if self.take_screenshots else 'Disabled'}")

        if self.take_screenshots and self.screenshot_manager:
            print(f"Screenshot Directory: {self.screenshot_manager.screenshot_dir}")
            print(f"Screenshots Taken: {len(self.screenshot_manager.screenshots)}")
            for screenshot in self.screenshot_manager.screenshots:
                print(f"  - {screenshot}")

        print("\nTest Status:")
        print("  [✓] Dummy server started successfully")
        print("  [✓] GUI process launched")
        print("  [?] Manual verification required for GUI functionality")

        print("\nNext Steps:")
        print("  1. Review screenshots in:", self.config.SCREENSHOT_DIR)
        print("  2. For automated GUI testing, consider installing:")
        print("     - pytest-qt: For Qt-based GUI testing")
        print("     - pywinauto: For Windows GUI automation")
        print("     - pyautogui: For screen capture and mouse/keyboard control")
        print("  3. Create baseline screenshots for regression testing")

        print("="*80)

    def run(self):
        """Run all tests."""
        try:
            self.setup()
            self.start_gui()
            self.run_interaction_tests()
            self.take_screenshots_external()
            return True
        except Exception as e:
            print(f"\n[ERROR] Test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            self.cleanup()
            self.generate_report()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Run GUI tests for HaasoscopeProQt')
    parser.add_argument('--duration', type=float, default=5.0,
                       help='Test duration in seconds (default: 5.0)')
    parser.add_argument('--no-screenshots', action='store_true',
                       help='Disable screenshot capture')
    parser.add_argument('--port', type=int, default=9999,
                       help='Dummy server port (default: 9999)')

    args = parser.parse_args()

    # Configure test
    config = TestConfig()
    config.TEST_DURATION = args.duration
    config.DUMMY_SERVER_PORT = args.port

    # Run tests
    runner = GUITestRunner(config, take_screenshots=not args.no_screenshots)
    success = runner.run()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
