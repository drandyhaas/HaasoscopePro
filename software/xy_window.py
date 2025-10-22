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
        # Can be either integer (physical channel) or string (math channel name)
        self.y_channel = 0
        self.x_channel = 0

        # Store math channel results for plotting
        self.math_results = {}

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

    def position_relative_to_main(self, main_window):
        """Position the window to the left of the main window with bottom edges aligned."""
        main_geometry = main_window.geometry()

        # Calculate position: 10 pixels to the right of main window's right edge
        x = main_geometry.x() + main_geometry.width() + 10

        # Align bottom edges
        y = main_geometry.y() + main_geometry.height() - self.height() - 32

        # Position to the left of main window with 10px gap
        x = main_geometry.x() - self.width() - 10

        self.move(x, y)

    def populate_channel_combos(self):
        """Populate the channel combo boxes with available channels only."""
        total_channels = self.state.num_board * self.state.num_chan_per_board

        self.y_channel_combo.blockSignals(True)
        self.x_channel_combo.blockSignals(True)

        self.y_channel_combo.clear()
        self.x_channel_combo.clear()

        available_channels = []

        # Add physical channels
        for ch_idx in range(total_channels):
            board_idx = ch_idx // self.state.num_chan_per_board
            local_ch = ch_idx % self.state.num_chan_per_board

            # Check if this channel is available
            # Skip if channel is disabled (due to oversampling, interleaving, etc.)
            if not self.state.channel_enabled[ch_idx]:
                continue

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

        # Add math channels if they exist
        if self.parent_window and hasattr(self.parent_window, 'math_window') and self.parent_window.math_window:
            for math_def in self.parent_window.math_window.math_channels:
                math_name = math_def['name']
                label = f"Math: {math_name}"
                # Use the math channel name as the data (string instead of int)
                self.y_channel_combo.addItem(label, math_name)
                self.x_channel_combo.addItem(label, math_name)
                available_channels.append(math_name)

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

        # Get color for Y channel
        if isinstance(self.y_channel, str):
            # Math channel - get color from math channel definition
            y_color = self._get_math_channel_color(self.y_channel)
        else:
            # Physical channel - get color from linepens
            if self.y_channel < len(self.plot_manager.linepens):
                y_color = self.plot_manager.linepens[self.y_channel].color()
            else:
                y_color = QColor('grey')

        left_axis = self.plot.getAxis('left')
        left_axis.setPen(y_color)
        left_axis.setTextPen(y_color)

        # Get color for X channel
        if isinstance(self.x_channel, str):
            # Math channel - get color from math channel definition
            x_color = self._get_math_channel_color(self.x_channel)
        else:
            # Physical channel - get color from linepens
            if self.x_channel < len(self.plot_manager.linepens):
                x_color = self.plot_manager.linepens[self.x_channel].color()
            else:
                x_color = QColor('grey')

        bottom_axis = self.plot.getAxis('bottom')
        bottom_axis.setPen(x_color)
        bottom_axis.setTextPen(x_color)

    def _get_math_channel_color(self, math_name):
        """Get the color for a math channel by name."""
        if self.parent_window and hasattr(self.parent_window, 'math_window') and self.parent_window.math_window:
            for math_def in self.parent_window.math_window.math_channels:
                if math_def['name'] == math_name:
                    return QColor(math_def['color'])
        return QColor('grey')  # Default color if not found

    def update_xy_plot(self, xydata, math_results=None):
        """Update the XY plot with new data.

        Args:
            xydata: The full xydata array from main_window
            math_results: Optional dictionary mapping math channel names to (x_data, y_data) tuples
        """
        # Store math results for later use
        if math_results is not None:
            self.math_results = math_results

        # Get data for X channel
        if isinstance(self.x_channel, str):
            # Math channel
            if self.x_channel in self.math_results:
                x_data = self.math_results[self.x_channel][1]  # Use Y data (voltage)
            else:
                return  # Math channel not available yet
        else:
            # Physical channel
            if self.x_channel < len(xydata):
                x_data = xydata[self.x_channel][1]  # Use Y data (voltage) from X channel
            else:
                return

        # Get data for Y channel
        if isinstance(self.y_channel, str):
            # Math channel
            if self.y_channel in self.math_results:
                y_data = self.math_results[self.y_channel][1]  # Use Y data (voltage)
            else:
                return  # Math channel not available yet
        else:
            # Physical channel
            if self.y_channel < len(xydata):
                y_data = xydata[self.y_channel][1]  # Use Y data (voltage) from Y channel
            else:
                return

        # Make sure arrays are the same length
        min_len = min(len(x_data), len(y_data))
        x_data = x_data[:min_len]
        y_data = y_data[:min_len]

        self.xy_line.setData(x=x_data, y=y_data, skipFiniteCheck=True)

    def showEvent(self, event):
        """Called when window is shown - set initial range."""
        super().showEvent(event)
        self.plot.setRange(xRange=(-5, 5), yRange=(-5, 5), padding=0.01)

    def refresh_channel_list(self):
        """Refresh the channel combo boxes to reflect current channels and math channels."""
        # Store current selections
        current_y = self.y_channel
        current_x = self.x_channel

        # Repopulate the combos
        self.populate_channel_combos()

        # Try to restore previous selections if they still exist
        # For Y channel
        for i in range(self.y_channel_combo.count()):
            if self.y_channel_combo.itemData(i) == current_y:
                self.y_channel_combo.setCurrentIndex(i)
                self.y_channel = current_y
                break

        # For X channel
        for i in range(self.x_channel_combo.count()):
            if self.x_channel_combo.itemData(i) == current_x:
                self.x_channel_combo.setCurrentIndex(i)
                self.x_channel = current_x
                break

    def closeEvent(self, event):
        """Called when window is closed - emit signal and update state."""
        self.window_closed.emit()
        super().closeEvent(event)
