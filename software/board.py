"""
This module provides functions for controlling and interacting with the data acquisition board hardware.
It includes functions for board setup, clock configuration, channel adjustments, and monitoring.

This version is refactored for readability and maintainability while strictly preserving
the original function names and signatures for compatibility.
"""

import time
import math

# Assuming these are custom or third-party modules for hardware interaction.
from spi import spicommand, spicommand2, spimode
from utils import binprint, getbit, inttobytes, send_leds
from adf435x_core import (
    calculate_regs, make_regs, DeviceType, FeedbackSelect,
    BandSelectClockMode, PDPolarity, ClkDivMode
)

# --- Constants for Hardware Registers and Configuration ---

# Device Configuration
REG_DEVICE_CONFIG = (0x00, 0x02)
VAL_POWER_UP = 0x00
VAL_POWER_DOWN = 0x03

# LVDS and Calibration
REG_LVDS_EN = (0x02, 0x00)
REG_CAL_EN = (0x00, 0x61)
VAL_ENABLE = 0x01
VAL_DISABLE = 0x00

# LVDS Mode and Control
REG_LMODE = (0x02, 0x01)
VAL_LMODE_DUAL_CHANNEL = 0x03
VAL_LMODE_SINGLE_CHANNEL = 0x07
REG_LVDS_SWING = (0x00, 0x48)
VAL_LVDS_SWING_HIGH = 0x00
VAL_LVDS_SWING_LOW = 0x01
REG_LCTRL = (0x02, 0x04)
VAL_LCTRL_TWOS_COMPLEMENT = 0x0a
REG_LSYNC_N = (0x02, 0x03)
VAL_LSYNC_ASSERT = 0x00
VAL_LSYNC_DEASSERT = 0x01

# Input and Clocking
REG_INPUT_MUX = (0x00, 0x60)
VAL_INPUT_MUX_SWAPPED = 0x12
VAL_INPUT_MUX_NORMAL = 0x01
REG_TAD_INVERT_CLK = (0x02, 0xB7)
REG_TAD_ADJUST = (0x02, 0xB6)

# ADC Full-Scale Range
REG_FS_RANGE_A = (0x00, 0x30)
REG_FS_RANGE_B = (0x00, 0x32)
VAL_FS_RANGE_800MV = (0xa0, 0x00)
VAL_FS_RANGE_1V = (0xff, 0xff)

# Over-range Configuration
REG_OVR_CFG = (0x02, 0x13)
VAL_OVR_ON = 0x0f
VAL_OVR_OFF = 0x07
REG_OVR_THRESHOLD_0 = (0x02, 0x11)
REG_OVR_THRESHOLD_1 = (0x02, 0x12)

# Test Pattern Selection
REG_PAT_SEL = (0x02, 0x05)
VAL_PAT_USER = 0x11
VAL_PAT_NORMAL_ADC = 0x02
REG_UPAT_CTRL = (0x01, 0x90)

# DAC Configuration
DAC_BITS = 16
MAX_DAC_CODE = (2 ** DAC_BITS) - 1
DAC_OUTPUT_RANGE_MV = 1000.0  # Assumes output is +/- 500mV, total range 1000mV

# Temperature Sensor Calculation
VREF_MV = 3300.0
TEMP_ADC_BITS = 12
TEMP_ADC_MAX_CODE = 2 ** TEMP_ADC_BITS
THERMISTOR_NOMINAL_OHMS = 10000.0
THERMISTOR_NOMINAL_TEMP_K = 273.15 + 25.0
THERMISTOR_BETA_COEFF = 3380.0
KELVIN_TO_CELSIUS_OFFSET = 273.15
BOARD_TEMP_CALIBRATION_OFFSET_C = -10.0


