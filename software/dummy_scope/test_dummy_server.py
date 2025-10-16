#!/usr/bin/env python3
"""
Simple test script to verify dummy_server.py and USB_Socket.py work correctly.
Run this after starting dummy_server.py in another terminal.
"""

import sys
import time
import struct
from USB_Socket import UsbSocketAdapter
from usbs import version, connect_socket_devices


def test_single_connection():
    """Test connecting to a single dummy server."""
    print("=" * 60)
    print("TEST 1: Single Connection")
    print("=" * 60)

    # Connect to dummy server
    print("Connecting to localhost:9999...")
    usb = UsbSocketAdapter('HaasoscopePro USB2 (Test)', 'localhost:9999')

    if not usb.good:
        print("ERROR: Failed to connect to dummy server!")
        print("Make sure dummy_server.py is running: python3 dummy_server.py")
        return False

    print("✓ Connected successfully")

    # Test version command
    print("\nSending version command...")
    ver = version(usb, quiet=True)
    print(f"✓ Received firmware version: 0x{ver:08x}")

    # Test direct command
    print("\nSending custom version command 3 times (like HaasoscopeProQt does)...")
    for i in range(3):
        usb.send(bytes([2, 0, 100, 100, 100, 100, 100, 100]))
        res = usb.recv(4)
        ver = struct.unpack("<I", res)[0] if len(res) == 4 else -1
        print(f"  Attempt {i+1}: 0x{ver:08x}")

    # Test LVDS info command (used for board ordering)
    print("\nTesting LVDS info command (opcode 2, sub 5)...")
    usb.send(bytes([2, 5, 0, 0, 99, 99, 99, 99]))
    res = usb.recv(4)
    if len(res) == 4:
        lvds_info = struct.unpack("<I", res)[0]
        print(f"✓ LVDS info: 0x{lvds_info:08x}")
    else:
        print("ERROR: Failed to get LVDS info")
        return False

    # Test fan control command
    print("\nTesting fan control command (opcode 2, sub 6)...")
    usb.send(bytes([2, 6, 1, 100, 100, 100, 100, 100]))  # Turn fan on
    res = usb.recv(4)
    print(f"✓ Fan control response: {res.hex()}")

    usb.close()
    print("\n✓ TEST 1 PASSED\n")
    return True


def test_multiple_connections():
    """Test connecting to multiple dummy servers."""
    print("=" * 60)
    print("TEST 2: Multiple Connections via connect_socket_devices()")
    print("=" * 60)

    print("Note: This test assumes only one server running on localhost:9999")
    print("For multiple servers, start additional dummy_server.py instances with --port 10000, etc.\n")

    usbs = connect_socket_devices(["localhost:9999"])

    if not usbs:
        print("ERROR: No devices connected!")
        return False

    print(f"✓ Connected to {len(usbs)} device(s)")

    for i, usb in enumerate(usbs):
        print(f"\nTesting device {i}...")
        ver = version(usb, quiet=True)
        print(f"  Firmware version: 0x{ver:08x}")

    print("\n✓ TEST 2 PASSED\n")
    return True


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Dummy Server & Socket Adapter Test Suite")
    print("=" * 60 + "\n")

    # Check if dummy server is running
    print("Checking if dummy_server.py is running on localhost:9999...")
    test_sock = UsbSocketAdapter('HaasoscopePro USB2 (Test)', 'localhost:9999')
    if not test_sock.good:
        print("\nERROR: Cannot connect to dummy_server.py!")
        print("Please start the server in another terminal:")
        print("  python3 dummy_server.py\n")
        return 1
    test_sock.close()
    print("✓ Server is running\n")

    # Run tests
    all_passed = True

    if not test_single_connection():
        all_passed = False

    if not test_multiple_connections():
        all_passed = False

    # Summary
    print("=" * 60)
    if all_passed:
        print("ALL TESTS PASSED ✓")
        print("=" * 60)
        return 0
    else:
        print("SOME TESTS FAILED ✗")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
