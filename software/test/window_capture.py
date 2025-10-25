"""
Window capture utilities for GUI testing.

Provides functions to find and capture screenshots of specific application windows
rather than full-screen captures, making tests more focused and reliable.
"""

import sys
from pathlib import Path
from typing import List, Tuple, Optional
from PIL import Image
import pyautogui


def find_haasoscope_windows() -> List[Tuple[str, Tuple[int, int, int, int]]]:
    """
    Find all HaasoscopeProQt windows and their screen positions.

    Returns:
        List of tuples: [(window_title, (left, top, width, height)), ...]
    """
    windows = []

    try:
        # Try using pygetwindow (cross-platform, but optional dependency)
        import pygetwindow as gw

        # Find all windows with "Haasoscope" in the title
        all_windows = gw.getAllWindows()
        for window in all_windows:
            if window.title and 'Haasoscope' in window.title:
                if window.visible and window.width > 0 and window.height > 0:
                    windows.append((
                        window.title,
                        (window.left, window.top, window.width, window.height)
                    ))

        return windows

    except ImportError:
        # Fallback: Use platform-specific window enumeration
        if sys.platform == 'win32':
            return _find_windows_win32()
        else:
            print("Warning: pygetwindow not available, falling back to full screen capture")
            return []


def _find_windows_win32() -> List[Tuple[str, Tuple[int, int, int, int]]]:
    """Windows-specific window enumeration using win32gui."""
    windows = []

    try:
        import win32gui

        def callback(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and 'Haasoscope' in title:
                    try:
                        rect = win32gui.GetWindowRect(hwnd)
                        left, top, right, bottom = rect
                        width = right - left
                        height = bottom - top
                        if width > 0 and height > 0:
                            results.append((title, (left, top, width, height)))
                    except:
                        pass

        win32gui.EnumWindows(callback, windows)

    except ImportError:
        print("Warning: win32gui not available")

    return windows


def capture_haasoscope_windows(save_dir: Path, prefix: str = "window") -> List[Path]:
    """
    Capture screenshots of all HaasoscopeProQt windows.

    Args:
        save_dir: Directory to save screenshots
        prefix: Prefix for screenshot filenames

    Returns:
        List of paths to saved screenshot files
    """
    save_dir.mkdir(exist_ok=True, parents=True)
    screenshots = []

    windows = find_haasoscope_windows()

    if not windows:
        # Fallback to full screen if no specific windows found
        print("No HaasoscopeProQt windows found, capturing full screen")
        filepath = save_dir / f"{prefix}_fullscreen.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(str(filepath))
        screenshots.append(filepath)
        return screenshots

    # Capture each window
    for i, (title, region) in enumerate(windows):
        # Clean title for filename
        clean_title = title.replace(' ', '_').replace('/', '_').replace('\\', '_')
        clean_title = ''.join(c for c in clean_title if c.isalnum() or c in ('_', '-'))

        filename = f"{prefix}_{i:02d}_{clean_title}.png"
        filepath = save_dir / filename

        # Capture the window region
        left, top, width, height = region
        try:
            screenshot = pyautogui.screenshot(region=(left, top, width, height))
            screenshot.save(str(filepath))
            screenshots.append(filepath)
            print(f"  Captured window: {title} -> {filename}")
        except Exception as e:
            print(f"  Warning: Failed to capture {title}: {e}")

    return screenshots


def capture_main_window_only(save_dir: Path, filename: str = "main_window.png") -> Optional[Path]:
    """
    Capture only the main HaasoscopeProQt window (not child windows).

    Args:
        save_dir: Directory to save screenshot
        filename: Filename for the screenshot

    Returns:
        Path to saved screenshot, or None if not found
    """
    save_dir.mkdir(exist_ok=True, parents=True)

    windows = find_haasoscope_windows()

    # Find the main window (typically has "Haasoscope Pro Qt" as exact or partial match)
    main_window = None
    for title, region in windows:
        # Main window typically has the base title
        if 'Haasoscope Pro Qt' in title or title == 'Haasoscope Pro':
            main_window = (title, region)
            break

    # If not found by exact match, use the first window
    if not main_window and windows:
        main_window = windows[0]

    if main_window:
        title, region = main_window
        filepath = save_dir / filename

        left, top, width, height = region
        try:
            screenshot = pyautogui.screenshot(region=(left, top, width, height))
            screenshot.save(str(filepath))
            print(f"  Captured main window: {title}")
            return filepath
        except Exception as e:
            print(f"  Warning: Failed to capture main window: {e}")
            return None

    # Fallback to full screen
    print("  Warning: Main window not found, capturing full screen")
    filepath = save_dir / filename
    screenshot = pyautogui.screenshot()
    screenshot.save(str(filepath))
    return filepath


if __name__ == "__main__":
    # Test the window finding
    print("Searching for HaasoscopeProQt windows...")
    windows = find_haasoscope_windows()

    if windows:
        print(f"Found {len(windows)} window(s):")
        for title, region in windows:
            print(f"  - {title}: {region}")
    else:
        print("No HaasoscopeProQt windows found")
