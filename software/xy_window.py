# xy_window.py

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QComboBox
from PyQt5.QtCore import pyqtSignal


class XYWindow(QtWidgets.QWidget):
    """Popup window showing XY plot mode."""

    # Signal emitted when the window is closed
    window_closed = pyqtSignal()

    def __init__(self, parent=None, state=None, plot_manager=None):
        super().__init__(parent)
        self.setWindowTitle("XY Plot")
        self.setWindowFlags(QtCore.Qt.Window)
        self.state = state
        self.plot_manager = plot_manager
        self.parent_window = parent

        # Default channel selections (will be set in populate_channel_combos)
        self.y_channel = 0
        self.x_channel = 0

        # Setup main layout
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        # Add channel selection controls at the top
        controls_layout = QHBoxLayout()

        # Y channel selector
        controls_layout.addWidget(QLabel("Y Channel:"))
        self.y_channel_combo = QComboBox()
        self.y_channel_combo.currentIndexChanged.connect(self.on_y_channel_changed)
        controls_layout.addWidget(self.y_channel_combo)

        controls_layout.addSpacing(20)

        # X channel selector
        controls_layout.addWidget(QLabel("X Channel:"))
        self.x_channel_combo = QComboBox()
        self.x_channel_combo.currentIndexChanged.connect(self.on_x_channel_changed)
        controls_layout.addWidget(self.x_channel_combo)

        controls_layout.addStretch()

        layout.addLayout(controls_layout)

        # Create plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot = self.plot_widget.getPlotItem()

        # Match styling to main plot
        self.plot_widget.setBackground(QColor('black'))
        self.plot.getAxis("left").setTickSpacing(1, .1)
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.8)

        # Set font and styling to match main plot
        font = QtWidgets.QApplication.font()
        font.setPixelSize(11)

        for axis in ['bottom', 'left']:
            axis_item = self.plot.getAxis(axis)
            axis_item.setStyle(tickFont=font)
            axis_item.setPen('grey')
            axis_item.setTextPen('grey')

        # Enable mouse interactions for pan/zoom
        self.plot.setMouseEnabled(x=True, y=True)

        # Create the XY plot line with bright green color (classic oscilloscope look)
        self.xy_line = self.plot.plot(pen=pg.mkPen(color="#00FF00", width=2), name="XY_Plot", skipFiniteCheck=True, connect="finite")

        layout.addWidget(self.plot_widget)
        self.setLayout(layout)

        # Populate channel dropdowns
        self.populate_channel_combos()

        # Set default size
        self.resize(600, 600)

    def populate_channel_combos(self):
        """Populate the channel combo boxes with available channels only."""
        total_channels = self.state.num_board * self.state.num_chan_per_board

        self.y_channel_combo.blockSignals(True)
        self.x_channel_combo.blockSignals(True)

        self.y_channel_combo.clear()
        self.x_channel_combo.clear()

        available_channels = []

        for ch_idx in range(total_channels):
            board_idx = ch_idx // self.state.num_chan_per_board
            local_ch = ch_idx % self.state.num_chan_per_board

            # Check if this channel is available
            # For single-channel mode (not two-channel), only ch 0 is available
            # For two-channel mode, both ch 0 and ch 1 are available
            if not self.state.dotwochannel[board_idx] and local_ch != 0:
                continue  # Skip ch 1 if board is in single-channel mode

            # Use custom name if available, otherwise use default naming
            if self.state.channel_names[ch_idx]:
                label = self.state.channel_names[ch_idx]
            else:
                label = f"Board {board_idx} Ch {local_ch}"

            self.y_channel_combo.addItem(label, ch_idx)
            self.x_channel_combo.addItem(label, ch_idx)
            available_channels.append(ch_idx)

        # Set defaults to first two available channels
        if len(available_channels) >= 1:
            self.y_channel = available_channels[0]
            self.y_channel_combo.setCurrentIndex(0)

        if len(available_channels) >= 2:
            self.x_channel = available_channels[1]
            self.x_channel_combo.setCurrentIndex(1)

        self.y_channel_combo.blockSignals(False)
        self.x_channel_combo.blockSignals(False)

        # Update axis labels and colors after population
        self.update_axis_labels()
        self.update_axis_colors()

    def on_y_channel_changed(self, index):
        """Handle Y channel selection change."""
        if index >= 0:
            self.y_channel = self.y_channel_combo.itemData(index)
            self.update_axis_labels()
            self.update_axis_colors()

    def on_x_channel_changed(self, index):
        """Handle X channel selection change."""
        if index >= 0:
            self.x_channel = self.x_channel_combo.itemData(index)
            self.update_axis_labels()
            self.update_axis_colors()

    def update_axis_labels(self):
        """Update the axis labels based on selected channels."""
        y_label = self.y_channel_combo.currentText()
        x_label = self.x_channel_combo.currentText()
        self.plot.setLabel('left', f"{y_label} (V/div)")
        self.plot.setLabel('bottom', f"{x_label} (V/div)")

    def update_axis_colors(self):
        """Update axis colors to match the selected channel colors."""
        if self.plot_manager is None:
            return

        # Get the colors for the selected channels from plot_manager
        if self.y_channel < len(self.plot_manager.linepens):
            y_color = self.plot_manager.linepens[self.y_channel].color()
            left_axis = self.plot.getAxis('left')
            left_axis.setPen(y_color)
            left_axis.setTextPen(y_color)

        if self.x_channel < len(self.plot_manager.linepens):
            x_color = self.plot_manager.linepens[self.x_channel].color()
            bottom_axis = self.plot.getAxis('bottom')
            bottom_axis.setPen(x_color)
            bottom_axis.setTextPen(x_color)

    def update_xy_plot(self, xydata):
        """Update the XY plot with new data.

        Args:
            xydata: The full xydata array from main_window
        """
        # Get data for selected channels
        if self.x_channel < len(xydata) and self.y_channel < len(xydata):
            x_data = xydata[self.x_channel][1]  # Use Y data (voltage) from X channel
            y_data = xydata[self.y_channel][1]  # Use Y data (voltage) from Y channel

            # Make sure arrays are the same length
            min_len = min(len(x_data), len(y_data))
            x_data = x_data[:min_len]
            y_data = y_data[:min_len]

            self.xy_line.setData(x=x_data, y=y_data, skipFiniteCheck=True)

    def showEvent(self, event):
        """Called when window is shown - set initial range."""
        super().showEvent(event)
        self.plot.setRange(xRange=(-5, 5), yRange=(-5, 5), padding=0.01)

    def closeEvent(self, event):
        """Called when window is closed - emit signal and update state."""
        self.window_closed.emit()
        super().closeEvent(event)
