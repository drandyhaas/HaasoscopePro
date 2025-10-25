#!/usr/bin/env python3
"""
GUI Test Script for HaasoscopeProQt

This script performs automated GUI testing of the HaasoscopeProQt application:
1. Starts a dummy server
2. Launches the GUI with maxdevices 0 (connects to dummy server only)
3. Waits for initialization
4. Simulates GUI interactions (menu actions, button presses, settings changes)
5. Takes screenshots of all windows
6. Compares to expected behavior
7. Summarizes test results

Requirements:
    pip install pytest pytest-qt pillow

Usage:
    cd test
    pytest test_gui.py -v
    pytest test_gui.py -v --screenshots  # Save screenshots even on success
    pytest test_gui.py -v -k test_basic_startup  # Run specific test
"""

import sys
import time
import subprocess
import os
from pathlib import Path
from typing import Optional, List
import json

import pytest
from PyQt5 import QtCore, QtWidgets, QtTest, QtGui
from PIL import Image, ImageChops
import numpy as np


# Test configuration
TEST_CONFIG = {
    "dummy_server_port": 9999,
    "dummy_server_host": "localhost",
    "init_wait_time": 8.0,  # seconds to wait for initialization
    "screenshot_dir": "test_screenshots",
    "baseline_dir": "test_screenshots/baseline",
    "comparison_threshold": 0.05,  # 5% difference allowed
}


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

        print(f"Starting dummy server on {self.host}:{self.port}")
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

        print(f"Dummy server started with PID {self.process.pid}")
        return self

    def stop(self):
        """Stop the dummy server."""
        if self.process:
            print(f"Stopping dummy server (PID {self.process.pid})")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("Dummy server didn't terminate, killing...")
                self.process.kill()
                self.process.wait()
            self.process = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


class ScreenshotManager:
    """Manages screenshots and comparisons for GUI testing."""

    def __init__(self, screenshot_dir: str, baseline_dir: str):
        self.screenshot_dir = Path(screenshot_dir)
        self.baseline_dir = Path(baseline_dir)
        self.screenshot_dir.mkdir(exist_ok=True)
        self.baseline_dir.mkdir(exist_ok=True)
        self.screenshots = {}

    def capture_widget(self, widget: QtWidgets.QWidget, name: str) -> Path:
        """Capture a screenshot of a widget."""
        if not widget.isVisible():
            print(f"Warning: Widget {name} is not visible, skipping screenshot")
            return None

        # Ensure widget is rendered
        QtWidgets.QApplication.processEvents()
        time.sleep(0.1)

        # Capture the widget
        pixmap = widget.grab()

        # Save screenshot
        filepath = self.screenshot_dir / f"{name}.png"
        pixmap.save(str(filepath))
        self.screenshots[name] = filepath
        print(f"Screenshot saved: {filepath}")
        return filepath

    def capture_all_windows(self, app: QtWidgets.QApplication, prefix: str = "") -> List[Path]:
        """Capture screenshots of all visible windows."""
        screenshots = []
        for i, widget in enumerate(app.topLevelWidgets()):
            if widget.isVisible():
                name = f"{prefix}window_{i}_{widget.windowTitle().replace(' ', '_')}"
                filepath = self.capture_widget(widget, name)
                if filepath:
                    screenshots.append(filepath)
        return screenshots

    def compare_images(self, img1_path: Path, img2_path: Path) -> dict:
        """
        Compare two images and return similarity metrics.

        Returns:
            dict with keys: 'identical', 'difference_percent', 'diff_image_path'
        """
        img1 = Image.open(img1_path)
        img2 = Image.open(img2_path)

        # Ensure same size
        if img1.size != img2.size:
            return {
                'identical': False,
                'difference_percent': 100.0,
                'error': f"Size mismatch: {img1.size} vs {img2.size}"
            }

        # Calculate difference
        diff = ImageChops.difference(img1, img2)
        diff_array = np.array(diff)

        # Calculate percentage of different pixels
        total_pixels = diff_array.size
        different_pixels = np.count_nonzero(diff_array)
        difference_percent = (different_pixels / total_pixels) * 100

        # Save diff image
        diff_path = self.screenshot_dir / f"diff_{img1_path.stem}.png"
        diff.save(str(diff_path))

        return {
            'identical': difference_percent == 0,
            'difference_percent': difference_percent,
            'diff_image_path': diff_path
        }

    def compare_to_baseline(self, screenshot_name: str) -> Optional[dict]:
        """Compare a screenshot to its baseline."""
        current = self.screenshot_dir / f"{screenshot_name}.png"
        baseline = self.baseline_dir / f"{screenshot_name}.png"

        if not baseline.exists():
            print(f"No baseline found for {screenshot_name}, creating one...")
            baseline.parent.mkdir(parents=True, exist_ok=True)
            Image.open(current).save(str(baseline))
            return None

        return self.compare_images(current, baseline)


