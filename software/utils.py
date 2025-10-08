"""
Provides low-level, generic helper functions for path finding, bit/byte
manipulation, and list processing used across the application.
"""
import sys
from typing import List


def get_pwd() -> str:
    """
    Finds the application's root directory, handling special paths for packaged executables.
    """
    path_string = sys.path[0]
    pwd = path_string
    # Handle cases where the script is run from a bundled executable folder
    for target in ["Mac_HaasoscopeProQt", "Windows_HaasoscopeProQt", "Linux_HaasoscopeProQt"]:
        index = path_string.find(target)
        if index != -1:
            pwd = path_string[:index + len(target)]
            break
    return pwd


def reverse_bits(byte: int) -> int:
    """Reverses the bit order of a single 8-bit integer."""
    reversed_byte = 0
    for i in range(8):
        if (byte >> i) & 1:
            reversed_byte |= 1 << (7 - i)
    return reversed_byte


def binprint(x: int) -> str:
    """Returns a zero-padded 8-bit binary string representation of an integer."""
    return bin(x)[2:].zfill(8)


def getbit(i: int, n: int) -> int:
    """Gets bit 'n' from integer 'i'."""
    return (i >> n) & 1


def find_longest_zero_stretch(arr: list, wrap: bool) -> tuple[int, int]:
    """
    Finds the longest contiguous stretch of near-zero values (<10) in a list.
    Used for PLL calibration.

    Args:
        arr (list): The list of numbers to search.
        wrap (bool): If True, treats the list as circular.

    Returns:
        A tuple containing (start_index, max_length).
    """
    if wrap:
        arr = arr + arr  # Duplicate the array to handle wraparound stretches
    max_length, current_length = 0, 0
    start_index, current_start = -1, -1
    for i, num in enumerate(arr):
        if num < 10:  # Threshold for "zero"
            if current_length == 0:
                current_start = i
            current_length += 1
            if current_length > max_length:
                max_length = current_length
                start_index = current_start
        else:
            current_length = 0
    return start_index, max_length


def inttobytes(theint: int) -> List[int]:
    """Converts a 32-bit integer to a 4-element list of bytes (little-endian)."""
    return [theint & 0xff, (theint >> 8) & 0xff, (theint >> 16) & 0xff, (theint >> 24) & 0xff]


def oldbytes(usb):
    """Reads and discards any lingering data in the USB receive buffer."""
    while True:
        old_data = usb.recv(100000)
        if len(old_data) > 0:
            print(f"Cleared {len(old_data)} old bytes from USB buffer.")
        else:
            break
