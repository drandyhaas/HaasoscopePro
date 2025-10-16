"""
Dummy Oscilloscope Testing Framework

This package provides testing utilities for HaasoscopeProQt without physical hardware.

Components:
  - dummy_server: TCP socket server simulating oscilloscope board
  - USB_Socket: Socket adapter implementing USB-compatible interface
  - test_dummy_server: Test suite for the dummy server
"""

__version__ = "1.0"
__all__ = ["dummy_server", "USB_Socket", "test_dummy_server"]