def adf4350(usb, freq, phase, r_counter=1, divided=FeedbackSelect.Divider, ref_doubler=False, ref_div2=True, themuxout=False):
    """
    Configures the ADF4350 synthesizer for a specific frequency and phase.
    """
    print('ADF4350 being set to %0.2f MHz' % freq)
    INT, MOD, FRAC, output_divider, band_select_clock_divider = (calculate_regs(
        device_type=DeviceType.ADF4350, freq=freq, ref_freq=50.0,
        band_select_clock_mode=BandSelectClockMode.Low,
        feedback_select=divided,
        r_counter=r_counter,
        ref_doubler=ref_doubler, ref_div2=ref_div2, enable_gcd=True))

    print("INT", INT, "MOD", MOD, "FRAC", FRAC, "outdiv", output_divider, "bandselclkdiv", band_select_clock_divider)

    regs = make_regs(
        INT=INT, MOD=MOD, FRAC=FRAC, output_divider=output_divider,
        band_select_clock_divider=band_select_clock_divider, r_counter=r_counter,
        ref_doubler=ref_doubler, ref_div_2=ref_div2,
        device_type=DeviceType.ADF4350, phase_value=phase, mux_out=themuxout,
        charge_pump_current=2.50, feedback_select=divided,
        pd_polarity=PDPolarity.Positive, prescaler='4/5',
        band_select_clock_mode=BandSelectClockMode.Low,
        clk_div_mode=ClkDivMode.ResyncEnable, clock_divider_value=1000,
        csr=False, aux_output_enable=False, aux_output_power=-4.0,
        output_enable=True, output_power=-4.0)

    spimode(usb, 0)
    for r in reversed(range(len(regs))):
        # regs[2]=0x5004E42 # Original commented-out line preserved
        print("adf4350 reg", r, binprint(regs[r]), hex(regs[r]))
        fourbytes = inttobytes(regs[r])
        spicommand(usb, "ADF4350 Reg " + str(r), fourbytes[3], fourbytes[2], fourbytes[1], False, fourth=fourbytes[0],
                   cs=3, nbyte=4)
    spimode(usb, 0)


def swapinputs(usb, doswap, insetup=False):
    """
    Swaps the physical inputs to the ADC.
    """
    if not insetup:
        spicommand(usb, "LVDS_EN", *REG_LVDS_EN, VAL_DISABLE, False)
        spicommand(usb, "CAL_EN", *REG_CAL_EN, VAL_DISABLE, False)

    if doswap:
        spicommand(usb, "INPUT_MUX", *REG_INPUT_MUX, VAL_INPUT_MUX_SWAPPED, False)
    else:
        spicommand(usb, "INPUT_MUX", *REG_INPUT_MUX, VAL_INPUT_MUX_NORMAL, False)

    if not insetup:
        spicommand(usb, "CAL_EN", *REG_CAL_EN, VAL_ENABLE, False)
        spicommand(usb, "LVDS_EN", *REG_LVDS_EN, VAL_ENABLE, False)


# --- Internal Helper Functions for setupboard ---
def _setupboard_configure_lvds(usb, two_channel_mode):
    if two_channel_mode:
        # LVDS mode: aligned, demux, dual channel, 12-bit
        spicommand(usb, "LMODE", *REG_LMODE, VAL_LMODE_DUAL_CHANNEL, False)
    else:
        # LVDS mode: aligned, demux, single channel, 12-bit
        spicommand(usb, "LMODE", *REG_LMODE, VAL_LMODE_SINGLE_CHANNEL, False)
    # high swing mode
    spicommand(usb, "LVDS_SWING", *REG_LVDS_SWING, VAL_LVDS_SWING_HIGH, False)
    # use LSYNC_N (software), 2's complement
    spicommand(usb, "LCTRL", *REG_LCTRL, VAL_LCTRL_TWOS_COMPLEMENT, False)

def _setupboard_configure_adc(usb, use_1v_range):
    # don't invert clk
    spicommand(usb, "TAD", *REG_TAD_INVERT_CLK, 0x00, False)
    # adjust TAD (time of ADC relative to clk)
    spicommand(usb, "TAD", *REG_TAD_ADJUST, 0, False)
    if use_1v_range:
        spicommand2(usb, "FS_RANGE A", *REG_FS_RANGE_A, *VAL_FS_RANGE_1V, False)
        spicommand2(usb, "FS_RANGE B", *REG_FS_RANGE_B, *VAL_FS_RANGE_1V, False)
    else:
        spicommand2(usb, "FS_RANGE A", *REG_FS_RANGE_A, *VAL_FS_RANGE_800MV, False)
        spicommand2(usb, "FS_RANGE B", *REG_FS_RANGE_B, *VAL_FS_RANGE_800MV, False)

