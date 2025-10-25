"""
Window capture utilities for GUI testing.

Provides functions to find and capture screenshots of specific application windows
rather than full-screen captures, making tests more focused and reliable.

**Border Adjustment:**
On Windows, window coordinates include an invisible border/shadow (typically 7-10 pixels)
added by the Aero window manager. This module automatically adjusts window coordinates
to exclude this border, capturing only the visible window content.

Default adjustment: 8 pixels on each side
To customize: Use border_adjustment parameter (try 10-12 if you still see extra pixels)
To disable: Set border_adjustment=0
"""

import sys
from pathlib import Path
from typing import List, Tuple, Optional
from PIL import Image
import pyautogui


def find_haasoscope_windows(border_size: int = 8) -> List[Tuple[str, Tuple[int, int, int, int]]]:
    """
    Find all HaasoscopeProQt windows and their screen positions.

    Args:
        border_size: Size of invisible border to exclude on Windows (default: 8 pixels)
                    Set to 0 to disable adjustment

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
                    # Get raw window coordinates
                    left, top, width, height = window.left, window.top, window.width, window.height

                    # Adjust for Windows shadow/border (typically 7-10 pixels on each side)
                    if sys.platform == 'win32' and border_size > 0:
                        left, top, width, height = _adjust_for_windows_shadow(
                            left, top, width, height, border_size=border_size
                        )

                    windows.append((window.title, (left, top, width, height)))

        return windows

    except ImportError:
        # Fallback: Use platform-specific window enumeration
        if sys.platform == 'win32':
            return _find_windows_win32(border_size=border_size)
        else:
            print("Warning: pygetwindow not available, falling back to full screen capture")
            return []


def _adjust_for_windows_shadow(left: int, top: int, width: int, height: int,
                                border_size: int = 8) -> Tuple[int, int, int, int]:
    """
    Adjust window coordinates to exclude Windows Aero shadow/invisible border.

    Windows 10/11 adds an invisible border around windows (typically 7-8 pixels on each side)
    for shadow effects. This function adjusts the coordinates to capture only the visible content.

    Args:
        left, top, width, height: Original window coordinates
        border_size: Size of invisible border on each side (default: 8 pixels)

    Returns:
        Adjusted (left, top, width, height) tuple
    """
    # Adjust left and top to skip the invisible border
    adjusted_left = left + border_size
    adjusted_top = top + border_size

    # Reduce width and height to exclude borders on all sides
    adjusted_width = width - (border_size * 2)
    adjusted_height = height - (border_size * 2)

    # Make sure we don't go negative
    if adjusted_width < 1 or adjusted_height < 1:
        # Border adjustment is too large, return original
        return (left, top, width, height)

    return (adjusted_left, adjusted_top, adjusted_width, adjusted_height)


def _find_windows_win32(border_size: int = 8) -> List[Tuple[str, Tuple[int, int, int, int]]]:
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
                            # Adjust for Windows shadow/border
                            if border_size > 0:
                                left, top, width, height = _adjust_for_windows_shadow(
                                    left, top, width, height, border_size=border_size
                                )
                            results.append((title, (left, top, width, height)))
                    except:
                        pass

        win32gui.EnumWindows(callback, windows)

    except ImportError:
        print("Warning: win32gui not available")

    return windows


def capture_haasoscope_windows(save_dir: Path, prefix: str = "window",
                               border_adjustment: int = 8) -> List[Path]:
    """
    Capture screenshots of all HaasoscopeProQt windows.

    Args:
        save_dir: Directory to save screenshots
        prefix: Prefix for screenshot filenames
        border_adjustment: Border size to exclude from window edges on Windows (default: 8 pixels)
                          This removes the invisible Aero shadow/border around windows.
                          Set to 0 to disable adjustment, or 10-12 if you still see extra pixels.

    Returns:
        List of paths to saved screenshot files
    """
    save_dir.mkdir(exist_ok=True, parents=True)
    screenshots = []

    windows = find_haasoscope_windows(border_size=border_adjustment)

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


def capture_main_window_only(save_dir: Path, filename: str = "main_window.png",
                             border_adjustment: int = 8) -> Optional[Path]:
    """
    Capture only the main HaasoscopeProQt window (not child windows).

    Args:
        save_dir: Directory to save screenshot
        filename: Filename for the screenshot
        border_adjustment: Border size to exclude from window edges on Windows (default: 8 pixels)

    Returns:
        Path to saved screenshot, or None if not found
    """
    save_dir.mkdir(exist_ok=True, parents=True)

    windows = find_haasoscope_windows(border_size=border_adjustment)

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
    print("=" * 80)
    print("HaasoscopeProQt Window Capture Test")
    print("=" * 80)
    print()

    print("Searching for HaasoscopeProQt windows...")
    windows = find_haasoscope_windows()

    if windows:
        print(f"Found {len(windows)} window(s):")
        for title, region in windows:
            left, top, width, height = region
            print(f"  - {title}")
            print(f"    Position: ({left}, {top})")
            print(f"    Size: {width} x {height}")
            print()

        print("Default border adjustment: 8 pixels on each side")
        print()
        print("If screenshots still show extra pixels, try:")
        print("  capture_haasoscope_windows(save_dir, border_adjustment=10)")
        print("  capture_haasoscope_windows(save_dir, border_adjustment=12)")
        print()
        print("To disable border adjustment:")
        print("  capture_haasoscope_windows(save_dir, border_adjustment=0)")

    else:
        print("No HaasoscopeProQt windows found")
        print()
        print("Make sure HaasoscopeProQt is running before running this test.")
