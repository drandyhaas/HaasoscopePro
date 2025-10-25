#!/usr/bin/env python3
"""
Quick test to verify window capture works on this platform.

Instructions:
1. Start HaasoscopeProQt (either with real hardware or dummy server)
2. Run this script: python test_window_capture.py
3. Check if windows are detected and screenshots are saved

This will help verify that the window capture is working correctly.
"""

import sys
from pathlib import Path
from window_capture import find_haasoscope_windows, capture_haasoscope_windows

print("=" * 80)
print("Window Capture Test")
print("=" * 80)
print()
print(f"Platform: {sys.platform}")
print()

# Step 1: Find windows
print("Step 1: Finding HaasoscopeProQt windows...")
print()
windows = find_haasoscope_windows()

if not windows:
    print("❌ No windows found!")
    print()
    print("Troubleshooting:")
    print("1. Make sure HaasoscopeProQt is running")
    print("2. Make sure the window is visible (not minimized)")
    if sys.platform == 'darwin':
        print("3. Check Screen Recording permissions in System Settings")
        print("   (Privacy & Security > Screen Recording)")
        print("4. Try running the diagnostic script:")
        print("   python diagnose_macos_capture.py")
    sys.exit(1)

print(f"✓ Found {len(windows)} window(s):")
print()
for i, (title, region) in enumerate(windows):
    left, top, width, height = region
    print(f"  {i+1}. {title}")
    print(f"     Position: ({left}, {top})")
    print(f"     Size: {width} x {height} pixels")
    print()

# Step 2: Capture screenshots
print("Step 2: Capturing screenshots...")
print()

output_dir = Path(__file__).parent / "test_captures"
screenshots = capture_haasoscope_windows(output_dir, prefix="test")

if screenshots:
    print(f"✓ Saved {len(screenshots)} screenshot(s):")
    print()
    for screenshot in screenshots:
        print(f"  - {screenshot}")
    print()

    # Check if screenshot actually contains window content
    print("Step 3: Verifying screenshot content...")
    print()

    if sys.platform == 'darwin':
        print("⚠️  IMPORTANT: Check if the screenshot shows the actual window content")
        print()
        print("If you only see the desktop background (not the app window):")
        print("1. You need to enable Screen Recording permission")
        print("2. See test/MACOS_SCREEN_CAPTURE.md for detailed instructions")
        print("3. Short version:")
        print("   - System Settings → Privacy & Security → Screen Recording")
        print("   - Add your Terminal/IDE")
        print("   - Fully quit (Cmd+Q) and restart your Terminal/IDE")
        print("   - Run this test again")
        print()

    print("=" * 80)
    print("Screenshot files created successfully!")
    print("Verify they contain the actual window content, not just the background.")
    print("=" * 80)
else:
    print("❌ Failed to capture screenshots")
    sys.exit(1)