def _setupboard_configure_overrange(usb, enable_overrange):
    if enable_overrange:
        spicommand(usb, "OVR_CFG", *REG_OVR_CFG, VAL_OVR_ON, False)
        spicommand(usb, "OVR_T0", *REG_OVR_THRESHOLD_0, 0xf2, False)
        spicommand(usb, "OVR_T1", *REG_OVR_THRESHOLD_1, 0xab, False)
    else:
        spicommand(usb, "OVR_CFG", *REG_OVR_CFG, VAL_OVR_OFF, False)

def _setupboard_set_test_pattern(usb, pattern_type):
    spicommand(usb, "PAT_SEL", *REG_PAT_SEL, VAL_PAT_USER, False)
    usrval = 0x00
    if pattern_type == 1:
        patterns = [(0, 0), (1, 1), (2, 2), (4, 4), (8, 8), (16, 16), (32, 32), (64, 64)]
    elif pattern_type == 2:
        #patterns = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0), (7, 0)]
        patterns = [(0, 0), (0, 1), (0, 0), (0, 2), (0, 0), (0, 3), (0, 0), (0, 4)]
    elif pattern_type == 3:
        patterns = [(0, 0), (1, 1), (1, 3), (3, 7), (3, 15), (7, 127), (7, 255), (8, 0)]
    elif pattern_type == 4:
        patterns = [(0, 0), (15, 255), (0, 0), (15, 255), (0, 0), (15, 255), (0, 0), (15, 255)]
    else:
        return

    for i, (val_a, val_b) in enumerate(patterns):
        addr_lsb = 0x80 + 2 * i
        spicommand2(usb, f"UPAT{i}", 0x01, addr_lsb, usrval + val_b, usrval + val_a, False)

    spicommand(usb, "UPAT_CTRL", *REG_UPAT_CTRL, 0x00, False)


def setupboard(usb, dopattern, twochannel, dooverrange):
    """
    Initializes and configures the main board hardware.
    """
    setfan(usb, 1)
    spimode(usb, 0)

    # Power up
    spicommand(usb, "DEVICE_CONFIG", *REG_DEVICE_CONFIG, VAL_POWER_UP, False)
    spicommand2(usb, "VENDOR", 0x00, 0x0c, 0x00, 0x00, True)

    # Disable interfaces during setup
    spicommand(usb, "LVDS_EN", *REG_LVDS_EN, VAL_DISABLE, False)
    spicommand(usb, "CAL_EN", *REG_CAL_EN, VAL_DISABLE, False)

    _setupboard_configure_lvds(usb, twochannel)
    swapinputs(usb, False, True)
    _setupboard_configure_adc(usb, use_1v_range=False)
    _setupboard_configure_overrange(usb, dooverrange)

    if dopattern:
        _setupboard_set_test_pattern(usb, dopattern)
    else:
        spicommand(usb, "PAT_SEL", *REG_PAT_SEL, VAL_PAT_NORMAL_ADC, False)
        spicommand(usb, "UPAT_CTRL", *REG_UPAT_CTRL, 0x1e, False)

    # Re-enable interfaces and trigger sync/calibration
    spicommand(usb, "CAL_EN", *REG_CAL_EN, VAL_ENABLE, False)
    spicommand(usb, "LVDS_EN", *REG_LVDS_EN, VAL_ENABLE, False)
    spicommand(usb, "LSYNC_N", *REG_LSYNC_N, VAL_LSYNC_ASSERT, False)
    spicommand(usb, "LSYNC_N", *REG_LSYNC_N, VAL_LSYNC_DEASSERT, False)

    # Read amplifier IDs and initialize DACs/Amps
    spimode(usb, 0)
    spicommand(usb, "Amp Rev ID", 0x00, 0x00, 0x00, True, cs=1, nbyte=2)
    spicommand(usb, "Amp Prod ID", 0x01, 0x00, 0x00, True, cs=1, nbyte=2)
    spicommand(usb, "Amp Rev ID", 0x00, 0x00, 0x00, True, cs=2, nbyte=2)
    spicommand(usb, "Amp Prod ID", 0x01, 0x00, 0x00, True, cs=2, nbyte=2)

    spimode(usb, 1)
    spicommand(usb, "DAC ref on", 0x38, 0xff, 0xff, False, cs=4)
    spicommand(usb, "DAC gain 1", 0x02, 0xff, 0xff, False, cs=4)
    spimode(usb, 0)
    dooffset(usb, 0, 0, 1, False)
    dooffset(usb, 1, 0, 1, False)
    setgain(usb, 0, 0, False)
    setgain(usb, 1, 0, False)


