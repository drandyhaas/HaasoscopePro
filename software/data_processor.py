# data_processor.py

import numpy as np
import struct
import warnings
import math
from scipy.signal import resample, butter, filtfilt
from scipy.optimize import curve_fit
from utils import find_fundamental_frequency_scipy, format_freq, find_crossing_distance, fit_rise

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
        triggerphase = state.triggerphase[board_idx] // (2 if state.dotwochannel else 1)

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

            if state.dotwochannel:
                samp, nsamp, nstart = s * 20 - downsampleoffset - triggerphase, 20, 0
                if samp < 0: nsamp, nstart, samp = 20 + samp, -samp, 0
                if samp + nsamp >= datasize: nsamp = datasize - samp
                if 0 < nsamp <= 20:
                    c1_idx, c2_idx = board_idx * 2, board_idx * 2 + 1
                    xy_data_array[c1_idx][1][samp:samp + nsamp] = npunpackedsamples[
                                                                  s * self.nsubsamples + 20 + nstart: s * self.nsubsamples + 20 + nstart + nsamp]
                    xy_data_array[c2_idx][1][samp:samp + nsamp] = npunpackedsamples[
                                                                  s * self.nsubsamples + nstart: s * self.nsubsamples + nstart + nsamp]
            else:  # Single channel mode
                samp, nsamp, nstart = s * 40 - downsampleoffset - triggerphase, 40, 0
                if samp < 0: nsamp, nstart, samp = 40 + samp, -samp, 0
                if samp + nsamp >= datasize: nsamp = datasize - samp
                if 0 < nsamp <= 40:
                    c_idx = board_idx * 2
                    xy_data_array[c_idx][1][samp:samp + nsamp] = npunpackedsamples[
                                                                 s * self.nsubsamples + nstart: s * self.nsubsamples + nstart + nsamp]

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
        if not state.dotwochannel:
            offset *= 2

        if state.doexttrig[board_idx]:
            factor = 2 if state.dotwochannel else 1
            offset -= int(state.toff / state.downsamplefactor / factor) + int(
                8 * state.lvdstrigdelay[board_idx] / state.downsamplefactor / factor) % 40

        return int(offset)

    def _apply_lpf(self, board_idx, xy_data_array):
        """Applies a digital low-pass filter if configured."""
        state = self.state
        if state.lpf > 0:
            sr = state.samplerate / (2 if state.dotwochannel else 1) / state.downsamplefactor
            nyquist = 0.5 * sr * 1e9
            normal_cutoff = min(state.lpf * 1e6 / nyquist, 0.99)

            fb, fa = butter(5, normal_cutoff, btype='low', analog=False)

            c1_idx = board_idx * 2
            xy_data_array[c1_idx][1] = filtfilt(fb, fa, xy_data_array[c1_idx][1])
            if state.dotwochannel:
                c2_idx = c1_idx + 1
                xy_data_array[c2_idx][1] = filtfilt(fb, fa, xy_data_array[c2_idx][1])

    def _apply_board_stabilizer(self, board_idx, xy_data_array):
        """Applies board-level trigger stabilization."""
        s = self.state
        if not s.trig_stabilizer_enabled:
            return

        vline_time = 4 * 10 * (s.triggerpos + 1.0) * (s.downsamplefactor / s.nsunits / s.samplerate)
        hline_pos = (s.triggerlevel - 127) * s.yscale * 256

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
                if s.fallingedge[board_idx]: yc = -yc
                if xc.size > 1:
                    distcorrtemp = find_crossing_distance(yc, hline_pos, vline_time, xc[0], xc[1] - xc[0])

        if distcorrtemp is not None and abs(distcorrtemp) < s.distcorrtol * s.downsamplefactor / s.nsunits:
            s.distcorr[board_idx] = distcorrtemp
            for i in range(s.num_chan_per_board):
                xy_data_array[board_idx * s.num_chan_per_board + i][0] -= s.distcorr[board_idx]
            s.totdistcorr[board_idx] += s.distcorr[board_idx]

    def calculate_fft(self, y_data):
        """Calculates the FFT for a given channel's y-data."""
        n = len(y_data)
        if n < 2: return np.array([]), np.array([])
        k = np.arange(n)

        uspersample = self.state.downsamplefactor / self.state.samplerate / 1000.
        if self.state.dointerleaved[self.state.activeboard]:
            uspersample /= 2
        elif self.state.dotwochannel:
            uspersample /= 2

        freq = (k / uspersample)[list(range(n // 2))] / n
        Y = np.fft.fft(y_data)[list(range(n // 2))] / n
        Y[0] = 1e-3  # Suppress DC for plotting

        return freq, abs(Y)

    def calculate_measurements(self, x_data, y_data, vline):
        """Calculates all requested measurements (Mean, RMS, Vpp, Freq, Risetime)."""
        if len(y_data) < 2: return {}
        state = self.state
        VperD = state.VperD[state.activexychannel]

        measurements = {
            "Mean": f"{1000 * VperD * np.mean(y_data):.3f} mV",
            "RMS": f"{1000 * VperD * np.std(y_data):.3f} mV",
            "Max": f"{1000 * VperD * np.max(y_data):.3f} mV",
            "Min": f"{1000 * VperD * np.min(y_data):.3f} mV",
            "Vpp": f"{1000 * VperD * (np.max(y_data) - np.min(y_data)):.3f} mV"
        }

        # Frequency Calculation
        sampling_rate = (state.samplerate * 1e9) / state.downsamplefactor
        if state.dotwochannel: sampling_rate /= 2
        found_freq = find_fundamental_frequency_scipy(y_data, sampling_rate)
        measurements["Freq"] = format_freq(found_freq)

        # Risetime Calculation
        fitwidth = (state.max_x - state.min_x) * state.fitwidthfraction
        xc = x_data[(x_data > vline - fitwidth) & (x_data < vline + fitwidth)]
        yc = y_data[(x_data > vline - fitwidth) & (x_data < vline + fitwidth)]

        if xc.size < 10:
            measurements["Risetime"] = "Fit range too small"
        else:
            p0 = [np.max(yc), xc[xc.size // 2], 2 * state.nsunits, np.min(yc)]
            if state.fallingedge[state.activeboard]: p0[2] *= -1

            with warnings.catch_warnings():
                try:
                    warnings.simplefilter("ignore")
                    p0[1] -= (p0[0] - p0[3]) / p0[2] / 2
                    popt, pcov = curve_fit(fit_rise, xc, yc, p0)
                    perr = np.sqrt(np.diag(pcov))

                    top, slope, bot = popt[0], popt[2], popt[3]
                    risetime = state.nsunits * 0.6 * (top - bot) / slope
                    if state.fallingedge[state.activeboard]: risetime *= -1

                    risetimeerr = state.nsunits * 0.6 * 4 * (top - bot) * perr[2] / (slope * slope)
                    if abs(risetimeerr) != math.inf:
                        measurements["Risetime"] = f"{risetime:.2f} \u00B1 {risetimeerr:.2f} ns"
                    else:
                        measurements["Risetime"] = "Fit unstable"
                except RuntimeError:
                    measurements["Risetime"] = "Fit failed"

        return measurements
