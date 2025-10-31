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

    def __init__(self):
        self.num_taps = 64  # FIR filter length
        self.num_averages = 50  # Number of waveforms to average for calibration
        self.regularization = 0.05  # Prevents over-boosting weak frequencies

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
        # Compute FFTs
        measured_fft = np.fft.rfft(measured)
        ideal_fft = np.fft.rfft(ideal)

        # Avoid division by zero - square wave has zero energy at even harmonics
        # Add small epsilon to prevent inf/nan
        epsilon = 1e-10 * np.max(np.abs(ideal_fft))
        H_complex = measured_fft / (ideal_fft + epsilon)

        # Compute magnitude and phase
        H_mag = np.abs(H_complex)
        H_phase = np.angle(H_complex)

        # Frequency array
        freqs = np.fft.rfftfreq(len(measured), d=1/sample_rate_hz)

        return {
            'freqs': freqs,
            'H_complex': H_complex,
            'magnitude': H_mag,
            'phase': H_phase
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

        # Identify harmonics with significant energy (odd harmonics of 10 MHz)
        # Square wave has harmonics at f, 3f, 5f, 7f, ...
        fundamental = 10e6  # 10 MHz

        # Create correction magnitude: C_mag(f) = 1 / H_mag(f)
        # With regularization to prevent over-boosting
        H_mag_max = np.max(H_mag)
        regularization_factor = self.regularization * H_mag_max

        correction_mag = 1.0 / (H_mag + regularization_factor)

        # Limit maximum correction to prevent noise amplification
        max_correction_factor = 10 ** (max_correction_db / 20)  # Convert dB to linear
        correction_mag = np.clip(correction_mag, 1/max_correction_factor, max_correction_factor)

        # Smooth the correction to avoid sharp transitions
        # Use median filter to remove outliers, then smooth
        window_length = min(11, len(correction_mag) // 10)
        if window_length >= 3 and window_length % 2 == 1:  # Must be odd
            correction_mag = signal.medfilt(correction_mag, kernel_size=window_length)

        # Apply additional smoothing
        if len(correction_mag) > 20:
            window_length = min(15, len(correction_mag) // 5)
            if window_length >= 5 and window_length % 2 == 1:
                polyorder = min(3, window_length - 2)
                correction_mag = signal.savgol_filter(correction_mag, window_length=window_length, polyorder=polyorder)

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

        # Interpolate correction to fft_length//2 + 1 points
        from scipy.interpolate import interp1d

        new_freqs = np.linspace(0, sample_rate_hz/2, fft_length//2 + 1)

        # Interpolate magnitude and phase separately
        interp_mag = interp1d(freqs, correction_mag, kind='linear', fill_value='extrapolate')
        interp_phase = interp1d(freqs, correction_phase, kind='linear', fill_value='extrapolate')

        correction_mag_interp = interp_mag(new_freqs)
        correction_phase_interp = interp_phase(new_freqs)

        # Reconstruct complex correction
        correction_complex_interp = correction_mag_interp * np.exp(1j * correction_phase_interp)

        # IFFT to get time-domain impulse response
        fir_full = np.fft.irfft(correction_complex_interp, n=fft_length)

        # Truncate to desired number of taps and apply window
        fir_coefficients = fir_full[:self.num_taps]

        # Apply Blackman window to reduce ringing
        window = signal.windows.blackman(self.num_taps)
        fir_coefficients = fir_coefficients * window

        # Normalize to approximately unity gain at DC
        dc_gain = np.sum(fir_coefficients)
        if abs(dc_gain) > 0.1:
            fir_coefficients = fir_coefficients / dc_gain

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

            # Compute frequency response
            freq_response = self.compute_frequency_response(measured_aligned, ideal, sample_rate_hz)

            # Design correction FIR filter
            fir_coefficients = self.design_correction_fir(freq_response, sample_rate_hz)

            # Validate the correction
            validation = self.validate_correction(measured_aligned, ideal, fir_coefficients)

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
    # Check if calibration exists
    if state.fir_coefficients is None:
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

    # Prepare data to save
    fir_data = {
        'fir_coefficients': state.fir_coefficients.tolist(),
        'calibration_samplerate_hz': state.fir_calibration_samplerate,
        'calibration_downsample': 0,  # Calibration is always at downsample=0 (max rate)
        'num_taps': len(state.fir_coefficients),
        'calibration_type': '10MHz_square_wave',
        'software_version': state.softwareversion,
    }

    # Optionally save frequency response if available
    if state.fir_freq_response is not None:
        fir_data['frequency_response'] = {
            'freqs': state.fir_freq_response['freqs'].tolist(),
            'magnitude': state.fir_freq_response['magnitude'].tolist(),
            'phase': state.fir_freq_response['phase'].tolist(),
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

    # Validate data
    if 'fir_coefficients' not in fir_data or fir_data['fir_coefficients'] is None:
        QMessageBox.warning(parent_window, "Load Failed", "Invalid FIR filter file: missing coefficients.")
        return False

    # Restore calibration data
    state.fir_coefficients = np.array(fir_data['fir_coefficients'])
    state.fir_calibration_samplerate = fir_data.get('calibration_samplerate_hz', None)

    # Restore frequency response if available
    if 'frequency_response' in fir_data:
        state.fir_freq_response = {
            'freqs': np.array(fir_data['frequency_response']['freqs']),
            'magnitude': np.array(fir_data['frequency_response']['magnitude']),
            'phase': np.array(fir_data['frequency_response']['phase']),
        }

    # Check if sample rate matches current sample rate
    current_samplerate_hz = state.samplerate * 1e9
    calibration_downsample = fir_data.get('calibration_downsample', 0)

    if state.fir_calibration_samplerate is not None:
        # Check if we're at the same base sample rate (downsample=0)
        if abs(current_samplerate_hz - state.fir_calibration_samplerate) > 1e6:  # 1 MHz tolerance
            # Different base sample rates
            reply = QMessageBox.question(
                parent_window, "Sample Rate Mismatch",
                f"FIR calibration was performed at {state.fir_calibration_samplerate/1e9:.3f} GS/s (downsample={calibration_downsample}),\n"
                f"but current base sample rate is {current_samplerate_hz/1e9:.3f} GS/s.\n\n"
                f"The correction may not be accurate. Continue anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                # Clear loaded data
                state.fir_coefficients = None
                state.fir_calibration_samplerate = None
                state.fir_freq_response = None
                return False
        elif state.downsample > 0:
            # Same base rate but currently downsampled - inform user
            QMessageBox.information(
                parent_window, "FIR Filter Loaded",
                f"FIR calibration was performed at maximum sample rate (downsample=0).\n"
                f"You are currently using downsample={state.downsample}.\n\n"
                f"The correction will be applied, but accuracy may be reduced at downsampled rates.\n"
                f"For best results, use downsample=0 (maximum sample rate)."
            )

    # Enable correction
    state.fir_correction_enabled = True
    ui.actionApply_FIR_corrections.setChecked(True)

    if hasattr(parent_window, 'statusBar'):
        parent_window.statusBar().showMessage(f"FIR filter loaded from {filename}", 5000)
    print(f"FIR filter loaded from {filename}")

    # Show success message if we didn't already show the downsample warning
    if not (state.downsample > 0 and abs(current_samplerate_hz - state.fir_calibration_samplerate) <= 1e6):
        QMessageBox.information(parent_window, "FIR Filter Loaded",
                              f"FIR filter loaded successfully from:\n{filename}\n\n"
                              f"Correction is now enabled.")

    return True
