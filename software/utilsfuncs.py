# utilsfuncs.py
"""
Utility functions for data processing and formatting.
"""
import numpy as np
import warnings
from scipy.optimize import curve_fit
from scipy.fft import rfft, rfftfreq


def inttobytes(val):
    """Converts an integer to a list of 4 little-endian byte values."""
    return list(val.to_bytes(4, 'little'))


def find_longest_zero_stretch(data, circular):
    # Placeholder implementation
    return 5, 6  # A plausible good phase start and length


def format_freq(freq_hz):
    if freq_hz < 1000:
        return f"{freq_hz:.2f} Hz"
    elif freq_hz < 1_000_000:
        return f"{freq_hz / 1000:.3f} kHz"
    else:
        return f"{freq_hz / 1_000_000:.3f} MHz"


def fit_rise(x, amp, x0, sig, offset):
    """Error function for fitting a rising edge."""
    from scipy.special import erf
    return offset + (amp / 2.0) * (1 + erf((x - x0) / (sig * np.sqrt(2))))


def find_fundamental_frequency_scipy(y_data, sampling_rate):
    """Finds the dominant frequency in a signal using FFT."""
    if len(y_data) < 2 or sampling_rate <= 0:
        return 0
    N = len(y_data)
    yf = rfft(y_data)
    xf = rfftfreq(N, 1 / sampling_rate)
    # Find the peak frequency
    idx = np.argmax(np.abs(yf[1:])) + 1  # ignore DC component
    return xf[idx]


def calculate_risetime(x_data, y_data, trigger_x, fit_width):
    """Calculates risetime by fitting an error function to the data."""
    if len(x_data) < 10:
        return None, None

    mask = (x_data > trigger_x - fit_width) & (x_data < trigger_x + fit_width)
    xc, yc = x_data[mask], y_data[mask]

    if len(xc) < 10:
        return None, None

    try:
        p0 = [np.ptp(yc), np.mean(xc), np.std(xc), np.min(yc)]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            popt, pcov = curve_fit(fit_rise, xc, yc, p0=p0, maxfev=5000)
        perr = np.sqrt(np.diag(pcov))
        # The 10-90% risetime of an error function is approximately 1.16 * sigma
        # The original code uses 0.8 * popt[2], which seems empirical. We'll use it.
        risetime = 0.8 * popt[2]
        risetime_err = perr[2]
        return risetime, risetime_err
    except (RuntimeError, ValueError):
        return None, None
