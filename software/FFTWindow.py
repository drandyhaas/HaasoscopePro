# FFTWindow.py

import time
from datetime import datetime
from math import log
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, loadUiType
from PyQt5.QtGui import QColor
from scipy.signal import find_peaks
from utils import get_pwd

# Load the UI template for the FFT Window
FFTWindowTemplate, FFTTemplateBaseClass = loadUiType(get_pwd() + "/HaasoscopeProFFT.ui")


class FFTWindow(FFTTemplateBaseClass):
    """
    A self-contained window for displaying FFT plots.

    This class manages its own plot items and updates. The main application
    interacts with it by calling the `update_plot` method.
    """

    def __init__(self):
        super().__init__()
        self.ui = FFTWindowTemplate()
        self.ui.setupUi(self)

        # Connect internal actions
        self.ui.actionTake_screenshot.triggered.connect(self.take_screenshot)
        self.ui.actionLog_scale.triggered.connect(self.log_scale)
        self.ui.actionPeak_hold.triggered.connect(self.toggle_peak_hold)
        self.ui.actionShow_peak_labels.triggered.connect(self.toggle_peak_labels)

        # Configure the plot widget
        self.plot = self.ui.plot
        self.plot.setLabel('bottom', 'Frequency (MHz)')
        self.plot.setLabel('left', 'Amplitude')
        self.plot.showGrid(x=True, y=True, alpha=.8)
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=True, y=False)  # Allow mouse pan/zoom on X axis ONLY
        self.plot.setBackground(QColor('black'))

        self.user_panned_zoomed = False
        self.plot.sigRangeChanged.connect(self.on_view_changed)

        # --- Plot Item Management ---
        self.fft_lines = {}  # Holds plot items for each channel: {'CH1': PlotDataItem, ...}

        # --- Analysis Plot Items ---
        self.peak_hold_line = self.plot.plot(pen=pg.mkPen(color=(255, 255, 0, 150), width=1))
        self.peak_text_labels = []

        # --- State Variables ---
        self.dolog = False
        self.peak_hold_enabled = True
        self.peak_hold_data = None
        self.show_labels_enabled = True
        self.ui.actionPeak_hold.setChecked(True)
        self.ui.actionShow_peak_labels.setChecked(True)

        # State variables for stable auto-ranging
        self.last_time = 0
        self.yrange_max = 0.1
        self.yrange_min = 1e-5
        self.new_plot = True

    def reset_analysis_state(self):
        """Resets all analysis data for a clean start."""
        self.peak_hold_data = None
        self.peak_hold_line.clear()
        self.clear_peak_labels()

    def on_view_changed(self):
        """Signal handler for when the user manually pans or zooms."""
        self.user_panned_zoomed = True

    def clear_peak_labels(self):
        """Removes all existing peak labels from the plot."""
        for label in self.peak_text_labels:
            self.plot.removeItem(label)
        self.peak_text_labels.clear()

    def toggle_peak_hold(self, checked):
        """Activates or deactivates the peak hold feature."""
        self.peak_hold_enabled = checked
        if not self.peak_hold_enabled:
            self.peak_hold_data = None
            self.peak_hold_line.clear()
            self.clear_peak_labels()
        else:
            self.peak_hold_data = None

    def toggle_peak_labels(self, checked):
        """Activates or deactivates the peak labels."""
        self.show_labels_enabled = checked
        if not self.show_labels_enabled:
            self.clear_peak_labels()

    def clear_plot(self, channel_name):
        """Removes a specific channel's trace from the plot."""
        if channel_name in self.fft_lines:
            line_to_remove = self.fft_lines.pop(channel_name)
            self.plot.removeItem(line_to_remove)

    def update_plot(self, channel_name, x_data, y_data, pen, title_text, xlabel_text, is_active_channel):
        """
        Public method to update a channel's FFT plot.
        Advanced features are linked to the active channel.
        """
        # --- Multi-channel Trace Update ---
        if channel_name not in self.fft_lines:
            self.fft_lines[channel_name] = self.plot.plot(pen=pen)

        self.fft_lines[channel_name].setData(x_data, y_data)

        self.plot.setTitle(title_text)
        self.plot.setLabel('bottom', xlabel_text)

        if not self.user_panned_zoomed:
            self.plot.enableAutoRange(axis='x')

        # All analysis is performed only on the active channel's data
        if is_active_channel:
            self.clear_peak_labels()

            # --- Peak Hold Logic ---
            if self.peak_hold_enabled:
                if self.peak_hold_data is None or len(self.peak_hold_data) != len(y_data):
                    self.peak_hold_data = y_data.copy()
                else:
                    self.peak_hold_data = np.maximum(self.peak_hold_data, y_data)
                self.peak_hold_line.setData(x_data, self.peak_hold_data)

                # --- Peak Label Logic ---
                if self.show_labels_enabled and len(x_data) > 0:
                    min_freq_dist = (x_data[-1] - x_data[0]) * 0.05

                    # Adapt peak finding strategy based on the y-axis scale
                    if self.dolog:
                        # On a log scale, find peaks that are significantly above the median
                        log_data = np.log10(self.peak_hold_data + 1e-10)  # Add epsilon to avoid log(0)
                        median_log = np.median(log_data)
                        # A threshold of 1 means peaks must be at least 1 decade (10x) above the median
                        peak_height_threshold = median_log + 0.5
                        peaks, _ = find_peaks(log_data, height=peak_height_threshold)
                    else:
                        # On a linear scale, use a fraction of the max height
                        peak_height_threshold = np.max(self.peak_hold_data) * 0.1
                        peaks, _ = find_peaks(self.peak_hold_data, height=peak_height_threshold)

                    if len(peaks) > 0:
                        peak_amplitudes = self.peak_hold_data[peaks]
                        sorted_peak_indices = peaks[np.argsort(peak_amplitudes)[::-1]]
                        labeled_peak_freqs = []
                        for peak_idx in sorted_peak_indices:
                            if len(labeled_peak_freqs) >= 20: break
                            current_peak_freq = x_data[peak_idx]
                            is_far_enough = all(abs(current_peak_freq - f) > min_freq_dist for f in labeled_peak_freqs)
                            if is_far_enough:
                                peak_amp = self.peak_hold_data[peak_idx]
                                text_item = pg.TextItem(text=f"{current_peak_freq:.2f}", color=(255, 255, 0),
                                                        anchor=(0.5, 1.5))
                                text_item.setPos(current_peak_freq, np.log10(peak_amp) if self.dolog else peak_amp)
                                self.plot.addItem(text_item)
                                self.peak_text_labels.append(text_item)
                                labeled_peak_freqs.append(current_peak_freq)
            else:
                self.peak_hold_line.clear()  # If peak hold is off, ensure line is clear

        # --- Y-Axis Ranging ---
        self.plot.enableAutoRange(axis='y', enable=False)
        if len(y_data) == 0: return

        ydatamax = np.max(y_data)
        if self.peak_hold_enabled and self.peak_hold_data is not None and is_active_channel:
            ydatamax = np.max(self.peak_hold_data)

        ydatamin = np.min(y_data)
        now = time.time()

        time_elapsed = (now - self.last_time) > 3.0
        peak_exceeded = self.yrange_max < ydatamax
        floor_dropped = self.yrange_min > ydatamin * 100

        if self.new_plot or time_elapsed or peak_exceeded or floor_dropped:
            self.new_plot = False
            self.last_time = now
            self.yrange_max = ydatamax * 1.2
            self.yrange_min = max(ydatamin, 1e-10)

            if self.dolog:
                self.plot.setYRange(log(self.yrange_min, 10), log(self.yrange_max, 10))
            else:
                self.plot.setYRange(0, self.yrange_max)

    def take_screenshot(self):
        pixmap = self.grab()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"HaasoscopePro_FFT_{timestamp}.png"
        pixmap.save(filename)
        print(f"Screenshot saved as {filename}")

    def log_scale(self):
        self.dolog = self.ui.actionLog_scale.isChecked()
        self.plot.setLogMode(x=False, y=self.dolog)
        self.plot.setLabel('left', 'log10 Amplitude' if self.dolog else 'Amplitude')
        self.new_plot = True