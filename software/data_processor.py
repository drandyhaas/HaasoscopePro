# data_processor.py

import numpy as np
import struct
import warnings
import math
from scipy.signal import butter, filtfilt, find_peaks
from scipy.optimize import curve_fit
from scipy.fft import fft, fftfreq


# #############################################################################
# Data Processing Helper Functions (Moved from utils.py)
# #############################################################################

def fit_rise(x: np.ndarray, top: float, left: float, slope: float, bot: float) -> np.ndarray:
    """A clipped linear ramp function for fitting rising/falling edges."""
    val = slope * (x - left) + bot
    in_bottom = (x <= left)
    val[in_bottom] = bot
    if slope != 0:
        right = left + (top - bot) / slope
        in_top = (x >= right)
        val[in_top] = top
    return val


def find_fundamental_frequency_scipy(signal: np.ndarray, sampling_rate: float) -> float:
    """Finds the dominant frequency in a signal using FFT and SciPy's find_peaks."""
    if len(signal) < 2 or sampling_rate <= 0:
        return 0.0
    n = len(signal)
    fft_values = fft(signal)
    frequencies = fftfreq(n, 1 / sampling_rate)

    positive_mask = frequencies > 0
    if not np.any(positive_mask):
        return 0.0

    positive_freqs = frequencies[positive_mask]
    positive_mags = np.abs(fft_values[positive_mask])

    if not positive_mags.any():
        return 0.0

    # Find peaks that are at least 25% of the max peak height to filter noise
    peak_indices, _ = find_peaks(positive_mags, height=np.max(positive_mags) / 4)
    if not peak_indices.any():
        return 0.0

    # The fundamental is assumed to be the lowest-frequency, significant peak
    return positive_freqs[peak_indices[0]]


def format_freq(freq_hz: float, suffix="Hz", dostr=True):
    """Formats a frequency in Hz to a string with appropriate units."""
    if freq_hz is None or freq_hz < 1.0:
        if dostr: return f"{freq_hz:.2f} {suffix}"
        else: return freq_hz, "Hz"
    if freq_hz < 1000:
        if dostr: return f"{freq_hz:.3f} {suffix}"
        else: return freq_hz, "Hz"
    elif freq_hz < 1_000_000:
        if dostr: return f"{freq_hz / 1000:.3f} k{suffix}"
        else: return freq_hz / 1000, "kHz"
    elif freq_hz < 1_000_000_000:
        if dostr: return f"{freq_hz / 1_000_000:.3f} M{suffix}"
        else: return freq_hz / 1_000_000, "MHz"
    else:
        if dostr: return f"{freq_hz / 1_000_000_000:.3f} G{suffix}"
        else: return freq_hz / 1_000_000_000, "GHz"


def find_crossing_distance(y_data, y_threshold, x_ref, x0=0.0, dx=1.0, rising=True):
    """Calculates the horizontal distance from a reference x-position to the closest threshold crossing.

    Args:
        y_data: Signal data
        y_threshold: Threshold value to find crossings
        x_ref: Reference x position
        x0: Starting x position (default 0.0)
        dx: Sample spacing (default 1.0)
        rising: If True, find rising edge crossings (low to high). If False, find falling edge crossings (high to low).

    Returns:
        Distance from x_ref to the closest crossing, or None if no crossing found.
    """
    # Find all indices where the data crosses the threshold
    crossings = np.where(np.diff(np.sign(y_data - y_threshold)))[0]
    if crossings.size == 0:
        return None

    # Linearly interpolate to find the exact x-intersection for all crossings
    y1 = y_data[crossings]
    y2 = y_data[crossings + 1]
    x1 = x0 + crossings * dx

    # Filter crossings by direction
    delta_y = y2 - y1
    if rising:
        # Rising edge: y2 > y1 (delta_y > 0)
        valid_crossings = delta_y > 0
    else:
        # Falling edge: y2 < y1 (delta_y < 0)
        valid_crossings = delta_y < 0

    if not np.any(valid_crossings):
        return None

    fraction = (y_threshold - y1[valid_crossings]) / delta_y[valid_crossings]
    all_x_intersects = x1[valid_crossings] + fraction * dx

    # Find the intersection point that is closest to the reference x_ref
    closest_idx = np.argmin(np.abs(all_x_intersects - x_ref))
    closest_x_intersect = all_x_intersects[closest_idx]

    return closest_x_intersect - x_ref


