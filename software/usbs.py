"""
Handles the discovery, connection, and ordering of HaasoscopePro USB devices.

The key function, `orderusbs`, implements a daisy-chain discovery algorithm
to determine the physical order of the connected boards.
"""
import ftd2xx
from typing import List
from USB_FT232H import UsbFt232hSync245mode
from utils import getbit


def version(usb: UsbFt232hSync245mode, quiet: bool = True) -> int:
    """Reads the firmware version from a connected board."""
    usb.send(bytes([2, 0, 100, 100, 100, 100, 100, 100]))
    res = usb.recv(4)
    if len(res) < 4: return -1
    ver = int.from_bytes(res, "little")
    if not quiet:
        print(f"Firmware version: {ver}")
    return ver


def connectdevices(nmax: int = 100) -> List[UsbFt232hSync245mode]:
    """
    Scans for and connects to all available HaasoscopePro boards.

    Args:
        nmax (int): The maximum number of devices to connect.

    Returns:
        A list of connected UsbFt232hSync245mode objects.
    """
    usbs = []
    try:
        devices = ftd2xx.listDevices()
        if devices is None:
            print("No FTDI devices found.")
            return []

        print(f"Found {len(devices)} FTDI devices: {devices}")
        for serial_bytes in devices:
            if len(usbs) >= nmax:
                break
            # Attempt to connect only to devices with a standard FTDI serial
            if serial_bytes and serial_bytes.startswith(b'FT'):
                usb_device = UsbFt232hSync245mode('HaasoscopePro USB2', serial_bytes)
                if usb_device.good:
                    usbs.append(usb_device)
    except ftd2xx.DeviceError as e:
        print(f"Error listing FTDI devices: {e}")

    print(f"Successfully connected to {len(usbs)} HaasoscopePro boards.")
    return usbs


def _find_next_board_in_chain(current_board_idx: int, first_board_idx: int, usbs: list) -> int:
    """Helper to find the next board in the daisy chain by toggling a signal."""
    # Set the spare LVDS output high ONLY on the current board
    for i, usb in enumerate(usbs):
        is_current = (i == current_board_idx)
        usb.send(bytes([2, 5, is_current, 0, 99, 99, 99, 99]))
        usb.recv(4)  # Dummy read

    next_board_idx = -1
    for i, usb in enumerate(usbs):
        if i == first_board_idx: continue  # The first board's input is unterminated

        usb.send(bytes([2, 5, (i == current_board_idx), 0, 99, 99, 99, 99]))
        res = usb.recv(4)
        if len(res) < 4: continue

        spare_in_is_high = getbit(res[2], 0)
        if spare_in_is_high:
            if next_board_idx != -1:
                raise RuntimeError(
                    f"Board ordering failed: Multiple boards detected a signal from board {current_board_idx}.")
            next_board_idx = i

    if next_board_idx == -1:
        raise RuntimeError(f"Board ordering failed: Could not find the next board after board {current_board_idx}.")

    return next_board_idx


def orderusbs(usbs: List[UsbFt232hSync245mode]) -> List[UsbFt232hSync245mode]:
    """
    Determines the physical daisy-chain order of the connected boards.

    The first board is identified as the one with no external clock input.
    Subsequent boards are found by activating a signal on the last known board
    and polling the others to see which one received it.

    Returns:
        A new list of UsbFt232hSync245mode objects, sorted in their physical order.
    """
    if len(usbs) <= 1:
        return usbs

    first_board_idx = -1
    for i, usb in enumerate(usbs):
        usb.send(bytes([2, 5, 0, 0, 99, 99, 99, 99]))  # Get clock info
        res = usb.recv(4)
        if len(res) < 4:
            raise RuntimeError(f"Board ordering failed: Could not get LVDS info from board index {i}.")

        # The first board in the chain has no external clock, so this bit will be high.
        if getbit(res[1], 3):
            if first_board_idx != -1:
                raise RuntimeError("Board ordering failed: Found two boards with no external clock. Check sync cables.")
            first_board_idx = i
            print(f"Identified board index {i} (Serial: {usb.serial.decode()}) as the first in the chain.")

    if first_board_idx == -1:
        raise RuntimeError("Board ordering failed: Could not find the first board. Check sync cables.")

    ordered_indices = [first_board_idx]
    while len(ordered_indices) < len(usbs):
        last_found_idx = ordered_indices[-1]
        next_idx = _find_next_board_in_chain(last_found_idx, first_board_idx, usbs)
        print(f"Found board index {next_idx} (Serial: {usbs[next_idx].serial.decode()}) is next.")
        ordered_indices.append(next_idx)

    # Create the new, ordered list of usb objects
    return [usbs[i] for i in ordered_indices]


def tellfirstandlast(usbs: List[UsbFt232hSync245mode]):
    """Informs each board if it is the first or last in the chain for termination purposes."""
    if not usbs: return

    for i, usb in enumerate(usbs):
        if i == 0:
            firstlast = 1  # First board
        elif i == len(usbs) - 1:
            firstlast = 2  # Last board
        else:
            firstlast = 0  # Middle board

        usb.send(bytes([2, 14, firstlast, 0, 99, 99, 99, 99]))
        usb.recv(4)
