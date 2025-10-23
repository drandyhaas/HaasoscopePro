# zoom_window.py

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets
from PyQt5.QtGui import QColor
from PyQt5.QtCore import pyqtSignal


class ZoomWindow(QtWidgets.QWidget):
    """Popup window showing zoomed view of the main plot."""

    # Signal emitted when the window is closed
    window_closed = pyqtSignal()

    def __init__(self, parent=None, state=None, plot_manager=None):
        super().__init__(parent)
        self.setWindowTitle("Zoom Window")
        self.setWindowFlags(QtCore.Qt.Window)
        self.state = state
        self.plot_manager = plot_manager
        self.parent_window = parent

        # Store zoom region bounds (will be set by ROI)
        self.zoom_x_range = None  # (min, max) in ns
        self.zoom_y_range = None  # (min, max) in V/div

        # Setup main layout
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

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

        # Set axis labels
        self.plot.setLabel('bottom', 'Time (ns)')
        self.plot.setLabel('left', 'Voltage (V/div)')

        # Enable mouse interactions for pan/zoom
        self.plot.setMouseEnabled(x=True, y=True)

        # Create plot lines for each channel (will be created dynamically)
        self.channel_lines = {}  # {channel_index: plot_line}
        self.math_channel_lines = {}  # {math_name: plot_line}

        layout.addWidget(self.plot_widget)
        self.setLayout(layout)

        # Set default size
        self.resize(800, 600)

    def position_relative_to_main(self, main_window):
        """Position the window to the right of the main window with tops aligned."""
        main_geometry = main_window.geometry()

        # Calculate position: 10 pixels to the right of main window's right edge
        x = main_geometry.x() + main_geometry.width() + 10

        # Align tops
        y = main_geometry.y()

        self.move(x, y)

    def set_zoom_region(self, x_range, y_range):
        """Set the zoom region to display.

        Args:
            x_range: (min, max) tuple for x-axis (time in ns)
            y_range: (min, max) tuple for y-axis (voltage in V/div)
        """
        self.zoom_x_range = x_range
        self.zoom_y_range = y_range

        # Update the plot view range
        if x_range and y_range:
            self.plot.setRange(xRange=x_range, yRange=y_range, padding=0)

    def update_zoom_plot(self, xydata, math_results=None):
        """Update the zoom plot with new data.

        Args:
            xydata: The full xydata array from main_window
            math_results: Optional dictionary mapping math channel names to (x_data, y_data) tuples
        """
        if not self.zoom_x_range or not self.zoom_y_range:
            return

        # Update physical channels
        total_channels = self.state.num_board * self.state.num_chan_per_board
        for ch_idx in range(total_channels):
            # Skip disabled channels
            if not self.state.channel_enabled[ch_idx]:
                continue

            board_idx = ch_idx // self.state.num_chan_per_board
            local_ch = ch_idx % self.state.num_chan_per_board

            # Skip ch 1 if board is in single-channel mode
            if not self.state.dotwochannel[board_idx] and local_ch != 0:
                continue

            # Get data
            if ch_idx >= len(xydata):
                continue

            x_data = xydata[ch_idx][0]
            y_data = xydata[ch_idx][1]

            if x_data is None or y_data is None or len(x_data) == 0:
                continue

            # Create line if it doesn't exist
            if ch_idx not in self.channel_lines:
                # Get pen color from plot_manager
                if ch_idx < len(self.plot_manager.linepens):
                    pen = self.plot_manager.linepens[ch_idx]
                else:
                    pen = pg.mkPen(color='white', width=1)

                self.channel_lines[ch_idx] = self.plot.plot(
                    pen=pen,
                    skipFiniteCheck=True,
                    connect="finite"
                )

            # Update line data
            self.channel_lines[ch_idx].setData(x=x_data, y=y_data, skipFiniteCheck=True)

        # Update math channels
        if math_results:
            for math_name, (x_data, y_data) in math_results.items():
                if x_data is None or y_data is None or len(x_data) == 0:
                    continue

                # Create line if it doesn't exist
                if math_name not in self.math_channel_lines:
                    # Get color from math channel definition
                    color = self._get_math_channel_color(math_name)
                    pen = pg.mkPen(color=color, width=2)

                    self.math_channel_lines[math_name] = self.plot.plot(
                        pen=pen,
                        skipFiniteCheck=True,
                        connect="finite"
                    )

                # Update line data
                self.math_channel_lines[math_name].setData(x=x_data, y=y_data, skipFiniteCheck=True)

        # Remove math channel lines that no longer exist
        existing_math_names = set(math_results.keys()) if math_results else set()
        for math_name in list(self.math_channel_lines.keys()):
            if math_name not in existing_math_names:
                self.plot.removeItem(self.math_channel_lines[math_name])
                del self.math_channel_lines[math_name]

    def _get_math_channel_color(self, math_name):
        """Get the color for a math channel by name."""
        if self.parent_window and hasattr(self.parent_window, 'math_window') and self.parent_window.math_window:
            for math_def in self.parent_window.math_window.math_channels:
                if math_def['name'] == math_name:
                    return QColor(math_def['color'])
        return QColor('white')  # Default color if not found

    def clear_channel_lines(self):
        """Clear all channel lines when channel configuration changes."""
        # Remove physical channel lines
        for line in self.channel_lines.values():
            self.plot.removeItem(line)
        self.channel_lines.clear()

        # Remove math channel lines
        for line in self.math_channel_lines.values():
            self.plot.removeItem(line)
        self.math_channel_lines.clear()

    def closeEvent(self, event):
        """Called when window is closed - emit signal and update state."""
        self.window_closed.emit()
        super().closeEvent(event)