# #############################################################################
# DataProcessor Class
# #############################################################################

class DataProcessor:
    """Handles processing of raw data from the hardware."""

    def __init__(self, state):
        self.state = state
        self.nsubsamples = 50  # 10*4 (clks) + 8 (strs) + 2 (beef)
        self.lastclk = -1

    def process_board_data(self, data, board_idx, xy_data_array):
        """
        Processes raw byte data for a single board, unpacking, scaling,
        filtering, and stabilizing it.
        """
        state = self.state

        # Use trigger reference from non-externally triggered board if needed
        if state.doexttrig[board_idx] and state.noextboard != -1:
            board_to_use = state.noextboard
            state.sample_triggered[board_idx] = state.sample_triggered[board_to_use]
            state.triggerphase[board_idx] = state.triggerphase[board_to_use]

        sample_triggered = state.sample_triggered[board_idx]
        triggerphase = state.triggerphase[board_idx] // (2 if state.dotwochannel[board_idx] else 1)

        # Unpack raw 16-bit integers and scale to plotting units
        unpackedsamples = struct.unpack('<' + 'h' * (len(data) // 2), data)
        npunpackedsamples = np.array(unpackedsamples, dtype='float') * state.yscale

        # If this board is the secondary in an oversampling pair (e.g., board 1, 3, etc.),
        # apply the correction factors calculated from its primary partner (e.g., board 0, 2).
        if state.dooversample[board_idx] and board_idx % 2 == 1:
            primary_board_idx = board_idx - 1
            # Additive mean correction
            npunpackedsamples += state.extrigboardmeancorrection[primary_board_idx]
            # Multiplicative RMS (standard deviation) correction
            npunpackedsamples *= state.extrigboardstdcorrection[primary_board_idx]

        # Calculate the total sample offset based on trigger position and hardware delays
        downsampleoffset = self._calculate_downsample_offset(sample_triggered, board_idx)

        # Map the sequential ADC samples into the correct time-ordered array slots
        datasize = xy_data_array[board_idx * 2][1].size
        nbadclkA, nbadclkB, nbadclkC, nbadclkD, nbadstr = 0, 0, 0, 0, 0
        for s in range(0, state.expect_samples + state.expect_samples_extra):

            # Check clock and strobe validity
            vals = unpackedsamples[s * self.nsubsamples + 40: s * self.nsubsamples + 50]
            if vals[9] != -16657: print("Warning: Beef marker not found!")
            if vals[8] != 0 or (self.lastclk != 341 and self.lastclk != 682):
                for n in range(0, 8):
                    val = vals[n]
                    if n < 4:
                        if val != 341 and val != 682:  # Expected clock patterns
                            if n == 0: nbadclkA += 1
                            if n == 1: nbadclkB += 1
                            if n == 2: nbadclkC += 1
                            if n == 3: nbadclkD += 1
                        self.lastclk = val
                    elif val not in {0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512}:  # Strobe should be one-hot
                        nbadstr += 1

            # CORRECTED: Use the per-board state to decide how to unpack data
            if state.dotwochannel[board_idx]:
                samp, nsamp, nstart = s * 20 - downsampleoffset - triggerphase, 20, 0
                if samp < 0: nsamp, nstart, samp = 20 + samp, -samp, 0
                if samp + nsamp >= datasize: nsamp = datasize - samp
                if 0 < nsamp <= 20:
                    c1_idx, c2_idx = board_idx * 2, board_idx * 2 + 1
                    xy_data_array[c1_idx][1][samp:samp + nsamp] = npunpackedsamples[s*self.nsubsamples+20+nstart: s*self.nsubsamples+20+nstart+nsamp]
                    xy_data_array[c2_idx][1][samp:samp + nsamp] = npunpackedsamples[s*self.nsubsamples+nstart: s*self.nsubsamples+nstart+nsamp]
            else:
                # Note: The data array is always allocated for 40 samples for simplicity.
                # For single-channel boards, we only fill the first channel's array.
                samp, nsamp, nstart = s * 40 - downsampleoffset - triggerphase, 40, 0
                if samp < 0: nsamp, nstart, samp = 40 + samp, -samp, 0
                if samp + nsamp >= datasize: nsamp = datasize - samp
                if 0 < nsamp <= 40:
                    c_idx = board_idx * 2
                    xy_data_array[c_idx][1][samp:samp + nsamp] = npunpackedsamples[s*self.nsubsamples+nstart: s*self.nsubsamples+nstart+nsamp]

        # Apply post-processing steps
        self._apply_lpf(board_idx, xy_data_array)
        self._apply_board_stabilizer(board_idx, xy_data_array)

        return nbadclkA, nbadclkB, nbadclkC, nbadclkD, nbadstr

    def _calculate_downsample_offset(self, sample_triggered, board_idx):
        """Calculates the total sample offset for data alignment."""
        state = self.state
        offset = 2 * (sample_triggered + (state.downsamplemergingcounter[
                                              board_idx] - 1) % state.downsamplemerging * 10) // state.downsamplemerging
        offset += 20 * state.triggershift
        if not state.dotwochannel[board_idx]:
            offset *= 2

        if state.doexttrig[board_idx]:
            factor = 2 if state.dotwochannel[board_idx] else 1
            offset -= int(state.toff / state.downsamplefactor / factor) + int(
                8 * state.lvdstrigdelay[board_idx] / state.downsamplefactor / factor) % 40

        return int(offset)

    def _apply_lpf(self, board_idx, xy_data_array):
        """Applies a digital low-pass filter if configured."""
        state = self.state
        sr = state.samplerate / (2 if state.dotwochannel[board_idx] else 1) / state.downsamplefactor
        nyquist = 0.5 * sr * 1e9

        c1_idx = board_idx * 2
        if state.lpf[c1_idx]:
            normal_cutoff = min(state.lpf[c1_idx] * 1e6 / nyquist, 0.99)
            fb, fa = butter(5, normal_cutoff, btype='low', analog=False)
            xy_data_array[c1_idx][1] = filtfilt(fb, fa, xy_data_array[c1_idx][1])

        if state.dotwochannel[board_idx]:
            c2_idx = c1_idx + 1
            if state.lpf[c2_idx]:
                normal_cutoff = min(state.lpf[c2_idx] * 1e6 / nyquist, 0.99)
                fb, fa = butter(5, normal_cutoff, btype='low', analog=False)
                xy_data_array[c2_idx][1] = filtfilt(fb, fa, xy_data_array[c2_idx][1])

    def _apply_board_stabilizer(self, board_idx, xy_data_array):
        """Applies board-level trigger stabilization."""
        s = self.state
        if not s.trig_stabilizer_enabled:
            return

        vline_time = 4 * 10 * (s.triggerpos + 1.0) * (s.downsamplefactor / s.nsunits / s.samplerate)
        hline_pos = (s.triggerlevel - 127) * s.yscale * 256
        # Include triggerdelta in the threshold
        hline_threshold = hline_pos + s.triggerdelta * s.yscale*256

        # --- This is the Board-level alignment logic from the original drawchannels() ---
        if abs(s.totdistcorr[board_idx]) > s.distcorrtol * s.downsamplefactor:
            for i in range(s.num_chan_per_board):
                xy_data_array[board_idx * s.num_chan_per_board + i][0] += s.totdistcorr[board_idx]
            s.totdistcorr[board_idx] = 0

        distcorrtemp = None
        if s.doexttrig[board_idx]:
            if s.noextboard != -1: distcorrtemp = s.distcorr[s.noextboard]
        else:
            triggering_chan_idx = board_idx * s.num_chan_per_board + s.triggerchan[board_idx]
            thed = xy_data_array[triggering_chan_idx]

            fitwidth = (s.max_x - s.min_x)
            xc = thed[0][(thed[0] > vline_time - fitwidth) & (thed[0] < vline_time + fitwidth)]
            if xc.size > 2:
                fitwidth *= s.distcorrsamp / xc.size
                xc = thed[0][(thed[0] > vline_time - fitwidth) & (thed[0] < vline_time + fitwidth)]
                yc = thed[1][(thed[0] > vline_time - fitwidth) & (thed[0] < vline_time + fitwidth)]

                # For falling edges, invert both the signal and the threshold
                threshold_to_use = hline_threshold
                if s.fallingedge[board_idx]:
                    yc = -yc
                    threshold_to_use = -hline_threshold

                if xc.size > 1:
                    distcorrtemp = find_crossing_distance(yc, threshold_to_use, vline_time, xc[0], xc[1] - xc[0])

        if distcorrtemp is not None and abs(distcorrtemp) < s.distcorrtol * s.downsamplefactor / s.nsunits:
            s.distcorr[board_idx] = distcorrtemp
            for i in range(s.num_chan_per_board):
                xy_data_array[board_idx * s.num_chan_per_board + i][0] -= s.distcorr[board_idx]
            s.totdistcorr[board_idx] += s.distcorr[board_idx]

    def calculate_fft(self, y_data, board_idx):
        """Calculates the FFT for a given channel's y-data."""
        n = len(y_data)
        if n < 2: return np.array([]), np.array([])
        k = np.arange(n)

        uspersample = self.state.downsamplefactor / self.state.samplerate / 1000.
        if self.state.dointerleaved[board_idx]:
            uspersample /= 2
        elif self.state.dotwochannel[board_idx]:
            uspersample *= 2

        freq = (k / uspersample)[list(range(n // 2))] / n
        Y = np.fft.fft(y_data)[list(range(n // 2))] / n
        Y[0] = 1e-3  # Suppress DC for plotting

        return freq, abs(Y)

    def calculate_measurements(self, x_data, y_data, vline, do_risetime_calc=False, use_edge_fit=True):
        """Calculates all requested measurements and returns fit results if requested.

        Args:
            x_data: Time data
            y_data: Signal data
            vline: Trigger position
            do_risetime_calc: Whether to calculate rise time
            use_edge_fit: If True, use edge-based fitting (works for any signal).
                         If False, use piecewise fitting (works for square waves).
        """
        if len(y_data) < 2: return {}, None
        state = self.state
        VperD = state.VperD[state.activexychannel]

        measurements = {
            "Mean": 1000 * VperD * np.mean(y_data),
            "RMS": 1000 * VperD * np.std(y_data),
            "Max": 1000 * VperD * np.max(y_data),
            "Min": 1000 * VperD * np.min(y_data),
            "Vpp": 1000 * VperD * (np.max(y_data) - np.min(y_data))
        }

        sampling_rate = (state.samplerate * 1e9) / state.downsamplefactor
        if state.dotwochannel[state.activeboard]: sampling_rate /= 2
        found_freq = find_fundamental_frequency_scipy(y_data, sampling_rate)
        measurements["Freq"] = found_freq

        # Initialize fit results to None
        fit_results = None

        if do_risetime_calc:
            if use_edge_fit:
                # New edge-based approach: find steep slope near trigger
                measurements, fit_results = self._calculate_risetime_edge(
                    x_data, y_data, vline, measurements
                )
            else:
                # Original piecewise approach for square waves
                measurements, fit_results = self._calculate_risetime_piecewise(
                    x_data, y_data, vline, measurements
                )

        return measurements, fit_results

    def _calculate_risetime_edge(self, x_data, y_data, vline, measurements):
        """Calculate rise time by fitting a line to the steepest edge near the trigger point."""
        state = self.state
        fitwidth = (state.max_x - state.min_x) * state.fitwidthfraction

        # Use "Falltime" for falling edges, "Risetime" for rising edges
        time_label = "Falltime" if state.fallingedge[state.activeboard] else "Risetime"
        error_label = f"{time_label} error"

        # Get data around trigger point
        xc = x_data[(x_data > vline - fitwidth) & (x_data < vline + fitwidth)]
        yc = y_data[(x_data > vline - fitwidth) & (x_data < vline + fitwidth)]

        if xc.size < 5:
            measurements[time_label] = math.nan
            measurements[error_label] = math.nan
            return measurements, None

        # Calculate signal min and max for edge validation using the FULL selected data
        y_min = np.min(yc)
        y_max = np.max(yc)
        y_20_threshold = y_min + 0.2 * (y_max - y_min)
        y_80_threshold = y_min + 0.8 * (y_max - y_min)

        # Get the trigger threshold for filtering
        hline_pos = (state.triggerlevel - 127) * state.yscale * 256
        hline_threshold = hline_pos + state.triggerdelta * state.yscale * 256

        # Find where the signal crosses the trigger threshold
        # This narrows our search significantly
        crossings = np.where(np.diff(np.sign(yc - hline_threshold)))[0]

        if len(crossings) == 0:
            # No crossing found, return NaN
            measurements[time_label] = math.nan
            measurements[error_label] = math.nan
            return measurements, None

        # Find crossing closest to vline
        vline_idx = np.argmin(np.abs(xc - vline))
        closest_crossing_idx = crossings[np.argmin(np.abs(crossings - vline_idx))]

        # Define search region: within ~10 samples of the trigger crossing
        search_range = 10
        search_start = max(0, closest_crossing_idx - search_range)
        search_end = min(len(xc), closest_crossing_idx + search_range)

        # Find the steepest section that extends from at least 20% to at least 80%
        # Use variable window sizes to handle both fast and slow signals
        max_slope = 0
        best_x_fit = None
        best_y_fit = None
        found_valid_edge = False

        # Try multiple window sizes from small to large
        min_window = max(3, xc.size // 20)  # At least 3 points, or 5% of data
        max_window = xc.size  # Can use full width for very slow signals

        # Try window sizes: small, medium, large, and full
        window_sizes_to_try = [
            min_window,
            max(5, xc.size // 10),
            max(10, xc.size // 5),
            max(20, xc.size // 3),
            max_window
        ]
        # Remove duplicates and sort
        window_sizes_to_try = sorted(set(window_sizes_to_try))

        for window_size in window_sizes_to_try:
            if window_size > xc.size:
                continue

            # Only check windows that overlap with the search region (±10 samples of crossing)
            window_start = max(0, search_start - window_size + 1)
            window_end = min(len(xc) - window_size + 1, search_end + 1)

            # Use adaptive step size: larger steps for larger windows
            # For small windows, check every position (step=1)
            # For large windows, skip positions to speed up search
            step = max(1, window_size // 20)  # Check every ~5% of window size

            for i in range(window_start, window_end, step):
                # Get this window
                x_window = xc[i:i+window_size]
                y_window = yc[i:i+window_size]

                # Check if this window extends from at least 20% to at least 80%
                y_window_min = np.min(y_window)
                y_window_max = np.max(y_window)

                if y_window_min <= y_20_threshold and y_window_max >= y_80_threshold:
                    # Extract only the points between 20% and 80% thresholds for fitting
                    # For the range check, use the actual min/max of the two thresholds
                    threshold_min = min(y_20_threshold, y_80_threshold)
                    threshold_max = max(y_20_threshold, y_80_threshold)
                    in_range = (y_window >= threshold_min) & (y_window <= threshold_max)
                    x_fit_candidate = x_window[in_range]
                    y_fit_candidate = y_window[in_range]

                    # Need at least 3 points for a good fit
                    if len(x_fit_candidate) >= 3:
                        # Simple linear regression on the 20%-80% portion
                        coeffs = np.polyfit(x_fit_candidate, y_fit_candidate, 1)
                        slope = coeffs[0]

                        # For rising trigger, find the largest positive slope
                        # For falling trigger, find the most negative (smallest) slope
                        if state.fallingedge[state.activeboard]:
                            # Falling edge: look for most negative slope
                            if max_slope == 0 or slope < max_slope:
                                max_slope = slope
                                best_x_fit = x_fit_candidate
                                best_y_fit = y_fit_candidate
                                found_valid_edge = True
                        else:
                            # Rising edge: look for most positive slope
                            if slope > max_slope:
                                max_slope = slope
                                best_x_fit = x_fit_candidate
                                best_y_fit = y_fit_candidate
                                found_valid_edge = True

        # If no valid edge found, return NaN
        if not found_valid_edge:
            measurements[time_label] = math.nan
            measurements[error_label] = math.nan
            return measurements, None

        # Use the best fit data found
        x_fit = best_x_fit
        y_fit = best_y_fit

        try:
            # Linear fit: y = mx + b
            coeffs, cov = np.polyfit(x_fit, y_fit, 1, cov=True)
            slope, intercept = coeffs
            slope_err = np.sqrt(cov[0, 0])

            # Calculate the signal amplitude (max - min in entire region)
            y_amp = np.max(yc) - np.min(yc)

            # Rise time is the time to traverse 60% of the amplitude at this slope
            # (10% to 90% is often 0.8, 20% to 80% is 0.6)
            if abs(slope) > 0:
                risetime = state.nsunits * 0.6 * abs(y_amp) / abs(slope)
                risetimeerr = state.nsunits * 0.6 * abs(y_amp) * slope_err / (slope * slope)

                measurements[time_label] = risetime
                measurements[error_label] = risetimeerr

                # Extend the fit line to cover 0% to 100% of the signal range
                # Using the slope from 20%-80% fit, but drawing from y_min to y_max
                y_0_percent = y_min
                y_100_percent = y_max

                # Calculate x values where the fit line crosses 0% and 100%
                # y = slope * x + intercept, so x = (y - intercept) / slope
                x_at_0_percent = (y_0_percent - intercept) / slope
                x_at_100_percent = (y_100_percent - intercept) / slope

                # Create extended fit line from 0% to 100%
                x_fit_extended = np.array([x_at_0_percent, x_at_100_percent])
                y_fit_extended = np.array([y_0_percent, y_100_percent])

                # Package results for plotting
                fit_results = {
                    'slope': slope,
                    'intercept': intercept,
                    'slope_err': slope_err,
                    'x_fit': x_fit_extended,  # Use extended line for plotting
                    'y_fit': y_fit_extended,  # Use extended line for plotting
                    'xc': xc,
                    'yc': yc,
                    'risetime_err': risetimeerr,
                    'fit_type': 'edge'
                }
            else:
                measurements[time_label] = math.nan
                measurements[error_label] = math.nan
                fit_results = None

        except (RuntimeError, ValueError, np.linalg.LinAlgError):
            measurements[time_label] = math.nan
            measurements[error_label] = math.nan
            fit_results = None

        return measurements, fit_results

    def _calculate_risetime_piecewise(self, x_data, y_data, vline, measurements):
        """Calculate rise time using the original piecewise function approach (for square waves)."""
        state = self.state

        # Use "Falltime" for falling edges, "Risetime" for rising edges
        time_label = "Falltime" if state.fallingedge[state.activeboard] else "Risetime"
        error_label = f"{time_label} error"

        fitwidth = (state.max_x - state.min_x) * state.fitwidthfraction
        xc = x_data[(x_data > vline - fitwidth) & (x_data < vline + fitwidth)]
        yc = y_data[(x_data > vline - fitwidth) & (x_data < vline + fitwidth)]

        if xc.size < 10:
            measurements[time_label] = math.nan
            measurements[error_label] = math.nan
            return measurements, None

        # initial guess
        p0 = [np.max(yc), xc[xc.size // 2], 2 * state.nsunits, np.min(yc)]
        if state.fallingedge[state.activeboard]: p0[2] *= -1

        with warnings.catch_warnings():
            try:
                warnings.simplefilter("ignore")
                p0[1] -= (p0[0] - p0[3]) / p0[2] / 2
                popt, pcov = curve_fit(fit_rise, xc, yc, p0=p0)
                perr = np.sqrt(np.diag(pcov))

                top, slope, bot = popt[0], popt[2], popt[3]
                risetime = state.nsunits * 0.6 * abs(top - bot) / slope
                if state.fallingedge[state.activeboard]: risetime *= -1 # since we call it "Falltime" now in the label
                risetimeerr = state.nsunits * 0.6 * 4 * abs(top - bot) * perr[2] / (slope * slope)

                measurements[time_label] = risetime
                measurements[error_label] = risetimeerr
                # Package the raw results to be returned
                fit_results = {'popt': popt, 'pcov': pcov, 'xc': xc, 'risetime_err': risetimeerr, 'fit_type': 'piecewise'}

            except (RuntimeError, ValueError):
                measurements[time_label] = math.nan
                measurements[error_label] = math.nan
                fit_results = None

        return measurements, fit_results