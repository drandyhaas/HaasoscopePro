# frequency_calibration.py
"""
Frequency response calibration for Haasoscope Pro
Uses 10 MHz square wave as reference signal to measure and correct hardware frequency response
"""

import sys
import os
import json
import numpy as np
from scipy import signal
from PyQt5.QtWidgets import QMessageBox, QFileDialog


class FrequencyCalibration:
    """Handles frequency response calibration using 10 MHz square wave"""

    # Calibration parameters (magic numbers)
    NUM_TAPS_FACTOR = 1  # FIR filter length is (depending on sample rate: 32/64/128) x this
    NUM_AVERAGES = 1000  # Number of waveforms to average for calibration
    REGULARIZATION = 0.001  # Small epsilon to prevent division by zero
    MAX_CORRECTION_DB = 6  # Maximum boost/cut in dB (prevents over-correction)
    MAX_PHASE_CORRECTION_DEG = 25  # Maximum phase correction in degrees
    SNR_THRESHOLD = 100  # Require signal > this much x noise floor
    HARMONIC_EXCLUSION_MHZ = 2.5  # Exclude ± this many MHz around harmonics for noise estimation
    NOISE_WINDOW_MHZ = 250  # ± This many MHz window for noise estimation
    MEDIAN_FILTER_SIZE = 10  # Median filter window for smoothing corrections

    def __init__(self):
        self.num_taps = None
        self.num_averages = self.NUM_AVERAGES
        self.regularization = self.REGULARIZATION

    def generate_ideal_square_wave(self, frequency_hz, sample_rate_hz, num_samples, phase_offset=0, duty_cycle=0.5):
        """
        Generate ideal square wave with specified parameters

        Args:
            frequency_hz: Frequency of square wave (e.g., 10e6 for 10 MHz)
            sample_rate_hz: Sample rate in Hz
            num_samples: Number of samples to generate
            phase_offset: Phase offset in radians (for alignment with measured signal)
            duty_cycle: Duty cycle as fraction (0.5 = 50%, 0.502 = 50.2%, etc.)

        Returns:
            numpy array of square wave values (+1 or -1)
        """
        t = np.arange(num_samples) / sample_rate_hz
        # scipy.signal.square uses duty parameter which is the fraction of high state
        square = signal.square(2 * np.pi * frequency_hz * t + phase_offset, duty=duty_cycle)
        return square

    def align_signals(self, measured, ideal):
        """
        Align measured signal to ideal signal using cross-correlation

        Args:
            measured: Measured waveform
            ideal: Ideal reference waveform

        Returns:
            aligned_measured: Measured signal shifted to align with ideal
            shift_samples: Number of samples shifted
        """
        # Cross-correlate to find optimal alignment
        correlation = signal.correlate(measured, ideal, mode='same')
        shift_samples = np.argmax(correlation) - len(measured) // 2

        # Shift measured signal
        aligned_measured = np.roll(measured, -shift_samples)

        return aligned_measured, shift_samples

    def estimate_phase_offset(self, measured, frequency_hz, sample_rate_hz):
        """
        Estimate the phase offset of measured square wave relative to zero phase

        Args:
            measured: Measured waveform
            frequency_hz: Fundamental frequency
            sample_rate_hz: Sample rate

        Returns:
            phase_offset: Estimated phase in radians
        """
        # Use first zero crossing to estimate phase
        # Find first rising edge zero crossing
        zero_crossings = np.where(np.diff(np.sign(measured)) > 0)[0]
        if len(zero_crossings) == 0:
            return 0.0

        first_crossing = zero_crossings[0]
        samples_per_period = sample_rate_hz / frequency_hz

        # Phase offset in radians
        phase_offset = -2 * np.pi * first_crossing / samples_per_period

        return phase_offset

    def measure_duty_cycle(self, measured, frequency_hz, sample_rate_hz):
        """
        Measure the duty cycle of the measured square wave

        Args:
            measured: Measured waveform
            frequency_hz: Fundamental frequency
            sample_rate_hz: Sample rate

        Returns:
            duty_cycle: Measured duty cycle as fraction (0.5 = 50%, etc.)
        """
        # Find threshold (midpoint between min and max)
        threshold = (np.max(measured) + np.min(measured)) / 2.0

        # Find all samples above threshold
        high_samples = measured > threshold

        # Count transitions to verify we have a clean signal
        transitions = np.diff(high_samples.astype(int))
        num_rising = np.sum(transitions > 0)
        num_falling = np.sum(transitions < 0)

        if num_rising < 2 or num_falling < 2:
            # Not enough transitions to measure duty cycle reliably
            print(f"  - WARNING: Only {num_rising} rising and {num_falling} falling edges detected")
            return 0.5

        # Duty cycle is fraction of time spent high
        duty_cycle = np.mean(high_samples)

        # Sanity check: duty cycle should be between 0.4 and 0.6 for square waves
        if duty_cycle < 0.4 or duty_cycle > 0.6:
            print(f"  - WARNING: Measured duty cycle {duty_cycle:.1%} is outside expected range [40%, 60%]")
            # Clamp to reasonable range
            duty_cycle = np.clip(duty_cycle, 0.4, 0.6)

        return duty_cycle

    def measure_frequency(self, measured, sample_rate_hz, expected_freq=10e6):
        """
        Measure the actual fundamental frequency of the input signal

        Args:
            measured: Measured waveform
            sample_rate_hz: Sample rate
            expected_freq: Expected frequency (for search range)

        Returns:
            measured_freq: Measured fundamental frequency in Hz
        """
        # FFT to find the fundamental frequency
        fft = np.fft.rfft(measured)
        freqs = np.fft.rfftfreq(len(measured), d=1/sample_rate_hz)

        # Search for peak within ±10% of expected frequency
        search_min = expected_freq * 0.9
        search_max = expected_freq * 1.1
        search_mask = (freqs >= search_min) & (freqs <= search_max)

        if np.sum(search_mask) == 0:
            print(f"  - WARNING: No bins in search range [{search_min/1e6:.2f}, {search_max/1e6:.2f}] MHz")
            return expected_freq

        # Find peak frequency in search range
        search_freqs = freqs[search_mask]
        search_fft = np.abs(fft[search_mask])
        peak_idx = np.argmax(search_fft)
        measured_freq = search_freqs[peak_idx]

        # Parabolic interpolation for sub-bin accuracy
        if 0 < peak_idx < len(search_fft) - 1:
            # Use 3-point parabolic interpolation
            y1 = search_fft[peak_idx - 1]
            y2 = search_fft[peak_idx]
            y3 = search_fft[peak_idx + 1]

            # Parabolic peak offset
            denom = y1 - 2*y2 + y3
            if abs(denom) > 1e-10:
                offset = 0.5 * (y1 - y3) / denom
                # Interpolate frequency
                df = search_freqs[1] - search_freqs[0] if len(search_freqs) > 1 else 0
                measured_freq = measured_freq + offset * df

        return measured_freq

    def compute_frequency_response(self, measured, ideal, sample_rate_hz, fundamental_freq, is_interleaved=False):
        """
        Compute frequency response H(f) = FFT(measured) / FFT(ideal)

        For square wave calibration with measured duty cycle:
        - The ideal square wave is generated with the same duty cycle as the measured signal
        - Both odd and even harmonics now have known energy in the ideal
        - We can use ALL harmonics for calibration
        - This gives better frequency coverage

        Args:
            measured: Measured waveform (aligned to ideal)
            ideal: Ideal reference waveform (with matching duty cycle)
            sample_rate_hz: Sample rate in Hz
            fundamental_freq: Measured fundamental frequency in Hz
            is_interleaved: True if interleaved mode (affects hardware LPF cutoff)

        Returns:
            dict with keys:
                'freqs': Frequency array (Hz)
                'H_complex': Complex frequency response
                'magnitude': Magnitude response |H(f)|
                'phase': Phase response in radians
        """
        # No windowing for calibration - the signal is already periodic (exact integer number of periods)
        # Windowing would spread energy across bins and contaminate the measurement
        # Compute FFTs directly without amplitude normalization
        # The FIR filter will include overall gain correction as part of frequency response
        measured_fft = np.fft.rfft(measured)
        ideal_fft = np.fft.rfft(ideal)

        # Square wave has energy ONLY at odd harmonics (10, 30, 50, 70 MHz...)
        # At other frequencies, both FFTs are near-zero, causing H(f) = 0/0 = garbage
        # Solution: Only compute H(f) at EXACTLY the bins where 10 MHz harmonics land

        # Frequency array
        freqs = np.fft.rfftfreq(len(measured), d=1/sample_rate_hz)

        # Compute bin spacing
        nyquist_freq = sample_rate_hz / 2
        df = sample_rate_hz / len(measured)  # Bin spacing in Hz

        # Find bins for ALL harmonics of measured fundamental frequency up to Nyquist
        harmonic_freqs = []
        harmonic_bins = []
        for n in range(1, 1000):  # Large upper limit
            freq = fundamental_freq * n  # All harmonics: f, 2f, 3f, 4f...
            if freq > nyquist_freq:
                break
            bin_idx = int(round(freq / df))
            if bin_idx < len(freqs):
                harmonic_freqs.append(freq)
                harmonic_bins.append(bin_idx)

        harmonic_bins = np.array(harmonic_bins)

        # Initialize H_complex to 1.0 (no correction) everywhere
        H_complex = np.ones_like(measured_fft, dtype=complex)

        # Measure noise floor vs frequency
        # For each harmonic, estimate local noise floor from nearby bins (excluding ±5 MHz around harmonic)
        measured_mag = np.abs(measured_fft)
        significant_bins = np.zeros(len(measured_fft), dtype=bool)

        exclusion_width = int(self.HARMONIC_EXCLUSION_MHZ * 1e6 / df)
        snr_threshold = self.SNR_THRESHOLD

        num_bins_used = 0
        for harmonic_bin in harmonic_bins:
            # Define noise measurement window
            noise_window_width = int(self.NOISE_WINDOW_MHZ * 1e6 / df)
            noise_start = max(1, harmonic_bin - noise_window_width)  # Skip DC bin
            noise_end = min(len(measured_fft), harmonic_bin + noise_window_width)

            # Exclude the harmonic itself and other nearby harmonics
            noise_bins = np.ones(noise_end - noise_start, dtype=bool)
            for other_bin in harmonic_bins:
                if noise_start <= other_bin < noise_end:
                    local_idx = other_bin - noise_start
                    exclude_start = max(0, local_idx - exclusion_width)
                    exclude_end = min(len(noise_bins), local_idx + exclusion_width + 1)
                    noise_bins[exclude_start:exclude_end] = False

            # Compute local noise floor as median of non-harmonic bins
            if np.sum(noise_bins) > 10:  # Need at least 10 bins to estimate noise
                local_noise = np.median(measured_mag[noise_start:noise_end][noise_bins])
            else:
                local_noise = 0.0

            # Check if measured signal at this harmonic is above 10x noise floor
            signal_level = measured_mag[harmonic_bin]
            if signal_level > snr_threshold * local_noise and local_noise > 0:
                H_complex[harmonic_bin] = measured_fft[harmonic_bin] / ideal_fft[harmonic_bin]
                significant_bins[harmonic_bin] = True
                num_bins_used += 1

        # Force DC bin to 1.0 (no correction for DC offset)
        H_complex[0] = 1.0 + 0j

        # Compute magnitude and phase
        H_mag = np.abs(H_complex)
        H_phase = np.angle(H_complex)

        # Diagnostic output
        print(f"Frequency response measurement:")
        print(f"  - Number of harmonic bins found: {len(harmonic_bins)}")
        print(f"  - Number of harmonic bins used (SNR > 10x): {num_bins_used} / {len(freqs)}")
        print(f"  - SNR threshold: {snr_threshold:.1f}x")
        # Show H(f) magnitude range only at the measured harmonics
        if np.sum(significant_bins) > 0:
            H_mag_at_harmonics = H_mag[significant_bins]
            print(f"  - H(f) magnitude range at harmonics: [{np.min(H_mag_at_harmonics):.4f}, {np.max(H_mag_at_harmonics):.4f}]")
        print(f"  - H(f) magnitude at DC: {H_mag[0]:.4f}")
        # Find the 10 MHz bin
        if len(harmonic_bins) > 0 and significant_bins[harmonic_bins[0]]:
            idx_10MHz = harmonic_bins[0]
            print(f"  - H(f) magnitude at 10 MHz: {H_mag[idx_10MHz]:.4f}")
        # Show first 10 harmonic frequencies
        sig_freqs = freqs[significant_bins]
        if len(sig_freqs) > 0:
            print(f"  - Calibration frequencies: {', '.join([f'{f/1e6:.0f}' for f in sig_freqs[:10]])} MHz..." if len(sig_freqs) > 10 else f"  - Calibration frequencies: {', '.join([f'{f/1e6:.0f}' for f in sig_freqs])} MHz")
            # Show frequency range
            print(f"  - Frequency range: {sig_freqs[0]/1e6:.0f} MHz to {sig_freqs[-1]/1e6:.0f} MHz")

        return {
            'freqs': freqs,
            'H_complex': H_complex,
            'magnitude': H_mag,
            'phase': H_phase,
            'significant_bins': significant_bins
        }

    def design_correction_fir(self, freq_response, sample_rate_hz, max_correction_db=None):
        """
        Design FIR filter to correct frequency response

        For square wave calibration with measured duty cycle:
        - H(f) is computed at ALL harmonic positions (10, 20, 30, 40... MHz)
        - The ideal square wave has matching duty cycle, so all harmonics have known energy
        - Compute correction C(f) = 1 / H(f) at those frequencies
        - Interpolate smoothly between them to create full frequency response

        Args:
            freq_response: Dict from compute_frequency_response()
            sample_rate_hz: Sample rate in Hz
            max_correction_db: Maximum boost/cut in dB (prevents over-correction)

        Returns:
            fir_coefficients: 64-tap FIR filter coefficients
        """
        if max_correction_db is None:
            max_correction_db = self.MAX_CORRECTION_DB

        freqs = freq_response['freqs']
        H_mag = freq_response['magnitude']
        H_phase = freq_response['phase']
        significant_bins = freq_response['significant_bins']

        # Create correction magnitude: C_mag(f) = 1 / H_mag(f)
        # With regularization to prevent over-boosting
        # Only apply regularization to significant bins (where we measured H(f))
        H_mag_significant = H_mag[significant_bins]
        H_mag_max_significant = np.max(H_mag_significant)
        regularization_factor = self.regularization * H_mag_max_significant

        correction_mag = np.ones_like(H_mag)  # Start with 1.0 (no correction)

        # Only compute correction at harmonic frequencies (limited to below hardware LPF)
        correction_mag[significant_bins] = 1.0 / (H_mag[significant_bins] + regularization_factor)

        # Limit maximum correction to prevent noise amplification
        max_correction_factor = 10 ** (max_correction_db / 20)  # Convert dB to linear
        correction_mag = np.clip(correction_mag, 1/max_correction_factor, max_correction_factor)

        # IMPORTANT: filtfilt applies the filter twice (forward + backward pass)
        # So the effective correction is correction_mag^2
        # We need to take square root so that after filtfilt we get the desired correction
        correction_mag = np.sqrt(correction_mag)

        # Smooth the correction at significant bins to prevent interpolation artifacts
        # Only smooth the correction values at harmonics, not all frequencies
        from scipy.ndimage import median_filter
        sig_indices = np.where(significant_bins)[0]
        if len(sig_indices) > self.MEDIAN_FILTER_SIZE:
            # Extract correction values at significant bins
            correction_at_harmonics = correction_mag[sig_indices]
            # Apply median filter to remove outliers
            smoothed_correction = median_filter(correction_at_harmonics, size=self.MEDIAN_FILTER_SIZE, mode='nearest')
            # Put smoothed values back
            correction_mag[sig_indices] = smoothed_correction

        # Correction phase: invert the measured phase, but limit phase correction
        # Large phase corrections can cause artifacts
        correction_phase = -H_phase
        # Limit phase correction to prevent artifacts
        max_phase_correction = np.deg2rad(self.MAX_PHASE_CORRECTION_DEG)
        correction_phase = np.clip(correction_phase, -max_phase_correction, max_phase_correction)

        # Construct complex correction response
        correction_complex = correction_mag * np.exp(1j * correction_phase)

        # Report bins with large corrections
        debug_large_corrections = False
        if debug_large_corrections: print(f"\nLarge corrections (>{self.MAX_CORRECTION_DB/2} dB or phase>+-{self.MAX_PHASE_CORRECTION_DEG/2}°):")
        large_correction_threshold_linear = 10 ** (self.MAX_CORRECTION_DB/2 / 20)
        large_phase_threshold_rad = np.deg2rad(self.MAX_PHASE_CORRECTION_DEG/2)  # Report if > half max

        for idx in sig_indices:
            # Convert correction to dB (remember we took sqrt for filtfilt, so square it back)
            correction_db = 20 * np.log10(correction_mag[idx]**2)
            phase_deg = np.rad2deg(correction_phase[idx])

            if abs(correction_mag[idx]**2 - 1.0) > (large_correction_threshold_linear - 1.0) or abs(phase_deg) > np.rad2deg(large_phase_threshold_rad):
                freq_mhz = freqs[idx] / 1e6
                if debug_large_corrections: print(f"  {freq_mhz:6.0f} MHz: magnitude {correction_mag[idx]**2:.3f}x ({correction_db:+.1f} dB), phase {phase_deg:+.1f}°")

        # Design FIR filter using frequency sampling method
        # Need to create full spectrum (positive and negative frequencies)
        # rfft gives us frequencies [0, f1, f2, ..., f_nyquist]
        # Full spectrum is [0, f1, ..., f_nyquist, -f_{nyquist-1}, ..., -f1]

        # For irfft, we need the positive frequencies only (rfft format)
        # irfft will automatically construct the symmetric negative frequencies

        # Compute FIR coefficients using inverse FFT
        # We want the FIR filter to be N taps long
        # So we need to truncate/pad the frequency response to appropriate length

        # Method: Use firwin2 or frequency sampling
        # Simpler method: Pad correction_complex to desired FFT length, then IFFT

        fft_length = 2048  # Use longer FFT for better frequency resolution in design

        # For square wave with sparse harmonics, we need to interpolate between
        # ONLY the significant frequencies, not the entire sparse array with 1.0 everywhere
        from scipy.interpolate import interp1d

        new_freqs = np.linspace(0, sample_rate_hz/2, fft_length//2 + 1)

        # Extract only significant frequencies and their corrections
        sig_freqs = freqs[significant_bins]
        sig_correction_mag = correction_mag[significant_bins]
        sig_correction_phase = correction_phase[significant_bins]

        # Interpolate between ONLY the significant harmonics
        # Use linear interpolation (no overshoot, unlike cubic which can overshoot between sparse points)
        interp_mag = interp1d(sig_freqs, sig_correction_mag, kind='linear',
                             fill_value=(sig_correction_mag[0], sig_correction_mag[-1]),
                             bounds_error=False)
        interp_phase = interp1d(sig_freqs, sig_correction_phase, kind='linear',
                               fill_value=(sig_correction_phase[0], sig_correction_phase[-1]),
                               bounds_error=False)

        correction_mag_interp = interp_mag(new_freqs)
        correction_phase_interp = interp_phase(new_freqs)

        # Set DC explicitly to 1.0 (no correction)
        correction_mag_interp[0] = 1.0
        correction_phase_interp[0] = 0.0

        # Reconstruct complex correction
        correction_complex_interp = correction_mag_interp * np.exp(1j * correction_phase_interp)

        # IFFT to get time-domain impulse response
        fir_full = np.fft.irfft(correction_complex_interp, n=fft_length)

        # Center the impulse response (shifts zero-frequency component to center)
        fir_full_centered = np.fft.fftshift(fir_full)

        # Extract middle num_taps samples (centered around the peak)
        center_idx = len(fir_full_centered) // 2
        start_idx = center_idx - self.num_taps // 2
        end_idx = start_idx + self.num_taps
        fir_coefficients = fir_full_centered[start_idx:end_idx]

        # Apply Blackman window to reduce ringing
        window = signal.windows.blackman(self.num_taps)
        fir_coefficients = fir_coefficients * window

        # Normalize to unity gain at DC
        dc_gain = np.sum(fir_coefficients)
        if abs(dc_gain) > 1e-6:  # Only skip normalization if gain is essentially zero
            fir_coefficients = fir_coefficients / dc_gain
        else:
            print(f"  - WARNING: DC gain too small ({dc_gain:.2e}), normalization skipped")

        # Diagnostic output
        print(f"FIR filter design:")
        print(f"  - DC gain before normalization: {dc_gain:.4f}")
        print(f"  - Filter coefficient range: [{np.min(fir_coefficients):.4f}, {np.max(fir_coefficients):.4f}]")
        print(f"  - Filter sum (DC response): {np.sum(fir_coefficients):.4f}")
        print(f"  - Filter correction (at harmonics): [{np.min(correction_mag[significant_bins]):.4f}, {np.max(correction_mag[significant_bins]):.4f}] (sqrt for filtfilt)")
        print(f"  - Effective correction after filtfilt: [{np.min(correction_mag[significant_bins])**2:.4f}, {np.max(correction_mag[significant_bins])**2:.4f}]")
        print(f"  - Interpolated correction range: [{np.min(correction_mag_interp):.4f}, {np.max(correction_mag_interp):.4f}]")

        return fir_coefficients

    def validate_correction(self, measured, ideal, fir_coefficients):
        """
        Validate the correction by applying FIR filter and comparing to ideal

        Args:
            measured: Measured waveform
            ideal: Ideal reference waveform
            fir_coefficients: FIR filter coefficients to test

        Returns:
            dict with:
                'corrected': Corrected waveform
                'improvement_db': Improvement in dB (positive = better)
                'mse_before': Mean squared error before correction
                'mse_after': Mean squared error after correction
        """
        # Apply FIR filter using zero-phase filtering (like existing LPF)
        corrected = signal.filtfilt(fir_coefficients, [1.0], measured)

        # Compute error metrics
        mse_before = np.mean((measured - ideal)**2)
        mse_after = np.mean((corrected - ideal)**2)

        # Avoid log(0)
        if mse_after < 1e-20:
            mse_after = 1e-20
        if mse_before < 1e-20:
            improvement_db = 0
        else:
            improvement_db = 10 * np.log10(mse_before / mse_after)

        return {
            'corrected': corrected,
            'improvement_db': improvement_db,
            'mse_before': mse_before,
            'mse_after': mse_after
        }

    def calibrate_from_data(self, waveform_data_list, sample_rate_hz, is_interleaved=False):
        """
        Complete calibration process from list of captured waveforms

        Args:
            waveform_data_list: List of numpy arrays (captured waveforms)
            sample_rate_hz: Sample rate in Hz
            is_interleaved: True if interleaved mode (affects hardware LPF cutoff)

        Returns:
            dict with:
                'fir_coefficients': FIR filter (tap count scales with sample rate)
                'freq_response': Frequency response dict
                'validation': Validation results dict
                'success': True if calibration successful
                'message': Status message
        """
        try:
            # Select number of taps based on sample rate to maintain consistent frequency resolution
            # Target: ~50 MHz frequency resolution across all modes
            sample_rate_ghz = sample_rate_hz / 1e9
            if sample_rate_ghz < 2.0:
                # Two-channel mode (1.6 GHz) → 32 taps for ~50 MHz resolution
                self.num_taps = 32 * self.NUM_TAPS_FACTOR
                mode_name = "Two-channel"
            elif sample_rate_ghz < 4.5:
                # Normal/Oversampling mode (3.2 GHz) → 64 taps for ~50 MHz resolution
                self.num_taps = 64 * self.NUM_TAPS_FACTOR
                mode_name = "Normal/Oversampling"
            else:
                # Interleaved mode (6.4 GHz) → 128 taps for ~50 MHz resolution
                self.num_taps = 128 * self.NUM_TAPS_FACTOR
                mode_name = "Interleaved"

            print(f"\nMode detected: {mode_name} ({sample_rate_ghz:.2f} GHz)")
            print(f"Using {self.num_taps} taps for ~{sample_rate_hz/self.num_taps/1e6:.1f} MHz frequency resolution")

            print("\nProcessing: Averaging waveforms...")
            # Average the captured waveforms
            measured = np.mean(waveform_data_list, axis=0)

            # Remove DC offset from measured signal
            measured_mean = np.mean(measured)
            measured = measured - measured_mean
            print(f"  - Removed DC offset: {measured_mean:.4f}")

            print("Processing: Measuring signal frequency...")
            # Measure actual fundamental frequency (might not be exactly 10 MHz)
            measured_freq = self.measure_frequency(measured, sample_rate_hz, expected_freq=10e6)
            print(f"  - Measured frequency: {measured_freq/1e6:.6f} MHz (expected 10.000000 MHz)")
            freq_error_ppm = (measured_freq - 10e6) / 10e6 * 1e6
            print(f"  - Frequency error: {freq_error_ppm:+.1f} ppm")

            print("Processing: Measuring duty cycle...")
            # Measure duty cycle from measured signal
            duty_cycle = self.measure_duty_cycle(measured, measured_freq, sample_rate_hz)

            print("Processing: Aligning signals...")
            # Estimate phase offset from measured signal
            phase_offset = self.estimate_phase_offset(measured, measured_freq, sample_rate_hz)

            # Generate ideal square wave with measured frequency, duty cycle, and phase
            ideal = self.generate_ideal_square_wave(measured_freq, sample_rate_hz, len(measured), phase_offset, duty_cycle)

            # Fine-tune alignment using cross-correlation
            measured_aligned, shift = self.align_signals(measured, ideal)

            # Normalize measured signal to match ideal amplitude
            # This removes overall gain, leaving only frequency-dependent response variations
            # The FIR filter will then preserve input amplitude while correcting frequency response
            measured_rms = np.std(measured_aligned)
            ideal_rms = np.std(ideal)
            if measured_rms > 0:
                amplitude_scale = ideal_rms / measured_rms
                measured_normalized = measured_aligned * amplitude_scale
            else:
                measured_normalized = measured_aligned
                amplitude_scale = 1.0

            # Diagnostic: Show signal characteristics
            print(f"\nSignal alignment:")
            print(f"  - Measured duty cycle: {duty_cycle*100:.2f}%")
            print(f"  - Measured signal range: [{np.min(measured_aligned):.4f}, {np.max(measured_aligned):.4f}]")
            print(f"  - Ideal signal range: [{np.min(ideal):.4f}, {np.max(ideal):.4f}]")
            print(f"  - Cross-correlation shift: {shift} samples")
            print(f"  - Measured RMS: {np.std(measured_aligned):.4f}")
            print(f"  - Amplitude normalization: {amplitude_scale:.4f}x (for H(f) computation only)")

            print("\nProcessing: Computing frequency response...")
            # Compute frequency response using normalized signals
            # This H(f) will show only frequency-dependent variations, not overall gain
            freq_response = self.compute_frequency_response(measured_normalized, ideal, sample_rate_hz, measured_freq, is_interleaved)

            print("\nProcessing: Designing FIR filter...")
            # Design correction FIR filter
            fir_coefficients = self.design_correction_fir(freq_response, sample_rate_hz)

            print("\nProcessing: Validating correction...")
            # Validate the correction using normalized signal
            # This tests if the FIR corrects frequency response while preserving amplitude
            validation = self.validate_correction(measured_normalized, ideal, fir_coefficients)

            # Show validation results
            print(f"\nCalibration validation:")
            print(f"  - MSE before correction: {validation['mse_before']:.6f}")
            print(f"  - MSE after correction: {validation['mse_after']:.6f}")
            print(f"  - Improvement: {validation['improvement_db']:.1f} dB")
            print(f"  - Corrected signal range: [{np.min(validation['corrected']):.4f}, {np.max(validation['corrected']):.4f}]")
            print(f"  - Ideal signal range: [{np.min(ideal):.4f}, {np.max(ideal):.4f}]")

            message = f"Calibration successful. Improvement: {validation['improvement_db']:.1f} dB"

            print("\nCalibration complete!")

            return {
                'fir_coefficients': fir_coefficients,
                'freq_response': freq_response,
                'validation': validation,
                'success': True,
                'message': message,
                'sample_rate_hz': sample_rate_hz
            }

        except Exception as e:
            return {
                'fir_coefficients': None,
                'freq_response': None,
                'validation': None,
                'success': False,
                'message': f"Calibration failed: {str(e)}",
                'sample_rate_hz': sample_rate_hz
            }


# ============================================================================
# FIR Filter Save/Load Functions
# ============================================================================

def save_fir_filter(parent_window, state):
    """
    Save FIR calibration to a separate file.

    Args:
        parent_window: Parent QWidget for dialogs
        state: ScopeState object containing FIR calibration data

    Returns:
        True if save successful, False otherwise
    """
    # Check if any calibration exists
    has_normal = state.fir_coefficients is not None
    has_oversample = (state.fir_coefficients_oversample[0] is not None and
                     state.fir_coefficients_oversample[1] is not None)
    has_interleaved = state.fir_coefficients_interleaved is not None
    has_twochannel = state.fir_coefficients_twochannel is not None

    if not has_normal and not has_oversample and not has_interleaved and not has_twochannel:
        QMessageBox.warning(parent_window, "Save FIR Filter",
                          "No FIR calibration data to save. Please measure calibration first.")
        return False

    # Open file dialog
    options = QFileDialog.Options()
    if sys.platform.startswith('linux'):
        options |= QFileDialog.DontUseNativeDialog
    filename, _ = QFileDialog.getSaveFileName(
        parent_window, "Save FIR Filter", "", "FIR Filter Files (*.fir);;All Files (*)", options=options
    )
    if not filename:
        return False

    # Add .fir extension if not present
    if not os.path.splitext(filename)[1]:
        filename += ".fir"

    # Prepare data to save - save both normal and oversampling if they exist
    fir_data = {
        'calibration_downsample': 0,  # Calibration is always at downsample=0 (max rate)
        'calibration_type': '10MHz_square_wave',
        'software_version': state.softwareversion,
    }

    # Save normal mode calibration if exists
    if has_normal:
        fir_data['fir_coefficients'] = state.fir_coefficients.tolist()
        fir_data['calibration_samplerate_hz'] = state.fir_calibration_samplerate
        fir_data['num_taps'] = len(state.fir_coefficients)

        # Save frequency response if available
        if state.fir_freq_response is not None:
            fir_data['frequency_response'] = {
                'freqs': state.fir_freq_response['freqs'].tolist(),
                'magnitude': state.fir_freq_response['magnitude'].tolist(),
                'phase': state.fir_freq_response['phase'].tolist(),
            }

    # Save oversampling mode calibration if exists
    if has_oversample:
        fir_data['fir_coefficients_board0'] = state.fir_coefficients_oversample[0].tolist()
        fir_data['fir_coefficients_board1'] = state.fir_coefficients_oversample[1].tolist()
        fir_data['calibration_samplerate_hz_board0'] = state.fir_calibration_samplerate_oversample[0]
        fir_data['calibration_samplerate_hz_board1'] = state.fir_calibration_samplerate_oversample[1]
        if 'num_taps' not in fir_data:  # Only set if not already set by normal mode
            fir_data['num_taps'] = len(state.fir_coefficients_oversample[0])

        # Save frequency responses if available
        if state.fir_freq_response_oversample[0] is not None:
            fir_data['frequency_response_board0'] = {
                'freqs': state.fir_freq_response_oversample[0]['freqs'].tolist(),
                'magnitude': state.fir_freq_response_oversample[0]['magnitude'].tolist(),
                'phase': state.fir_freq_response_oversample[0]['phase'].tolist(),
            }
        if state.fir_freq_response_oversample[1] is not None:
            fir_data['frequency_response_board1'] = {
                'freqs': state.fir_freq_response_oversample[1]['freqs'].tolist(),
                'magnitude': state.fir_freq_response_oversample[1]['magnitude'].tolist(),
                'phase': state.fir_freq_response_oversample[1]['phase'].tolist(),
            }

    # Save interleaved mode calibration if exists
    if has_interleaved:
        fir_data['fir_coefficients_interleaved'] = state.fir_coefficients_interleaved.tolist()
        fir_data['calibration_samplerate_hz_interleaved'] = state.fir_calibration_samplerate_interleaved
        if 'num_taps' not in fir_data:  # Only set if not already set by other modes
            fir_data['num_taps'] = len(state.fir_coefficients_interleaved)

        # Save frequency response if available
        if state.fir_freq_response_interleaved is not None:
            fir_data['frequency_response_interleaved'] = {
                'freqs': state.fir_freq_response_interleaved['freqs'].tolist(),
                'magnitude': state.fir_freq_response_interleaved['magnitude'].tolist(),
                'phase': state.fir_freq_response_interleaved['phase'].tolist(),
            }

    # Save two-channel mode calibration if exists
    if has_twochannel:
        fir_data['fir_coefficients_twochannel'] = state.fir_coefficients_twochannel.tolist()
        fir_data['calibration_samplerate_hz_twochannel'] = state.fir_calibration_samplerate_twochannel
        if 'num_taps' not in fir_data:  # Only set if not already set by other modes
            fir_data['num_taps'] = len(state.fir_coefficients_twochannel)

        # Save frequency response if available
        if state.fir_freq_response_twochannel is not None:
            fir_data['frequency_response_twochannel'] = {
                'freqs': state.fir_freq_response_twochannel['freqs'].tolist(),
                'magnitude': state.fir_freq_response_twochannel['magnitude'].tolist(),
                'phase': state.fir_freq_response_twochannel['phase'].tolist(),
            }

    # Save to file
    try:
        with open(filename, 'w') as f:
            json.dump(fir_data, f, indent=2)
        if hasattr(parent_window, 'statusBar'):
            parent_window.statusBar().showMessage(f"FIR filter saved to {filename}", 5000)
        print(f"FIR filter saved to {filename}")
        return True
    except Exception as e:
        QMessageBox.critical(parent_window, "Save Failed", f"Failed to save FIR filter:\n{e}")
        return False


def load_fir_filter(parent_window, state, ui, filename=None, enable_corrections=True, show_dialogs=True):
    """
    Load FIR calibration from a file.

    Args:
        parent_window: Parent QWidget for dialogs
        state: ScopeState object to store loaded calibration
        ui: UI object for checkbox updates

        filename: Optional filename to load (if None, shows file dialog)
        enable_corrections: Whether to enable FIR corrections after loading (default: True)
        show_dialogs: Whether to show dialog boxes (default: True)

    Returns:
        True if load successful, False otherwise
    """
    # Open file dialog if no filename provided
    if filename is None:
        options = QFileDialog.Options()
        if sys.platform.startswith('linux'):
            options |= QFileDialog.DontUseNativeDialog
        filename, _ = QFileDialog.getOpenFileName(
            parent_window, "Load FIR Filter", "", "FIR Filter Files (*.fir);;All Files (*)", options=options
        )
        if not filename:
            return False

    # Load from file
    try:
        with open(filename, 'r') as f:
            fir_data = json.load(f)
    except Exception as e:
        if show_dialogs:
            QMessageBox.critical(parent_window, "Load Failed", f"Failed to load FIR filter:\n{e}")
        else:
            print(f"Warning: Failed to load FIR filter from {filename}: {e}")
        return False

    # Check which calibrations are present in the file
    has_normal_in_file = 'fir_coefficients' in fir_data and fir_data['fir_coefficients'] is not None
    has_oversample_in_file = ('fir_coefficients_board0' in fir_data and fir_data['fir_coefficients_board0'] is not None and
                             'fir_coefficients_board1' in fir_data and fir_data['fir_coefficients_board1'] is not None)
    has_interleaved_in_file = 'fir_coefficients_interleaved' in fir_data and fir_data['fir_coefficients_interleaved'] is not None
    has_twochannel_in_file = 'fir_coefficients_twochannel' in fir_data and fir_data['fir_coefficients_twochannel'] is not None

    if not has_normal_in_file and not has_oversample_in_file and not has_interleaved_in_file and not has_twochannel_in_file:
        if show_dialogs:
            QMessageBox.warning(parent_window, "Load Failed", "Invalid FIR filter file: missing coefficients.")
        else:
            print(f"Warning: Invalid FIR filter file {filename}: missing coefficients")
        return False

    current_samplerate_hz = state.samplerate * 1e9
    calibration_downsample = fir_data.get('calibration_downsample', 0)

    # Load normal mode calibration if present
    if has_normal_in_file:
        state.fir_coefficients = np.array(fir_data['fir_coefficients'])
        state.fir_calibration_samplerate = fir_data.get('calibration_samplerate_hz', None)

        # Restore frequency response if available
        if 'frequency_response' in fir_data:
            state.fir_freq_response = {
                'freqs': np.array(fir_data['frequency_response']['freqs']),
                'magnitude': np.array(fir_data['frequency_response']['magnitude']),
                'phase': np.array(fir_data['frequency_response']['phase']),
            }

        # Check sample rate match
        if state.fir_calibration_samplerate is not None:
            if abs(current_samplerate_hz - state.fir_calibration_samplerate) > 1e6:  # 1 MHz tolerance
                if show_dialogs:
                    reply = QMessageBox.question(
                    parent_window, "Sample Rate Mismatch",
                    f"Normal FIR calibration was performed at {state.fir_calibration_samplerate/1e9:.3f} GS/s,\n"
                    f"but current base sample rate is {current_samplerate_hz/1e9:.3f} GS/s.\n\n"
                    f"The correction may not be accurate. Continue anyway?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                    if reply == QMessageBox.No:
                        state.fir_coefficients = None
                        state.fir_calibration_samplerate = None
                        state.fir_freq_response = None
                        return False
                else:
                    print(f"Warning: Normal FIR calibration sample rate mismatch (continuing anyway)")

    # Load oversampling mode calibration if present
    if has_oversample_in_file:
        state.fir_coefficients_oversample[0] = np.array(fir_data['fir_coefficients_board0'])
        state.fir_coefficients_oversample[1] = np.array(fir_data['fir_coefficients_board1'])
        state.fir_calibration_samplerate_oversample[0] = fir_data.get('calibration_samplerate_hz_board0', None)
        state.fir_calibration_samplerate_oversample[1] = fir_data.get('calibration_samplerate_hz_board1', None)

        # Restore frequency responses if available
        if 'frequency_response_board0' in fir_data:
            state.fir_freq_response_oversample[0] = {
                'freqs': np.array(fir_data['frequency_response_board0']['freqs']),
                'magnitude': np.array(fir_data['frequency_response_board0']['magnitude']),
                'phase': np.array(fir_data['frequency_response_board0']['phase']),
            }
        if 'frequency_response_board1' in fir_data:
            state.fir_freq_response_oversample[1] = {
                'freqs': np.array(fir_data['frequency_response_board1']['freqs']),
                'magnitude': np.array(fir_data['frequency_response_board1']['magnitude']),
                'phase': np.array(fir_data['frequency_response_board1']['phase']),
            }

        # Check sample rate match (check board 0)
        if state.fir_calibration_samplerate_oversample[0] is not None:
            if abs(current_samplerate_hz - state.fir_calibration_samplerate_oversample[0]) > 1e6:
                if show_dialogs:
                    reply = QMessageBox.question(
                    parent_window, "Sample Rate Mismatch",
                    f"Oversampling FIR calibration was performed at {state.fir_calibration_samplerate_oversample[0]/1e9:.3f} GS/s,\n"
                    f"but current base sample rate is {current_samplerate_hz/1e9:.3f} GS/s.\n\n"
                    f"The correction may not be accurate. Continue anyway?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                    if reply == QMessageBox.No:
                        state.fir_coefficients_oversample = [None, None]
                        state.fir_calibration_samplerate_oversample = [None, None]
                        state.fir_freq_response_oversample = [None, None]
                        # Don't return False here - other modes might still be loaded
                else:
                    print(f"Warning: Oversampling FIR calibration sample rate mismatch (continuing anyway)")
                    if not has_normal_in_file and not has_interleaved_in_file:
                        return False

    # Load interleaved mode calibration if present
    if has_interleaved_in_file:
        state.fir_coefficients_interleaved = np.array(fir_data['fir_coefficients_interleaved'])
        state.fir_calibration_samplerate_interleaved = fir_data.get('calibration_samplerate_hz_interleaved', None)

        # Restore frequency response if available
        if 'frequency_response_interleaved' in fir_data:
            state.fir_freq_response_interleaved = {
                'freqs': np.array(fir_data['frequency_response_interleaved']['freqs']),
                'magnitude': np.array(fir_data['frequency_response_interleaved']['magnitude']),
                'phase': np.array(fir_data['frequency_response_interleaved']['phase']),
            }

        # Check sample rate match (interleaved is at 2x sample rate)
        if state.fir_calibration_samplerate_interleaved is not None:
            expected_interleaved_rate = current_samplerate_hz * 2  # 6.4 GHz
            if abs(expected_interleaved_rate - state.fir_calibration_samplerate_interleaved) > 1e6:
                if show_dialogs:
                    reply = QMessageBox.question(
                    parent_window, "Sample Rate Mismatch",
                    f"Interleaved FIR calibration was performed at {state.fir_calibration_samplerate_interleaved/1e9:.3f} GS/s,\n"
                    f"but current interleaved sample rate is {expected_interleaved_rate/1e9:.3f} GS/s.\n\n"
                    f"The correction may not be accurate. Continue anyway?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                    if reply == QMessageBox.No:
                        state.fir_coefficients_interleaved = None
                        state.fir_calibration_samplerate_interleaved = None
                        state.fir_freq_response_interleaved = None
                        # Don't return False here - other modes might still be loaded
                else:
                    print(f"Warning: Interleaved FIR calibration sample rate mismatch (continuing anyway)")
                    if not has_normal_in_file and not has_oversample_in_file and not has_twochannel_in_file:
                        return False

    # Load two-channel mode calibration if present
    if has_twochannel_in_file:
        state.fir_coefficients_twochannel = np.array(fir_data['fir_coefficients_twochannel'])
        state.fir_calibration_samplerate_twochannel = fir_data.get('calibration_samplerate_hz_twochannel', None)

        # Restore frequency response if available
        if 'frequency_response_twochannel' in fir_data:
            state.fir_freq_response_twochannel = {
                'freqs': np.array(fir_data['frequency_response_twochannel']['freqs']),
                'magnitude': np.array(fir_data['frequency_response_twochannel']['magnitude']),
                'phase': np.array(fir_data['frequency_response_twochannel']['phase']),
            }

        # Check sample rate match (two-channel is at half sample rate)
        if state.fir_calibration_samplerate_twochannel is not None:
            expected_twochannel_rate = current_samplerate_hz / 2  # 1.6 GHz
            if abs(expected_twochannel_rate - state.fir_calibration_samplerate_twochannel) > 1e6:
                if show_dialogs:
                    reply = QMessageBox.question(
                    parent_window, "Sample Rate Mismatch",
                    f"Two-channel FIR calibration was performed at {state.fir_calibration_samplerate_twochannel/1e9:.3f} GS/s,\n"
                    f"but current two-channel sample rate is {expected_twochannel_rate/1e9:.3f} GS/s.\n\n"
                    f"The correction may not be accurate. Continue anyway?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                    if reply == QMessageBox.No:
                        state.fir_coefficients_twochannel = None
                        state.fir_calibration_samplerate_twochannel = None
                        state.fir_freq_response_twochannel = None
                        # Don't return False here - other modes might still be loaded
                else:
                    print(f"Warning: Two-channel FIR calibration sample rate mismatch (continuing anyway)")
                    if not has_normal_in_file and not has_oversample_in_file and not has_interleaved_in_file:
                        return False

    # Enable correction (only if requested)
    if enable_corrections:
        state.fir_correction_enabled = True

    # Build success message based on what was loaded
    loaded_modes = []
    if has_normal_in_file and state.fir_coefficients is not None:
        loaded_modes.append("Normal")
    if has_oversample_in_file and state.fir_coefficients_oversample[0] is not None:
        loaded_modes.append("Oversampling")
    if has_interleaved_in_file and state.fir_coefficients_interleaved is not None:
        loaded_modes.append("Interleaved")
    if has_twochannel_in_file and state.fir_coefficients_twochannel is not None:
        loaded_modes.append("Two-channel")

    # Update checkbox state to reflect availability for current mode
    # Always call this to enable the menu item when corrections are loaded
    if hasattr(parent_window, 'update_fir_checkbox_state'):
        parent_window.update_fir_checkbox_state()
    elif enable_corrections:
        # Fallback if update method doesn't exist and corrections should be enabled
        ui.actionApply_FIR_corrections.setEnabled(True)
        ui.actionApply_FIR_corrections.setChecked(True)

    # Show success message (only if show_dialogs is True)
    mode_text = ", ".join(loaded_modes)
    if show_dialogs:
        if enable_corrections:
            message_suffix = "Correction will be enabled for modes with available calibration data."
        else:
            message_suffix = "Corrections loaded but not enabled."
        QMessageBox.information(parent_window, "FIR Filter Loaded",
                              f"{mode_text} FIR filter loaded successfully from:\n{filename}\n\n{message_suffix}")

    status = "enabled" if enable_corrections else "not enabled"
    print(f"FIR filter ({mode_text}) loaded from {filename} (corrections {status})")

    return True
