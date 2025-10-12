"""
Provides high-level functions for configuring the Haasoscope Pro hardware,
including the ADC, PLL synthesizer, amplifiers, and other peripherals.

This module acts as the primary hardware abstraction layer, using lower-level
modules like `spi.py` to execute commands.
"""

import time
import math
from typing import Union

# Import dependencies
from spi import spicommand, spicommand2, set_spi_mode
from utils import reverse_bits, inttobytes, getbit, binprint
from adf435x_core import calculate_regs, make_regs, DeviceType, FeedbackSelect, BandSelectClockMode, PDPolarity, ClkDivMode, MuxOut, LDPinMode

def auxoutselector(usb, val: int, doprint: bool = False):
    """Selects the signal to route to the auxiliary SMA output."""
    usb.send(bytes([2, 10, val, 0, 99, 99, 99, 99]))
    res = usb.recv(4)
    if doprint:
        print(f"auxoutselector now {val}, was {res[0]}")

def clkout_ena(usb, en: bool, doprint: bool = True):
    """Enables or disables the LVDS clock output for daisy-chaining boards."""
    usb.send(bytes([2, 9, int(en), 0, 99, 99, 99, 99]))
    res = usb.recv(4)
    if doprint:
        print(f"Clock out now {int(en)}, was {res[0]}")

def flash_erase(usb, doprint: bool = False):
    """Sends the command to bulk erase the configuration flash."""
    usb.send(bytes([17, 0, 0, 0, 99, 100, 101, 102]))
    res = usb.recv(4)
    if doprint:
        print(f"bulk erase got {res[0]}")

def flash_busy(usb, doprint: bool = False) -> int:
    """Checks the busy status of the configuration flash."""
    usb.send(bytes([14, 13, 0, 0, 99, 99, 99, 99]))
    res = usb.recv(4)
    if doprint:
        print(f"flash busy got {res[0]}")
    return res[0]

def reload_firmware(usb):
    """Commands the FPGA to reload its configuration from the flash memory."""
    print("New firmware is being loaded into the FPGA")
    usb.send(bytes([2, 19, 1, 0, 100, 100, 100, 100]))
    usb.recv(4)


def flash_write(usb, byte3: int, byte2: int, byte1: int, value_to_write: int, do_receive: bool = True):
    """
    Writes a single byte to a specific 24-bit address in the flash memory.

    Args:
        usb: The USB device handle.
        byte3 (int): The most significant byte of the address.
        byte2 (int): The middle byte of the address.
        byte1 (int): The least significant byte of the address.
        value_to_write (int): The 8-bit value to write.
        do_receive (bool): If True, waits for a response from the device.
    """
    # The hardware requires the data byte's bits to be reversed.
    reversed_value = reverse_bits(value_to_write)
    usb.send(bytes([16, byte3, byte2, byte1, reversed_value, 100, 101, 102]))
    if do_receive:
        res = usb.recv(4)
        print(f"Flash write response: {res[0]}")