def setgain(usb, chan, value, doswap):
    """
    Sets the gain for a specified amplifier channel.
    """
    spimode(usb, 0)
    gain_code = 26 - value # 00 to 20 is 26 to -6 dB, 0x1a is no gain

    if doswap:
        chan = (chan + 1) % 2

    if chan == 0:
        spicommand(usb, "Amp Gain 0", 0x02, 0x00, gain_code, False, cs=2, nbyte=2, quiet=True)
    if chan == 1:
        spicommand(usb, "Amp Gain 1", 0x02, 0x00, gain_code, False, cs=1, nbyte=2, quiet=True)


def dooffset(usb, chan, val, scaling, doswap):
    """
    Sets the DC offset for a channel using the DAC.
    """
    spimode(usb, 1)
    # Map the bipolar mV value to a unipolar DAC code
    normalized_value = (val * scaling / 2 + DAC_OUTPUT_RANGE_MV / 2) / DAC_OUTPUT_RANGE_MV
    dacval = int(MAX_DAC_CODE * normalized_value)

    ret = False
    if 0 < dacval < MAX_DAC_CODE:
        ret = True
        if doswap:
            chan = (chan + 1) % 2

        # DAC 1 controls channel 1 (original chan 1), DAC 2 controls channel 0 (original chan 0)
        if chan == 1:
            spicommand(usb, "DAC 1 value", 0x18, dacval >> 8, dacval % 256, False, cs=4, quiet=True)
        if chan == 0:
            spicommand(usb, "DAC 2 value", 0x19, dacval >> 8, dacval % 256, False, cs=4, quiet=True)

    spimode(usb, 0)
    return ret


def fit_rise(x, top, left, leftplus, bot):
    """
    A linear ramp function for fitting rise times.
    """
    val = bot + (x - left) * (top - bot) / leftplus
    inbottom = (x <= left)
    val[inbottom] = bot
    intop = (x >= (left + leftplus))
    val[intop] = top
    return val


def clockswitch(usb, board, quiet):
    """
    Sends the command to switch the clock source.
    """
    usb.send(bytes([7, 0, 0, 0, 99, 99, 99, 99]))
    usb.recv(4)
    return clockused(usb, board, quiet)


def clockused(usb, board, quiet):
    """
    Checks which clock source is currently active.
    """
    usb.send(bytes([2, 5, 0, 0, 99, 99, 99, 99]))
    clockinfo = usb.recv(4)
    if not quiet:
        print("Clockinfo for board", board, binprint(clockinfo[1]), binprint(clockinfo[0]))

    if getbit(clockinfo[1], 1) and not getbit(clockinfo[1], 3):
        if not quiet: print("Board", board, "locked to ext board")
        return 1
    else:
        if not quiet: print("Board", board, "locked to internal clock")
        return 0


def switchclock(usb, board):
    """
    Switches the clock source and prints the new status.
    """
    clockswitch(usb, board, True)
    clockswitch(usb, board, False)


def setchanimpedance(usb, chan, onemeg, doswap):
    """Sets the input impedance for a channel."""
    if doswap: chan = (chan + 1) % 2
    if chan == 0: controlbit = 0
    elif chan == 1: controlbit = 4
    else: return
    usb.send(bytes([10, controlbit, onemeg, 0, 0, 0, 0, 0]))
    usb.recv(4)


