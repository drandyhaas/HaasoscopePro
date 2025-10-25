"""
Window capture utilities for GUI testing.

Provides functions to find and capture screenshots of specific application windows
rather than full-screen captures, making tests more focused and reliable.

**Platform-Specific Handling:**

macOS:
- Uses PyObjC/Quartz framework for native window detection
- Requires: pip install pyobjc-framework-Quartz
- No border adjustment needed

Windows:
- Window coordinates include an invisible border/shadow (typically 7-10 pixels)
  added by the Aero window manager
- Default adjustment: 8 pixels on each side
- To customize: Use border_adjustment parameter (try 10-12 if you still see extra pixels)
- To disable: Set border_adjustment=0

Linux:
- Uses pygetwindow if available
- No border adjustment needed
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
    # Use platform-specific methods
    if sys.platform == 'darwin':
        return _find_windows_macos()
    elif sys.platform == 'win32':
        return _find_windows_win32(border_size=border_size)

    # Try pygetwindow for other platforms
    windows = []
    try:
        import pygetwindow as gw

        # Find all windows with "Haasoscope" in the title
        all_windows = gw.getAllWindows()
        for window in all_windows:
            if window.title and 'Haasoscope' in window.title:
                if window.visible and window.width > 0 and window.height > 0:
                    # Get raw window coordinates
                    left, top, width, height = window.left, window.top, window.width, window.height
                    windows.append((window.title, (left, top, width, height)))

        return windows

    except (ImportError, AttributeError) as e:
        print(f"Warning: pygetwindow not available or not supported: {e}")
        return []


def _find_windows_macos() -> List[Tuple[str, Tuple[int, int, int, int]]]:
    """
    macOS-specific window enumeration using Quartz/AppKit.

    Returns window info including window ID for use with screencapture.
    Window tuple format: (title, (x, y, width, height, window_id))
    Note: For compatibility, we return (x, y, width, height) but also store window_id separately.
    """
    windows = []

    try:
        from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID
        from AppKit import NSWorkspace

        # Get list of all windows
        window_list = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID
        )

        # First pass: look for explicit Haasoscope windows
        for window in window_list:
            # Get window info
            window_name = window.get('kCGWindowName', '')
            owner_name = window.get('kCGWindowOwnerName', '')
            window_layer = window.get('kCGWindowLayer', 0)
            window_bounds = window.get('kCGWindowBounds', {})
            window_id = window.get('kCGWindowNumber', 0)

            # Look for Haasoscope windows (by window name or owner)
            # PyQt apps often have "Python" as owner, so check both
            is_haasoscope = (
                'Haasoscope' in window_name or
                ('Python' in owner_name and window_name)  # Python process with a title
            )

            if is_haasoscope and window_layer == 0:  # Layer 0 = normal windows
                # Get bounds
                x = int(window_bounds.get('X', 0))
                y = int(window_bounds.get('Y', 0))
                width = int(window_bounds.get('Width', 0))
                height = int(window_bounds.get('Height', 0))

                if width > 100 and height > 100:  # Ignore tiny windows
                    title = window_name if window_name else f"{owner_name} Window"
                    # Store window_id in a global dict for later use
                    _macos_window_ids[(title, (x, y, width, height))] = window_id
                    windows.append((title, (x, y, width, height)))
                    print(f"  Found window: {title} ({width}x{height} at {x},{y}) [ID: {window_id}]")

        # If no explicit Haasoscope windows found, check Python windows
        if not windows:
            print("  No explicit Haasoscope windows found, checking Python windows...")
            for window in window_list:
                owner_name = window.get('kCGWindowOwnerName', '')
                window_name = window.get('kCGWindowName', '')
                window_layer = window.get('kCGWindowLayer', 0)
                window_bounds = window.get('kCGWindowBounds', {})
                window_id = window.get('kCGWindowNumber', 0)

                if 'Python' in owner_name and window_layer == 0:
                    x = int(window_bounds.get('X', 0))
                    y = int(window_bounds.get('Y', 0))
                    width = int(window_bounds.get('Width', 0))
                    height = int(window_bounds.get('Height', 0))

                    # Main app window is typically large
                    if width > 500 and height > 400:
                        title = window_name if window_name else "HaasoscopeProQt"
                        # Store window_id in a global dict for later use
                        _macos_window_ids[(title, (x, y, width, height))] = window_id
                        windows.append((title, (x, y, width, height)))
                        print(f"  Found Python window: {title} ({width}x{height} at {x},{y}) [ID: {window_id}]")

    except ImportError:
        print("Warning: PyObjC not available. Install with: pip install pyobjc-framework-Quartz")
    except Exception as e:
        print(f"Warning: Error finding macOS windows: {e}")

    return windows


# Global dict to store macOS window IDs for screencapture
_macos_window_ids = {}


def _capture_window_macos(title: str, region: Tuple[int, int, int, int], filepath: Path) -> bool:
    """
    Capture a window on macOS using the native screencapture command.

    Tries multiple methods:
    1. Window ID capture (requires Screen Recording permission)
    2. Region-based capture using window bounds (works without permission)
    3. Interactive mode as last resort

    Args:
        title: Window title
        region: Window region (x, y, width, height)
        filepath: Path to save the screenshot

    Returns:
        True if successful, False otherwise
    """
    import subprocess

    # Look up the window ID
    window_key = (title, region)
    window_id = _macos_window_ids.get(window_key)

    if not window_id:
        # If window ID not found, try finding it again
        _find_windows_macos()
        window_id = _macos_window_ids.get(window_key)

    # Method 1: Try window ID capture (best quality, but requires permission)
    if window_id:
        try:
            cmd = ['screencapture', '-l', str(window_id), '-o', '-x', str(filepath)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

            if result.returncode == 0 and filepath.exists():
                return True
            # If failed, continue to fallback methods
        except:
            pass

    # Method 2: Region-based capture using window bounds
    # This works without Screen Recording permission
    try:
        x, y, width, height = region
        # screencapture -R takes x,y,width,height
        cmd = ['screencapture', '-R', f'{x},{y},{width},{height}', '-x', str(filepath)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode == 0 and filepath.exists():
            # Check if the image is not empty
            img = Image.open(filepath)
            if img.size[0] > 0 and img.size[1] > 0:
                return True

    except subprocess.TimeoutExpired:
        print(f"  Error: screencapture timed out")
        return False
    except Exception as e:
        print(f"  Error running screencapture: {e}")
        return False

    return False


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

        # Capture the window
        try:
            if sys.platform == 'darwin':
                # Use macOS native screencapture for better window capture
                success = _capture_window_macos(title, region, filepath)
                if success:
                    screenshots.append(filepath)
                    print(f"  Captured window: {title} -> {filename}")
                else:
                    print(f"  Warning: Failed to capture {title}")
            else:
                # Use pyautogui for other platforms
                left, top, width, height = region
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

        try:
            if sys.platform == 'darwin':
                # Use macOS native screencapture
                success = _capture_window_macos(title, region, filepath)
                if success:
                    print(f"  Captured main window: {title}")
                    return filepath
                else:
                    print(f"  Warning: Failed to capture main window")
                    return None
            else:
                # Use pyautogui for other platforms
                left, top, width, height = region
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