def flash_writeall_from_file(usb, filename: str, do_write: bool = True) -> bytes:
    """
    Reads a binary file and writes its entire contents to the flash memory.

    Args:
        usb: The USB device handle.
        filename (str): The path to the binary file (e.g., firmware.rpd).
        do_write (bool): If False, reads the file but does not write to the device.

    Returns:
        The byte contents of the file that was read.
    """
    with open(filename, 'rb') as f:
        all_bytes = f.read()
        print(f"Opened {filename} with length {len(all_bytes)} bytes.")
        if do_write:
            for i, byte_val in enumerate(all_bytes):
                addr2 = i // (256 * 256)
                addr1 = (i // 256) % 256
                addr0 = i % 256
                # Write the byte but don't wait for an individual response to maximize speed.
                flash_write(usb, addr2, addr1, addr0, byte_val, do_receive=False)

                # The USB buffer is read in chunks to prevent overflow.
                if (i + 1) % 1024 == 0:
                    usb.recv(4 * 1024)
                    if (i + 1) % (1024 * 50) == 0:
                        print(f"Wrote byte {i + 1} / {len(all_bytes)}")

            # Receive the final remaining responses.
            remaining_bytes = len(all_bytes) % 1024
            if remaining_bytes > 0:
                usb.recv(4 * remaining_bytes)
            print(f"Finished writing {len(all_bytes)} bytes.")
    return all_bytes


def flash_read(usb, byte3: int, byte2: int, byte1: int, do_receive: bool = True) -> int:
    """
    Reads a single byte from a specific 24-bit address in the flash memory.

    Args:
        usb: The USB device handle.
        byte3 (int): The most significant byte of the address.
        byte2 (int): The middle byte of the address.
        byte1 (int): The least significant byte of the address.
        do_receive (bool): If True, receives and processes the response.

    Returns:
        The 8-bit value read from the flash memory.
    """
    usb.send(bytes([15, byte3, byte2, byte1, 99, 99, 99, 99]))
    if do_receive:
        res = usb.recv(4)
        if res and len(res) >= 1:
            value = reverse_bits(res[0])
            print(f"Flash read from adr {byte3:02x}{byte2:02x}{byte1:02x}: {value}")
            return value
        else:
            print("Flash read timed out.")
            return -1
    return 0


def flash_readall(usb) -> bytearray:
    """Reads the entire contents of the flash memory. This is a slow operation."""
    read_bytes = bytearray()
    total_size = 1191788
    block_size = 65536  # 256 * 256
    num_blocks = (total_size + block_size - 1) // block_size  # Ceiling division

    for k in range(num_blocks):
        print(f"Reading flash block {k + 1}/{num_blocks}...")

        # Determine how many bytes to read in this specific block
        bytes_so_far = k * block_size
        bytes_remaining_in_file = total_size - bytes_so_far
        reads_this_block = min(block_size, bytes_remaining_in_file)

        # Send all read commands for the block first
        for addr_in_block in range(reads_this_block):
            j = addr_in_block // 256
            i = addr_in_block % 256
            flash_read(usb, k, j, i, do_receive=False)

        # Receive the exact number of expected bytes for this block
        bytes_to_expect = reads_this_block * 4
        res = usb.recv(bytes_to_expect)

        if len(res) == bytes_to_expect:
            # Process the received bytes
            for byte_index in range(0, len(res), 4):
                out_byte = reverse_bits(res[byte_index])
                read_bytes.append(out_byte)
        else:
            print(f"Flash readall timeout on block {k + 1}. Expected {bytes_to_expect}, received {len(res)}.")
            break  # Stop if a read fails

    return read_bytes


def adf4350(usb, freq: float, phase: Union[int, None], r_counter: int = 1,
            divided: int = FeedbackSelect.Divider, ref_doubler: bool = False,
            ref_div2: bool = True, themuxout: bool = False, quiet: bool = True):
    """
    Configures the ADF4350 PLL synthesizer for a specific frequency.

    Args:
        usb: The USB device handle.
        freq (float): The target frequency in MHz.
        phase (int | None): The desired phase value (1-4095), or None for no phase adjust.
        r_counter (int): The R-counter divider value.
        divided (int): The feedback source for the PLL (from FeedbackSelect class).
        themuxout (bool): If True, routes a debug signal to the MUXOUT pin.
        quiet (bool): If True, suppresses debug print statements.
    """
    if not quiet:
        print(f'ADF4350: Configuring for {freq:.2f} MHz')

    INT, MOD, FRAC, output_divider, band_select_clock_divider = calculate_regs(
        device_type=DeviceType.ADF4350,
        freq=freq,
        ref_freq=50.0,
        band_select_clock_mode=BandSelectClockMode.Low,
        feedback_select=divided,
        r_counter=r_counter,
        ref_doubler=ref_doubler,
        ref_div2=ref_div2,
        enable_gcd=True
    )
    if not quiet:
        print(f"ADF4350 params: INT={INT}, MOD={MOD}, FRAC={FRAC}, out_div={output_divider}")

    regs = make_regs(
        device_type=DeviceType.ADF4350,
        INT=INT, MOD=MOD, FRAC=FRAC,
        output_divider=output_divider,
        band_select_clock_divider=band_select_clock_divider,
        r_counter=r_counter,
        ref_doubler=ref_doubler,
        ref_div_2=ref_div2,
        phase_value=phase,
        mux_out=int(themuxout),  # Note: Original code uses bool as int for mux_out
        charge_pump_current=2.50,
        feedback_select=divided,
        pd_polarity=PDPolarity.Positive,
        prescaler='4/5',
        band_select_clock_mode=BandSelectClockMode.Low,
        clk_div_mode=ClkDivMode.ResyncEnable,
        clock_divider_value=1000,
        output_power=5
    )

    set_spi_mode(usb, 0)
    for r in reversed(range(len(regs))):
        if not quiet:
            print(f"ADF4350 Reg {r}: {hex(regs[r])}")
        fourbytes = inttobytes(regs[r])
        spicommand(usb, f"ADF4350 Reg {r}", fourbytes[3], fourbytes[2], fourbytes[1], False,
                   fourth=fourbytes[0], cs=3, nbyte=4)
    set_spi_mode(usb, 0)


def setupboard(usb, dopattern: int, twochannel: bool, dooverrange: bool, do1v: bool = False) -> int:
    """
    Performs the initial configuration of the ADC and front-end amplifiers.
    Returns 0 on success, non-zero on failure.
    """
    #setfan(usb, True)
    set_spi_mode(usb, 0)

    # --- Power-up and Verification ---
    spicommand(usb, "DEVICE_CONFIG", 0x00, 0x02, 0x00, False)  # Power up ADC
    res = spicommand2(usb, "VENDOR_ID", 0x00, 0x0c, 0, 0, True)
    if res is None or res[0] != 0x51:
        print("Error: Could not read correct Vendor ID from ADC!")
        return 1

    # --- ADC and LVDS Configuration ---
    spicommand(usb, "LVDS_EN", 0x02, 0x00, 0x00, False)
    spicommand(usb, "CAL_EN", 0x00, 0x61, 0x00, False)
    if twochannel:
        spicommand(usb, "LMODE", 0x02, 0x01, 0x03, False)  # Dual channel
    else:
        spicommand(usb, "LMODE", 0x02, 0x01, 0x07, False)  # Single channel
    spicommand(usb, "LVDS_SWING", 0x00, 0x48, 0x00, False)  # High swing
    spicommand(usb, "LCTRL", 0x02, 0x04, 0x0a, False)  # 2's complement
    swapinputs(usb, False, insetup=True)  # Default to un-swapped inputs
    spicommand(usb, "TAD", 0x02, 0xB6, 0, False)  # Default TAD (ADC timing)

    # --- ADC Full-Scale Range ---
    if do1v:
        spicommand2(usb, "FS_RANGE A", 0x00, 0x30, 0xff, 0xff, False)  # 1V range
        spicommand2(usb, "FS_RANGE B", 0x00, 0x32, 0xff, 0xff, False)
    else:
        spicommand2(usb, "FS_RANGE A", 0x00, 0x30, 0xa0, 0x00, False)  # 800mV range
        spicommand2(usb, "FS_RANGE B", 0x00, 0x32, 0xa0, 0x00, False)

    # --- Finalization and Sync ---
    spicommand(usb, "CAL_EN", 0x00, 0x61, 0x01, False)
    spicommand(usb, "LVDS_EN", 0x02, 0x00, 0x01, False)
    spicommand(usb, "LSYNC_N", 0x02, 0x03, 0x00, False)  # Assert LSYNC
    spicommand(usb, "LSYNC_N", 0x02, 0x03, 0x01, False)  # De-assert LSYNC

    # --- Front-End Initialization ---
    set_spi_mode(usb, 1)  # Set SPI mode for DAC
    spicommand(usb, "DAC ref on", 0x38, 0xff, 0xff, False, cs=4)
    spicommand(usb, "DAC gain 1", 0x02, 0xff, 0xff, False, cs=4)
    set_spi_mode(usb, 0)  # Return to default SPI mode
    dooffset(usb, 0, 0, 1, False)
    dooffset(usb, 1, 0, 1, False)
    setgain(usb, 0, 0, False)
    setgain(usb, 1, 0, False)

    return 0


def setgain(usb, chan: int, value: int, doswap: bool):
    """Sets the gain for one of the front-end variable gain amplifiers."""
    set_spi_mode(usb, 0)
    if doswap: chan = (chan + 1) % 2
    cs = 2 if chan == 0 else 1
    # 26 is 0dB gain. Value is dB, so 26-value is the register setting.
    spicommand(usb, f"Amp Gain {chan}", 0x02, 0x00, 26 - value, False, cs=cs, nbyte=2, quiet=True)


def dooffset(usb, chan: int, val: int, scaling: float, doswap: bool) -> bool:
    """Sets the DC offset for a channel via the DAC."""
    set_spi_mode(usb, 1)
    dacval = int((pow(2, 16) - 1) * (val * scaling / 2 + 500) / 1000)
    if 0 < dacval < pow(2, 16):
        if doswap: chan = (chan + 1) % 2
        dac_addr = 0x19 if chan == 0 else 0x18
        spicommand(usb, f"DAC {chan} value", dac_addr, dacval >> 8, dacval & 0xFF, False, cs=4, quiet=True)
        set_spi_mode(usb, 0)
        return True
    set_spi_mode(usb, 0)
    return False


def clockused(usb, board: int, quiet: bool) -> int:
    """Checks if the board is locked to its internal clock (0) or an external clock (1)."""
    usb.send(bytes([2, 5, 0, 0, 99, 99, 99, 99]))
    clockinfo = usb.recv(4)
    if not quiet: print(f"Clockinfo for board {board}: {binprint(clockinfo[1])} {binprint(clockinfo[0])}")

    if getbit(clockinfo[1], 1) and not getbit(clockinfo[1], 3):
        if not quiet: print(f"Board {board} locked to external board")
        return 1
    else:
        if not quiet: print(f"Board {board} locked to internal clock")
        return 0


def switchclock(usb, board: int):
    """Toggles the clock source and checks the new status."""
    usb.send(bytes([7, 0, 0, 0, 99, 99, 99, 99]))
    usb.recv(4)
    return clockused(usb, board, quiet=False)


def setchanimpedance(usb, chan: int, onemeg: bool, doswap: bool):
    """Sets the input impedance for a channel (True for 1M Ohm, False for 50 Ohm)."""
    if doswap: chan = (chan + 1) % 2
    controlbit = 0 if chan == 0 else 4
    usb.send(bytes([10, controlbit, int(onemeg), 0, 0, 0, 0, 0]))
    usb.recv(4)


def setchanacdc(usb, chan: int, ac: bool, doswap: bool):
    """Sets the input coupling for a channel (True for AC, False for DC)."""
    if doswap: chan = (chan + 1) % 2
    controlbit = 1 if chan == 0 else 5
    usb.send(bytes([10, controlbit, int(not ac), 0, 0, 0, 0, 0]))
    usb.recv(4)


def setchanatt(usb, chan: int, att: bool, doswap: bool):
    """Enables or disables the front-end attenuator/filter."""
    if doswap: chan = (chan + 1) % 2
    controlbit = 2 if chan == 0 else 6
    usb.send(bytes([10, controlbit, int(att), 0, 0, 0, 0, 0]))
    usb.recv(4)


def setsplit(usb, split: bool):
    """Enables or disables the clock splitter for oversampling."""
    usb.send(bytes([10, 7, int(split), 0, 0, 0, 0, 0]))
    usb.recv(4)


def swapinputs(usb, doswap: bool, insetup: bool = False):
    """Swaps the physical inputs for Channels A and B."""
    if not insetup:
        spicommand(usb, "LVDS_EN", 0x02, 0x00, 0x00, False)
        spicommand(usb, "CAL_EN", 0x00, 0x61, 0x00, False)

    spicommand(usb, "INPUT_MUX", 0x00, 0x60, 0x12 if doswap else 0x01, False)

    if not insetup:
        spicommand(usb, "CAL_EN", 0x00, 0x61, 0x01, False)
        spicommand(usb, "LVDS_EN", 0x02, 0x00, 0x01, False)


def boardinbits(usb) -> int:
    """Reads the raw digital input status byte from the board (e.g., for PLL lock)."""
    usb.send(bytes([2, 1, 0, 100, 100, 100, 100, 100]))
    res = usb.recv(4)
    return res[0] if res and len(res) >= 1 else 0


def setfan(usb, fanon: bool, quiet: bool = True):
    """Turns the cooling fan on or off."""
    usb.send(bytes([2, 6, int(fanon), 100, 100, 100, 100, 100]))
    res = usb.recv(4)
    if not quiet: print(f"Set fan {int(fanon)}, status was {res[0]}")

def setfanpwm(usb, fanpwm: byte, quiet: bool = True):
    """Turns the cooling fan to a given duty cycle."""
    usb.send(bytes([2, 21, fanpwm, 100, 100, 100, 100, 100]))
    res = usb.recv(4)
    if not quiet: print(f"Set fan to {fanpwm}, was {res[0]}")


def send_leds(usb, r1, g1, b1, r2, g2, b2):
    """Sends RGB values to the two front-panel LEDs."""
    rw, gw, bw = 0.3, 0.4, 0.2
    r1, g1, b1 = reverse_bits(int(r1 * rw)), reverse_bits(int(g1 * gw)), reverse_bits(int(b1 * bw))
    r2, g2, b2 = reverse_bits(int(r2 * rw)), reverse_bits(int(g2 * gw)), reverse_bits(int(b2 * bw))
    # The LED controller requires two commands to latch the value
    for _ in range(2):
        usb.send(bytes([11, 1, g1, r1, b1, g2, r2, b2]))
        usb.recv(4)
        time.sleep(.001)
        usb.send(bytes([11, 0, g1, r1, b1, g2, r2, b2]))
        usb.recv(4)
        time.sleep(.001)


def gettemps(usb) -> list[float]:
    """Reads temperatures from the ADC die and a board thermistor."""
    set_spi_mode(usb, 0)

    # Read ADC die temperature sensor
    spicommand(usb, "ADC Temp Conv", 0x00, 0x00, 0, True, cs=6, nbyte=2, quiet=True)  # Dummy
    slowdac1 = spicommand(usb, "ADC Temp Read", 0x00, 0x00, 0, True, cs=6, nbyte=2, quiet=True)
    if not slowdac1 or len(slowdac1) < 2: return [0,0]

    slowdac1_val = (256 * slowdac1[1] + slowdac1[0])
    slowdac1_mv = slowdac1_val * 3300 / pow(2, 12) / 4.0
    adc_temp = (750 - slowdac1_mv) / 1.5

    # Read board thermistor
    spicommand(usb, "Board Temp Conv", 0x08, 0x00, 0, True, cs=6, nbyte=2, quiet=True)  # Dummy
    slowdac2 = spicommand(usb, "Board Temp Read", 0x08, 0x00, 0, True, cs=6, nbyte=2, quiet=True)
    if not slowdac2 or len(slowdac2) < 2: return [0,0]

    slowdac2_mv = (256 * slowdac2[1] + slowdac2[0]) * 3300 / pow(2, 12) / 1.1
    if slowdac2_mv == 0: return [0,0]

    r_board = 10000 * (3300 / slowdac2_mv - 1)
    if r_board <= 0: return [0,0]

    # Steinhart-Hart equation for thermistor
    t0, beta = 273.15 + 25, 3380.0
    t_board = 1.0 / (1.0 / t0 - math.log(r_board / 10000.0) / beta) - 273.15 - 10

    return [adc_temp, t_board]

def cleanup(usb):
    """Powers down the board safely."""
    set_spi_mode(usb, 0)
    spicommand(usb, "DEVICE_CONFIG", 0x00, 0x02, 0x03, False)
    setfan(usb, False)
    send_leds(usb, 50, 35, 50, 50, 35, 50)
