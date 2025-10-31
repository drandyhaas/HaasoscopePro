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

    def __init__(self, num_taps=64):
        self.num_taps = num_taps  # FIR filter length (64, 128, or 256)
        self.num_averages = 2*100  # Number of waveforms to average for calibration
        self.regularization = 0.001  # Small epsilon to prevent division by zero (was 0.05, too aggressive)

    def generate_ideal_square_wave(self, frequency_hz, sample_rate_hz, num_samples, phase_offset=0):
        """
        Generate ideal square wave with specified parameters

        Args:
            frequency_hz: Frequency of square wave (e.g., 10e6 for 10 MHz)
            sample_rate_hz: Sample rate in Hz
            num_samples: Number of samples to generate
            phase_offset: Phase offset in radians (for alignment with measured signal)

        Returns:
            numpy array of square wave values (+1 or -1)
        """
        t = np.arange(num_samples) / sample_rate_hz
        square = signal.square(2 * np.pi * frequency_hz * t + phase_offset)
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

    def compute_frequency_response(self, measured, ideal, sample_rate_hz):
        """
        Compute frequency response H(f) = FFT(measured) / FFT(ideal)

        Args:
            measured: Measured waveform (aligned to ideal)
            ideal: Ideal reference waveform
            sample_rate_hz: Sample rate in Hz

        Returns:
            dict with keys:
                'freqs': Frequency array (Hz)
                'H_complex': Complex frequency response
                'magnitude': Magnitude response |H(f)|
                'phase': Phase response in radians
        """
        # Compute FFTs directly without amplitude normalization
        # The FIR filter will include overall gain correction as part of frequency response
        measured_fft = np.fft.rfft(measured)
        ideal_fft = np.fft.rfft(ideal)

        # Square wave has energy ONLY at odd harmonics (10, 30, 50, 70 MHz...)
        # At other frequencies, both FFTs are near-zero, causing H(f) = 0/0 = garbage
        # Solution: Only compute H(f) where ideal signal has significant energy

        # Find frequencies with significant energy in ideal signal
        ideal_magnitude = np.abs(ideal_fft)
        max_ideal_mag = np.max(ideal_magnitude)
        threshold = 0.01 * max_ideal_mag  # 1% of peak is "significant"

        # Initialize H_complex to 1.0 (no correction) everywhere
        H_complex = np.ones_like(measured_fft, dtype=complex)

        # Only compute H(f) at frequencies with significant energy
        significant_bins = ideal_magnitude > threshold
        H_complex[significant_bins] = measured_fft[significant_bins] / ideal_fft[significant_bins]

        # Force DC bin to 1.0 (no correction for DC offset)
        H_complex[0] = 1.0 + 0j

        # Compute magnitude and phase
        H_mag = np.abs(H_complex)
        H_phase = np.angle(H_complex)

        # Frequency array
        freqs = np.fft.rfftfreq(len(measured), d=1/sample_rate_hz)

        # Diagnostic output
        print(f"Frequency response measurement:")
        print(f"  - Number of significant frequency bins: {np.sum(significant_bins)} / {len(freqs)}")
        print(f"  - H(f) magnitude range: [{np.min(H_mag):.4f}, {np.max(H_mag):.4f}]")
        print(f"  - H(f) magnitude at DC: {H_mag[0]:.4f}")
        # Find the 10 MHz bin (approximately)
        idx_10MHz = np.argmin(np.abs(freqs - 10e6))
        print(f"  - H(f) magnitude near 10 MHz: {H_mag[idx_10MHz]:.4f} at {freqs[idx_10MHz]/1e6:.1f} MHz")
        # Show frequencies with significant energy
        sig_freqs = freqs[significant_bins]
        if len(sig_freqs) > 0:
            print(f"  - Calibration frequencies: {', '.join([f'{f/1e6:.1f}' for f in sig_freqs[:10]])} MHz..." if len(sig_freqs) > 10 else f"  - Calibration frequencies: {', '.join([f'{f/1e6:.1f}' for f in sig_freqs])} MHz")

        return {
            'freqs': freqs,
            'H_complex': H_complex,
            'magnitude': H_mag,
            'phase': H_phase,
            'significant_bins': significant_bins
        }

    def design_correction_fir(self, freq_response, sample_rate_hz, max_correction_db=20):
        """
        Design FIR filter to correct frequency response

        For square wave calibration:
        - Only odd harmonics have energy (10, 30, 50, ... MHz)
        - Compute correction at those frequencies
        - Interpolate smoothly between them

        Args:
            freq_response: Dict from compute_frequency_response()
            sample_rate_hz: Sample rate in Hz
            max_correction_db: Maximum boost/cut in dB (prevents over-correction)

        Returns:
            fir_coefficients: 64-tap FIR filter coefficients
        """
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

        # Only compute correction at significant frequencies
        correction_mag[significant_bins] = 1.0 / (H_mag[significant_bins] + regularization_factor)

        # Limit maximum correction to prevent noise amplification
        max_correction_factor = 10 ** (max_correction_db / 20)  # Convert dB to linear
        correction_mag = np.clip(correction_mag, 1/max_correction_factor, max_correction_factor)

        # IMPORTANT: filtfilt applies the filter twice (forward + backward pass)
        # So the effective correction is correction_mag^2
        # We need to take square root so that after filtfilt we get the desired correction
        correction_mag = np.sqrt(correction_mag)

        # NOTE: Skip smoothing for square wave calibration
        # Square wave has sparse spectrum (only odd harmonics), so smoothing
        # would average each harmonic peak with many neighboring zero-energy bins,
        # destroying the correction information. The interpolation step below
        # will naturally smooth between harmonics.

        # Correction phase: invert the measured phase
        correction_phase = -H_phase

        # Construct complex correction response
        correction_complex = correction_mag * np.exp(1j * correction_phase)

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

    def calibrate_from_data(self, waveform_data_list, sample_rate_hz):
        """
        Complete calibration process from list of captured waveforms

        Args:
            waveform_data_list: List of numpy arrays (captured waveforms)
            sample_rate_hz: Sample rate in Hz

        Returns:
            dict with:
                'fir_coefficients': 64-tap FIR filter
                'freq_response': Frequency response dict
                'validation': Validation results dict
                'success': True if calibration successful
                'message': Status message
        """
        try:
            # Average the captured waveforms
            measured = np.mean(waveform_data_list, axis=0)

            # Estimate phase offset from measured signal
            phase_offset = self.estimate_phase_offset(measured, 10e6, sample_rate_hz)

            # Generate ideal 10 MHz square wave with estimated phase
            ideal = self.generate_ideal_square_wave(10e6, sample_rate_hz, len(measured), phase_offset)

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
            print(f"  - Measured signal range: [{np.min(measured_aligned):.4f}, {np.max(measured_aligned):.4f}]")
            print(f"  - Ideal signal range: [{np.min(ideal):.4f}, {np.max(ideal):.4f}]")
            print(f"  - Cross-correlation shift: {shift} samples")
            print(f"  - Measured RMS: {np.std(measured_aligned):.4f}")
            print(f"  - Amplitude normalization: {amplitude_scale:.4f}x (for H(f) computation only)")

            # Compute frequency response using normalized signals
            # This H(f) will show only frequency-dependent variations, not overall gain
            freq_response = self.compute_frequency_response(measured_normalized, ideal, sample_rate_hz)

            # Design correction FIR filter
            fir_coefficients = self.design_correction_fir(freq_response, sample_rate_hz)

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

    if not has_normal and not has_oversample and not has_interleaved:
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


