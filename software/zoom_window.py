# zoom_window.py

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets
from PyQt5.QtGui import QColor, QPen
from PyQt5.QtCore import pyqtSignal
from plot_manager import add_secondary_axis


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

        for axis in ['bottom', 'left', 'right']:
            axis_item = self.plot.getAxis(axis)
            axis_item.setStyle(tickFont=font)
            if axis != 'right':  # Don't set grey for right axis - will be colored per channel
                axis_item.setPen('grey')
                axis_item.setTextPen('grey')

        # Set axis labels
        self.plot.setLabel('bottom', 'Time (ns)')
        self.plot.setLabel('left', 'Voltage (V/div)')

        # Disable mouse interactions for pan/zoom
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMouseEnabled(x=False, y=False)
        # Disable all mouse interactions on the ViewBox
        view_box = self.plot.getViewBox()
        view_box.setMouseEnabled(x=False, y=False)
        # Disable right-click menu (already done above but making sure)
        view_box.setMenuEnabled(False)

        # Add secondary Y-axis for voltage display
        self.right_axis = None
        if state and state.num_board > 0:
            self.right_axis = add_secondary_axis(
                plot_item=self.plot,
                conversion_func=lambda val: val * self.state.VperD[self.state.activexychannel],
                text='Voltage', units='V', color="w"
            )
            self.right_axis.setWidth(w=40)
            self.right_axis.setVisible(True)
            # Update the axis to match the active channel
            self.update_right_axis()

        # Create view-only trigger lines (non-movable)
        self.trigger_lines = {}
        dashedpen = pg.mkPen(color="w", width=1.0, style=QtCore.Qt.DashLine)
        self.trigger_lines['vline'] = pg.InfiniteLine(pos=0.0, angle=90, movable=False, pen=dashedpen)
        self.trigger_lines['hline'] = pg.InfiniteLine(pos=0.0, angle=0, movable=False, pen=dashedpen)
        self.plot.addItem(self.trigger_lines['vline'])
        self.plot.addItem(self.trigger_lines['hline'])
        # Initially hidden - will be shown when main plot shows them
        self.trigger_lines['vline'].setVisible(False)
        self.trigger_lines['hline'].setVisible(False)

        # Create view-only cursor lines (non-movable)
        self.cursor_lines = {}
        cursor_pen = pg.mkPen(color=QColor('gray'), width=2.0, style=QtCore.Qt.DotLine)
        self.cursor_lines['t1'] = pg.InfiniteLine(pos=0.0, angle=90, movable=False, pen=cursor_pen)
        self.cursor_lines['t2'] = pg.InfiniteLine(pos=0.0, angle=90, movable=False, pen=cursor_pen)
        self.cursor_lines['v1'] = pg.InfiniteLine(pos=0.0, angle=0, movable=False, pen=cursor_pen)
        self.cursor_lines['v2'] = pg.InfiniteLine(pos=0.0, angle=0, movable=False, pen=cursor_pen)
        for cursor in self.cursor_lines.values():
            self.plot.addItem(cursor)
            cursor.setVisible(False)  # Initially hidden

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

        # Update the right axis to reflect the active channel
        self.update_right_axis()

    def update_trigger_and_cursor_lines(self, main_plot_manager):
        """Update the zoom window's trigger and cursor lines to match the main plot.

        Args:
            main_plot_manager: The main window's plot manager to get line positions from
        """
        if not main_plot_manager:
            return

        # Update trigger lines (vline, hline)
        if hasattr(main_plot_manager, 'otherlines'):
            if 'vline' in main_plot_manager.otherlines:
                vline = main_plot_manager.otherlines['vline']
                self.trigger_lines['vline'].setPos(vline.value())
                self.trigger_lines['vline'].setVisible(vline.isVisible())

            if 'hline' in main_plot_manager.otherlines:
                hline = main_plot_manager.otherlines['hline']
                self.trigger_lines['hline'].setPos(hline.value())
                self.trigger_lines['hline'].setVisible(hline.isVisible())

        # Update cursor lines (t1, t2, v1, v2)
        if hasattr(main_plot_manager, 'cursor_manager') and main_plot_manager.cursor_manager:
            cursor_mgr = main_plot_manager.cursor_manager
            if hasattr(cursor_mgr, 'cursor_lines'):
                for cursor_name in ['t1', 't2', 'v1', 'v2']:
                    if cursor_name in cursor_mgr.cursor_lines and cursor_name in self.cursor_lines:
                        main_cursor = cursor_mgr.cursor_lines[cursor_name]
                        self.cursor_lines[cursor_name].setPos(main_cursor.value())
                        self.cursor_lines[cursor_name].setVisible(main_cursor.isVisible())

    def update_right_axis(self):
        """Update the secondary Y-axis to show voltage for the active channel."""
        if not self.right_axis or not self.state:
            return

        # Get the active channel color and properties
        active_channel = self.state.activexychannel
        if active_channel < len(self.plot_manager.linepens):
            active_pen = QPen(self.plot_manager.linepens[active_channel])
            active_pen.setWidth(1)
            self.right_axis.setPen(active_pen)
            self.right_axis.setTextPen(color=active_pen.color())

        # Update the axis label
        board = self.state.activeboard
        channel = self.state.selectedchannel
        self.right_axis.setLabel(text=f"Voltage for Board {board} Channel {channel}", units='V')

        # Update the conversion function to use the active channel's VperD
        self.right_axis.conversion_func = lambda val: val * self.state.VperD[active_channel]

        # Update tick spacing based on the channel's voltage per division
        tick_span = round(2 * 5 * self.state.VperD[active_channel], 1)
        self.right_axis.setTickSpacing(tick_span, 0.1 * tick_span)

        # Apply the update
        if hasattr(self.right_axis, 'update_function'):
            self.right_axis.update_function()

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