def setchanacdc(usb, chan, ac, doswap):
    """Sets the AC/DC coupling for a channel."""
    if doswap: chan = (chan + 1) % 2
    if chan == 0: controlbit = 1
    elif chan == 1: controlbit = 5
    else: return
    # Note: The original logic `not ac` is preserved.
    usb.send(bytes([10, controlbit, not ac, 0, 0, 0, 0, 0]))
    usb.recv(4)


def setchanatt(usb, chan, att, doswap):
    """Sets the input attenuation for a channel."""
    if doswap: chan = (chan + 1) % 2
    if chan == 0: controlbit = 2
    elif chan == 1: controlbit = 6
    else: return
    usb.send(bytes([10, controlbit, att, 0, 0, 0, 0, 0]))
    usb.recv(4)


def setsplit(usb, split):
    """Sets the split mode."""
    controlbit = 7
    usb.send(bytes([10, controlbit, split, 0, 0, 0, 0, 0]))
    usb.recv(4)


def boardinbits(usb):
    """Reads the board's input status bits."""
    usb.send(bytes([2, 1, 0, 100, 100, 100, 100, 100]))
    res = usb.recv(4)
    return res[0]


def setfan(usb, fanon):
    """Turns the cooling fan on or off."""
    usb.send(bytes([2, 6, fanon, 100, 100, 100, 100, 100]))
    res = usb.recv(4)
    print("Set fan", fanon, "and it was", res[0])


def cleanup(usb):
    """
    Powers down the board and resets LEDs for a clean shutdown.
    """
    spimode(usb, 0)
    spicommand(usb, "DEVICE_CONFIG", *REG_DEVICE_CONFIG, VAL_POWER_DOWN, False)
    setfan(usb, 0)
    send_leds(usb, 50, 35, 50, 50, 35, 50)
    return 1


def getoverrange(usb):
    """Reads and prints the over-range status from the board."""
    usb.send(bytes([2, 2, 0, 100, 100, 100, 100, 100]))
    res = usb.recv(4)
    print("Overrange0", res[3], res[2], res[1], res[0])


def gettemps(usb):
    """
    Reads the ADC and board temperatures.
    """
    spimode(usb, 0)

    # Read ADC temperature sensor
    spicommand(usb, "SlowDAC1", 0x00, 0x00, 0x00, True, cs=6, nbyte=2, quiet=True)
    slowdac1 = spicommand(usb, "SlowDAC1", 0x00, 0x00, 0x00, True, cs=6, nbyte=2, quiet=True)
    slowdac1_code = (256 * slowdac1[1] + slowdac1[0])
    slowdac1_v = (slowdac1_code * VREF_MV / TEMP_ADC_MAX_CODE) / 4.0
    adctemp = (750 - slowdac1_v) / 1.5

    # Read board temperature sensor (thermistor)
    spicommand(usb, "SlowDAC2", 0x08, 0x00, 0x00, True, cs=6, nbyte=2, quiet=True)
    slowdac2 = spicommand(usb, "SlowDAC2", 0x08, 0x00, 0x00, True, cs=6, nbyte=2, quiet=True)
    slowdac2_code = (256 * slowdac2[1] + slowdac2[0])
    slowdac2_v = (slowdac2_code * VREF_MV / TEMP_ADC_MAX_CODE) / 1.1 # 2.0 on older boards

    Rboard = THERMISTOR_NOMINAL_OHMS * (VREF_MV / slowdac2_v - 1)

    # Steinhart-Hart equation approximation
    Tboard_inv_k = (1 / THERMISTOR_NOMINAL_TEMP_K) - (math.log(Rboard / THERMISTOR_NOMINAL_OHMS) / THERMISTOR_BETA_COEFF)
    Tboard = (1 / Tboard_inv_k) - KELVIN_TO_CELSIUS_OFFSET + BOARD_TEMP_CALIBRATION_OFFSET_C

    return "Temps (ADC, board): " + str(round(adctemp, 1)) + "\u00b0C, " + str(round(Tboard, 2)) + "\u00b0C"