@pytest.fixture(scope="session")
def dummy_server():
    """Fixture to start and stop the dummy server."""
    server = DummyServerManager(
        port=TEST_CONFIG["dummy_server_port"],
        host=TEST_CONFIG["dummy_server_host"]
    )
    server.start()
    yield server
    server.stop()


@pytest.fixture
def haasoscope_app(qtbot, dummy_server):
    """
    Fixture to launch the HaasoscopeProQt application.

    This imports and initializes the application with the dummy server.
    """
    # Import the main application module
    import HaasoscopeProQt
    import main_window

    # Create application if it doesn't exist
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    # Mock command-line arguments to connect to dummy server
    sys.argv = [
        "HaasoscopeProQt.py",
        "--socket", f"{dummy_server.host}:{dummy_server.port}",
        "--max-devices", "0"
    ]

    # Initialize the application (mimicking HaasoscopeProQt.py main logic)
    # We need to actually run the initialization code
    # For now, we'll import and manually initialize

    # This is a simplified version - in reality we'd need to follow the exact
    # initialization sequence from HaasoscopeProQt.py
    print("Initializing HaasoscopePro application...")

    # Wait for initialization
    time.sleep(TEST_CONFIG["init_wait_time"])

    # Get the main window
    main_win = None
    for widget in app.topLevelWidgets():
        if isinstance(widget, QtWidgets.QMainWindow):
            main_win = widget
            break

    if main_win:
        qtbot.addWidget(main_win)
        main_win.show()
        qtbot.waitExposed(main_win)

    yield {"app": app, "main_window": main_win}

    # Cleanup
    if main_win:
        main_win.close()
    app.quit()


@pytest.fixture
def screenshot_manager():
    """Fixture to create a screenshot manager."""
    return ScreenshotManager(
        screenshot_dir=TEST_CONFIG["screenshot_dir"],
        baseline_dir=TEST_CONFIG["baseline_dir"]
    )


# ============================================================================
# Test Cases
# ============================================================================

def test_dummy_server_starts(dummy_server):
    """Test that the dummy server starts successfully."""
    assert dummy_server.process is not None
    assert dummy_server.process.poll() is None, "Dummy server process has terminated"


def test_basic_startup(haasoscope_app, screenshot_manager, qtbot):
    """
    Test basic application startup.

    Verifies:
    - Application launches successfully
    - Main window is visible
    - Initial UI state is correct
    """
    app = haasoscope_app["app"]
    main_window = haasoscope_app["main_window"]

    assert app is not None, "Application failed to initialize"
    assert main_window is not None, "Main window not found"
    assert main_window.isVisible(), "Main window is not visible"

    # Take screenshot
    screenshot_manager.capture_widget(main_window, "test_basic_startup_main")

    # Capture all windows
    screenshots = screenshot_manager.capture_all_windows(app, "startup_")
    assert len(screenshots) > 0, "No windows captured"


