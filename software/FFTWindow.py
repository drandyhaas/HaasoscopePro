# FFTWindow.py

import time
from datetime import datetime
from math import log
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, loadUiType
from PyQt5.QtGui import QColor
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

        # Configure the plot widget
        self.plot = self.ui.plot
        self.plot.setLabel('bottom', 'Frequency (MHz)')
        self.plot.setLabel('left', 'Amplitude')
        self.plot.showGrid(x=True, y=True, alpha=.8)
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=True, y=True)  # Allow user to pan/zoom the FFT
        self.plot.setBackground(QColor('black'))

        # Create the plot line items
        self.fft_line = self.plot.plot(pen=pg.mkPen(color="w"), name="fft_plot")
        self.peak_hold_line = self.plot.plot(pen=pg.mkPen(color=(255, 255, 0, 150), width=1.5))

        self.dolog = False
        self.peak_hold_enabled = False
        self.peak_hold_data = None

        # State variables for stable auto-ranging of the Y-axis
        self.last_time = 0
        self.yrange_max = 0.1
        self.yrange_min = 1e-5
        self.new_plot = True

    def toggle_peak_hold(self, checked):
        """Activates or deactivates the peak hold feature."""
        self.peak_hold_enabled = checked
        if not self.peak_hold_enabled:
            # When disabled, clear the data and the plot line
            self.peak_hold_data = None
            self.peak_hold_line.clear()
        else:
            # When enabled, reset the data to start a new peak hold
            self.peak_hold_data = None

    def update_plot(self, x_data, y_data, pen, title_text, xlabel_text):
        """
        Public method called by the main window to update the FFT plot with new data.
        This method handles all internal plot updates, including stable auto-ranging.
        """
        # Set the plot data, pen, and labels
        self.fft_line.setData(x_data, y_data)
        self.fft_line.setPen(pen)
        self.plot.setTitle(title_text)
        self.plot.setLabel('bottom', xlabel_text)
        self.plot.enableAutoRange(axis='x')

        # --- Peak Hold Logic ---
        if self.peak_hold_enabled:
            if self.peak_hold_data is None or len(self.peak_hold_data) != len(y_data):
                # If starting a new peak hold, copy the first dataset
                self.peak_hold_data = y_data.copy()
            else:
                # Otherwise, update with the element-wise maximum
                self.peak_hold_data = np.maximum(self.peak_hold_data, y_data)

            # Set the data for the peak hold trace
            self.peak_hold_line.setData(x_data, self.peak_hold_data)

        # Use stable, manual auto-ranging for the Y-axis
        self.plot.enableAutoRange(axis='y', enable=False)

        # Ensure y_data is not empty before finding min/max
        if len(y_data) == 0:
            return

        ydatamax = np.max(y_data)
        ydatamin = np.min(y_data)
        now = time.time()

        # Define conditions for when to update the Y-range
        time_elapsed = (now - self.last_time) > 3.0
        peak_exceeded = self.yrange_max < ydatamax
        floor_dropped = self.yrange_min > ydatamin * 100

        if self.new_plot or time_elapsed or peak_exceeded or floor_dropped:
            self.new_plot = False
            self.last_time = now
            self.yrange_max = ydatamax * 1.2
            self.yrange_min = max(ydatamin, 1e-10)  # Avoid log(0)

            if self.dolog:
                self.plot.setYRange(log(self.yrange_min, 10), log(self.yrange_max, 10))
            else:
                self.plot.setYRange(0, self.yrange_max)

    def take_screenshot(self):
        """Captures the FFT window and saves it to a timestamped PNG file."""
        pixmap = self.grab()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"HaasoscopePro_FFT_{timestamp}.png"
        pixmap.save(filename)
        print(f"Screenshot saved as {filename}")

    def log_scale(self):
        """Toggles the Y-axis between linear and logarithmic scales."""
        self.dolog = self.ui.actionLog_scale.isChecked()
        self.plot.setLogMode(x=False, y=self.dolog)
        self.plot.setLabel('left', 'log10 Amplitude' if self.dolog else 'Amplitude')
        self.new_plot = True  # Force a Y-range rescale on the next update