"""
Low-level functions for communicating with on-board chips via the SPI bus,
abstracted through the FTDI USB interface.
"""

from utils import binprint

# This global flag can be set to True during development to see SPI mode changes.
debugspi = False

def _execute_spi_transaction(usb, cs: int, b2: int, b3: int, b4: int, b5: int, nbyte: int) -> bytes:
    """
    (Helper) Sends a single, raw 8-byte SPI command packet and returns the 4-byte response.
    This is the core function that handles the direct USB communication.
    """
    # The opcode for an SPI transaction is 3.
    command_packet = bytes([3, cs, b2, b3, b4, b5, 100, nbyte])
    usb.send(command_packet)
    return usb.recv(4)

def spicommand(usb, name: str, first: int, second: int, third: int, read: bool,
               fourth: int = 100, show_bin: bool = False, cs: int = 0, nbyte: int = 3, quiet: bool = True) -> bytes:
    """
    Sends a general-purpose 3-byte or 4-byte SPI command by calling the core transaction helper once.
    """
    addr = first | 0x80 if read else first

    # Call the helper to perform the single transaction.
    spires = _execute_spi_transaction(usb, cs, addr, second, third, fourth, nbyte)

    if not quiet:
        if read:
            if show_bin:
                print(f"SPI Read: \t{name} ({hex(addr)} {hex(second)}) -> {binprint(spires[1])} {binprint(spires[0])}")
            else:
                print(f"SPI Read: \t{name} ({hex(addr)} {hex(second)}) -> {hex(spires[1])} {hex(spires[0])}")
        else:
            if nbyte == 4:
                print(f"SPI Write:\t{name} ({hex(addr)} {hex(second)}) -> {hex(third)} {hex(fourth)}")
            else:
                print(f"SPI Write:\t{name} ({hex(addr)} {hex(second)}) -> {hex(third)}")

    if read:
        return spires
    return None

def spicommand2(usb, name: str, first: int, second: int, third: int, fourth: int, read: bool,
                cs: int = 0, nbyte: int = 3, quiet: bool = True) -> bytes:
    """
    Sends a specialized SPI command for a 16-bit value by calling the core transaction helper twice.
    """
    addr = first | 0x80 if read else first

    # Call the helper for the first transaction (lower byte).
    spires = _execute_spi_transaction(usb, cs, addr, second, fourth, 100, nbyte)

    # Call the helper for the second transaction (upper byte at the next address).
    spires2 = _execute_spi_transaction(usb, cs, addr, second + 1, third, 100, nbyte)

    if not quiet:
        if read:
            print(f"SPI Read 16b:\t{name} ({hex(addr)} {hex(second)}) -> {hex(spires2[0])} {hex(spires[0])}")
        else:
            print(f"SPI Write 16b:\t{name} ({hex(addr)} {hex(second)}) -> {hex(third)} {hex(fourth)}")

    if read:
        # Per original behavior, returns only the result of the first transaction.
        return spires
    return None

def set_spi_mode(usb, mode: int):
    """
    Sets the SPI mode (clock polarity and phase). This is a different command type.
    """
    usb.send(bytes([4, mode, 0, 0, 0, 0, 0, 0]))
    spires = usb.recv(4)
    if debugspi:
        print(f"SPI mode set to {spires[0]}")