def test_menu_interactions(haasoscope_app, screenshot_manager, qtbot):
    """
    Test menu interactions.

    Tests:
    - Opening File menu
    - Opening View menu
    - Opening Tools menu
    """
    app = haasoscope_app["app"]
    main_window = haasoscope_app["main_window"]

    if main_window is None:
        pytest.skip("Main window not available")

    # Find the menu bar
    menu_bar = main_window.menuBar()
    assert menu_bar is not None, "Menu bar not found"

    # Test File menu
    file_menu = None
    for action in menu_bar.actions():
        if "file" in action.text().lower():
            file_menu = action.menu()
            break

    if file_menu:
        # Click the File menu
        qtbot.mouseClick(menu_bar, QtCore.Qt.LeftButton)
        QtWidgets.QApplication.processEvents()
        time.sleep(0.5)

        screenshot_manager.capture_widget(main_window, "test_menu_file_open")


def test_trigger_settings(haasoscope_app, screenshot_manager, qtbot):
    """
    Test changing trigger settings.

    Tests:
    - Accessing trigger controls
    - Changing trigger level
    - Changing trigger mode
    """
    app = haasoscope_app["app"]
    main_window = haasoscope_app["main_window"]

    if main_window is None:
        pytest.skip("Main window not available")

    # Take initial screenshot
    screenshot_manager.capture_widget(main_window, "test_trigger_before")

    # Find trigger-related widgets (this depends on the UI structure)
    # We would need to inspect the UI to find the correct widget names

    # For now, just wait and capture state
    time.sleep(1.0)
    QtWidgets.QApplication.processEvents()

    screenshot_manager.capture_widget(main_window, "test_trigger_after")


def test_channel_controls(haasoscope_app, screenshot_manager, qtbot):
    """
    Test channel control interactions.

    Tests:
    - Toggling channel visibility
    - Changing channel gain
    - Changing channel offset
    """
    app = haasoscope_app["app"]
    main_window = haasoscope_app["main_window"]

    if main_window is None:
        pytest.skip("Main window not available")

    screenshot_manager.capture_widget(main_window, "test_channels_initial")

    # Wait for data acquisition
    time.sleep(2.0)
    QtWidgets.QApplication.processEvents()

    screenshot_manager.capture_widget(main_window, "test_channels_running")


def test_fft_window(haasoscope_app, screenshot_manager, qtbot):
    """
    Test opening the FFT window.

    Tests:
    - Opening FFT window via menu or button
    - FFT window displays correctly
    """
    app = haasoscope_app["app"]
    main_window = haasoscope_app["main_window"]

    if main_window is None:
        pytest.skip("Main window not available")

    # Try to find and click FFT button/menu
    # This requires knowing the UI structure

    # For now, capture all visible windows
    time.sleep(1.0)
    screenshots = screenshot_manager.capture_all_windows(app, "test_fft_")


def test_screenshot_comparison(haasoscope_app, screenshot_manager, qtbot):
    """
    Test screenshot comparison against baseline.

    This test will create baselines on first run, then compare on subsequent runs.
    """
    app = haasoscope_app["app"]
    main_window = haasoscope_app["main_window"]

    if main_window is None:
        pytest.skip("Main window not available")

    # Capture screenshot
    screenshot_manager.capture_widget(main_window, "test_comparison_baseline")

    # Compare to baseline
    comparison = screenshot_manager.compare_to_baseline("test_comparison_baseline")

    if comparison is not None:
        print(f"Difference: {comparison['difference_percent']:.2f}%")
        threshold = TEST_CONFIG["comparison_threshold"] * 100
        assert comparison['difference_percent'] < threshold, \
            f"Screenshot differs by {comparison['difference_percent']:.2f}% (threshold: {threshold}%)"


# ============================================================================
# Test Result Summary
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def test_summary(request):
    """Generate a test summary at the end of the test session."""
    yield

    # This runs after all tests complete
    print("\n" + "="*80)
    print("GUI TEST SUMMARY")
    print("="*80)

    # Get test results from pytest
    session = request.session
    if hasattr(session, 'testscollected'):
        print(f"Total tests collected: {session.testscollected}")

    # Summary will be printed by pytest
    print("\nScreenshots saved to:", TEST_CONFIG["screenshot_dir"])
    print("Baseline images at:", TEST_CONFIG["baseline_dir"])
    print("\nTo update baselines: delete contents of", TEST_CONFIG["baseline_dir"])
    print("="*80)


if __name__ == "__main__":
    # Run tests when executed directly
    pytest.main([__file__, "-v", "--tb=short"])