def load_fir_filter(parent_window, state, ui):
    """
    Load FIR calibration from a file.

    Args:
        parent_window: Parent QWidget for dialogs
        state: ScopeState object to store loaded calibration
        ui: UI object for checkbox updates

    Returns:
        True if load successful, False otherwise
    """
    # Open file dialog
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
        QMessageBox.critical(parent_window, "Load Failed", f"Failed to load FIR filter:\n{e}")
        return False

    # Check which calibrations are present in the file
    has_normal_in_file = 'fir_coefficients' in fir_data and fir_data['fir_coefficients'] is not None
    has_oversample_in_file = ('fir_coefficients_board0' in fir_data and fir_data['fir_coefficients_board0'] is not None and
                             'fir_coefficients_board1' in fir_data and fir_data['fir_coefficients_board1'] is not None)
    has_interleaved_in_file = 'fir_coefficients_interleaved' in fir_data and fir_data['fir_coefficients_interleaved'] is not None

    if not has_normal_in_file and not has_oversample_in_file and not has_interleaved_in_file:
        QMessageBox.warning(parent_window, "Load Failed", "Invalid FIR filter file: missing coefficients.")
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
                    if not has_normal_in_file and not has_oversample_in_file:
                        return False

    # Enable correction
    state.fir_correction_enabled = True
    ui.actionApply_FIR_corrections.setChecked(True)

    # Build success message based on what was loaded
    loaded_modes = []
    if has_normal_in_file and state.fir_coefficients is not None:
        loaded_modes.append("Normal")
    if has_oversample_in_file and state.fir_coefficients_oversample[0] is not None:
        loaded_modes.append("Oversampling")
    if has_interleaved_in_file and state.fir_coefficients_interleaved is not None:
        loaded_modes.append("Interleaved")

    mode_text = ", ".join(loaded_modes)
    print(f"FIR filter ({mode_text}) loaded from {filename}")

    # Show success message
    QMessageBox.information(parent_window, "FIR Filter Loaded",
                          f"{mode_text} FIR filter loaded successfully from:\n{filename}\n\n"
                          f"Correction is now enabled.")

    return True
