"""Legacy (original) Haasoscope support for the HaasoscopePro software.

This package lets the modern HaasoscopePro application drive the *original*
Haasoscope hardware. The original board has 4 channels at 8-bit / 125 MS/s and
talks a serial command protocol that is completely different from the Pro's
8-byte opcode FIFO protocol.

The integration works by presenting one physical original board as **two virtual
Pro "boards" of two channels each** (channels 0,1 -> board half 0; channels 2,3
-> board half 1). This keeps num_chan_per_board == 2 so the rest of the Pro app
(plotting, measurements, FFT, cursors, math, ...) runs unchanged.

- old_device.OldHaasoscopeDevice : slim self-contained serial driver for the
  original hardware (ported byte sequences from the legacy HaasoscopeLibQt.py).
- old_adapter.OldHaasoscopeBoardAdapter : implements the Pro "usb object"
  contract, translating Pro opcodes to device operations and packing the
  original 8-bit data into the Pro's 16-bit packet format.
"""

from .old_device import OldHaasoscopeDevice
from .old_adapter import OldHaasoscopeBoardAdapter, make_adapters_for_device

__all__ = [
    "OldHaasoscopeDevice",
    "OldHaasoscopeBoardAdapter",
    "make_adapters_for_device",
]
