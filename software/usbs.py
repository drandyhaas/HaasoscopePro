"""
Handles the discovery, connection, and ordering of HaasoscopePro USB devices.

The key function, `orderusbs`, implements a daisy-chain discovery algorithm
to determine the physical order of the connected boards.

For testing without hardware, use connect_socket_devices() instead of connectdevices().
"""
import sys
import ftd2xx
from typing import List, Union
from USB_FT232H import UsbFt232hSync245mode
from dummy_scope.USB_Socket import UsbSocketAdapter
from board import reload_firmware
from utils import getbit, oldbytes


def version(usb: UsbFt232hSync245mode, quiet: bool = True) -> int:
    """Reads the firmware version from a connected board."""
    usb.send(bytes([2, 0, 100, 100, 100, 100, 100, 100]))
    res = usb.recv(4)
    if len(res) < 4:
        print("Failed to get firmware version!")
        return -1
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

                    # Can skip or select particular boards if needed
                    if usb_device.serial == b'FTAKMEZ1' and False:
                        #continue
                        reload_firmware(usb_device)
                        usb_device.reopen()
                        sys.exit(-1)

                    # Clear any old data from the USB buffer just in case
                    if oldbytes(usb_device) > 100000:
                        raise RuntimeError(
                            f"Board communication failed with baord {usb_device.serial}.")

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
        if len(res) < 4:
            print("Warning in _find_next_board_in_chain: no response received from board",i)
            continue

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

    Dummy boards (UsbSocketAdapter instances) are not ordered via hardware discovery.
    They are appended to the end of the list in their original order.

    Returns:
        A new list of UsbFt232hSync245mode objects, sorted in their physical order.
    """
    if len(usbs) <= 1:
        return usbs

    # Separate real boards from dummy boards (UsbSocketAdapter)
    real_boards = []
    real_indices = []
    dummy_boards = []

    for i, usb in enumerate(usbs):
        # Check if this is a dummy board by checking the class type
        if isinstance(usb, UsbSocketAdapter):
            dummy_boards.append(usb)
            print(f"Board index {i} (Serial: {usb.serial.decode()}) is a dummy board - will not be ordered via hardware.")
        else:
            real_boards.append(usb)
            real_indices.append(i)

    # If there are no real boards or only one real board, just return the original order
    if len(real_boards) <= 1:
        return usbs

    first_board_idx = -1
    for i, usb in enumerate(real_boards):
        usb.send(bytes([2, 5, 0, 0, 99, 99, 99, 99]))  # Get clock info
        res = usb.recv(4)
        if len(res) < 4:
            orig_idx = real_indices[i]
            raise RuntimeError(f"Board ordering failed: Could not get LVDS info from board index {orig_idx}.")

        # The first board in the chain has no external clock, so this bit will be high.
        if getbit(res[1], 3):
            if first_board_idx != -1:
                raise RuntimeError(f"Board ordering failed: Also found board {i} with no external clock. Check sync cables.")
            first_board_idx = i
            print(f"Identified board index {i} (Serial: {usb.serial.decode()}) as the first in the chain.")

    if first_board_idx == -1:
        raise RuntimeError("Board ordering failed: Could not find the first board. Check sync cables.")

    ordered_indices = [first_board_idx]
    while len(ordered_indices) < len(real_boards):
        last_found_idx = ordered_indices[-1]
        next_idx = _find_next_board_in_chain(last_found_idx, first_board_idx, real_boards)
        print(f"Found board index {next_idx} (Serial: {real_boards[next_idx].serial.decode()}) is next.")
        ordered_indices.append(next_idx)

    # Create the new, ordered list of real boards
    ordered_real_boards = [real_boards[i] for i in ordered_indices]

    # Append dummy boards at the end in their original order
    return ordered_real_boards + dummy_boards


def tellfirstandlast(usbs: List[Union[UsbFt232hSync245mode, UsbSocketAdapter]]):
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


def connect_socket_devices(socket_addresses: List[str]) -> List[UsbSocketAdapter]:
    """
    Connect to dummy oscilloscope servers via TCP sockets for testing.

    Args:
        socket_addresses (List[str]): List of socket addresses in format "host:port"
                                     e.g., ["localhost:9999", "localhost:10000"]

    Returns:
        A list of connected UsbSocketAdapter objects.
    """
    usbs = []
    for addr in socket_addresses:
        try:
            usb_device = UsbSocketAdapter('HaasoscopePro USB2 (Socket)', addr)
            if usb_device.good:
                usbs.append(usb_device)
                # Optionally clear old data simulation
                version(usb_device, quiet=True)
        except Exception as e:
            print(f"Failed to connect to socket {addr}: {e}")

    print(f"Connected to {len(usbs)} dummy oscilloscope server(s) via socket.")
    return usbs
