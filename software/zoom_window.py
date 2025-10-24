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
        # Hide the autoscale button (accessed through PlotItem)
        self.plot.hideButtons()

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
        self.reference_lines = {}  # {channel_index: plot_line} for physical channel references
        self.math_reference_lines = {}  # {math_name: plot_line} for math channel references

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

    def update_zoom_plot(self, stabilized_data, math_results=None):
        """Update the zoom plot with new data.

        Args:
            stabilized_data: Dictionary mapping channel index to (x_data, y_data) tuples of post-processed data
            math_results: Optional dictionary mapping math channel names to (x_data, y_data) tuples
        """
        if not self.zoom_x_range or not self.zoom_y_range:
            return

        # Update physical channels
        total_channels = self.state.num_board * self.state.num_chan_per_board

        for ch_idx in range(total_channels):
            board_idx = ch_idx // self.state.num_chan_per_board
            local_ch = ch_idx % self.state.num_chan_per_board

            # Determine if this channel should be shown
            should_show = (
                self.state.channel_enabled[ch_idx] and
                (self.state.dotwochannel[board_idx] or local_ch == 0)
            )

            if not should_show:
                # Hide this channel's line if it exists
                if ch_idx in self.channel_lines:
                    self.channel_lines[ch_idx].setVisible(False)
                continue

            # Get post-processed data from stabilized_data (a list indexed by channel)
            if ch_idx >= len(stabilized_data) or stabilized_data[ch_idx] is None:
                continue

            x_data, y_data = stabilized_data[ch_idx]

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

            # Show and update line data
            self.channel_lines[ch_idx].setVisible(True)
            self.channel_lines[ch_idx].setData(x=x_data, y=y_data, skipFiniteCheck=True)

        # Update math channels
        if math_results:
            for math_name, (x_data, y_data) in math_results.items():
                if x_data is None or y_data is None or len(x_data) == 0:
                    continue

                # Check if this math channel should be displayed
                math_def = self._get_math_channel_definition(math_name)
                is_displayed = math_def.get('displayed', True) if math_def else True

                # Create line if it doesn't exist
                if math_name not in self.math_channel_lines:
                    # Get color and width from math channel definition
                    color = self._get_math_channel_color(math_name)
                    width = math_def.get('width', 2) if math_def else 2
                    # Use dashed pen for math channels, like in main window
                    pen = pg.mkPen(color=color, width=width, style=QtCore.Qt.DashLine)

                    self.math_channel_lines[math_name] = self.plot.plot(
                        pen=pen,
                        skipFiniteCheck=True,
                        connect="finite"
                    )
                else:
                    # Update pen to match current color and width
                    color = self._get_math_channel_color(math_name)
                    width = math_def.get('width', 2) if math_def else 2
                    pen = pg.mkPen(color=color, width=width, style=QtCore.Qt.DashLine)
                    self.math_channel_lines[math_name].setPen(pen)

                # Update line data and visibility
                self.math_channel_lines[math_name].setData(x=x_data, y=y_data, skipFiniteCheck=True)
                self.math_channel_lines[math_name].setVisible(is_displayed)

        # Remove math channel lines that no longer exist
        existing_math_names = set(math_results.keys()) if math_results else set()
        for math_name in list(self.math_channel_lines.keys()):
            if math_name not in existing_math_names:
                self.plot.removeItem(self.math_channel_lines[math_name])
                del self.math_channel_lines[math_name]

        # Update the right axis to reflect the active channel
        self.update_right_axis()

    def update_reference_waveforms(self, reference_data, reference_visible, math_reference_data, math_reference_visible):
        """Update the reference waveforms in the zoom window.

        Args:
            reference_data: Dictionary {channel_index: {'x_ns': array, 'y': array}}
            reference_visible: Dictionary {channel_index: bool}
            math_reference_data: Dictionary {math_name: {'x_ns': array, 'y': array}}
            math_reference_visible: Dictionary {math_name: bool}
        """
        # Update physical channel references
        for ch_idx, ref_data in reference_data.items():
            is_visible = reference_visible.get(ch_idx, False)

            if ch_idx not in self.reference_lines:
                # Create reference line with semi-transparent pen matching channel color and width
                if ch_idx < len(self.plot_manager.linepens):
                    color = QColor(self.plot_manager.linepens[ch_idx].color())
                    color.setAlphaF(0.5)
                    width = self.plot_manager.linepens[ch_idx].width()
                    pen = pg.mkPen(color=color, width=width)
                else:
                    color = QColor('white')
                    color.setAlphaF(0.5)
                    pen = pg.mkPen(color=color, width=1)

                self.reference_lines[ch_idx] = self.plot.plot(
                    pen=pen,
                    skipFiniteCheck=True,
                    connect="finite"
                )
            else:
                # Update the pen to match current channel color and width
                if ch_idx < len(self.plot_manager.linepens):
                    color = QColor(self.plot_manager.linepens[ch_idx].color())
                    color.setAlphaF(0.5)
                    width = self.plot_manager.linepens[ch_idx].width()
                    pen = pg.mkPen(color=color, width=width)
                    self.reference_lines[ch_idx].setPen(pen)

            # Update data - need to convert from ns to current time units
            x_data_ns = ref_data['x_ns']
            y_data = ref_data['y']
            x_data = x_data_ns / self.state.nsunits  # Convert to current time units

            # Resample reference to match the stored doresamp setting for display
            # Use stored doresamp if available (for backward compatibility)
            doresamp_to_use = ref_data.get('doresamp', self.state.doresamp[ch_idx])
            if doresamp_to_use > 1:
                from scipy.signal import resample
                y_resampled, x_resampled = resample(y_data, len(x_data) * doresamp_to_use, t=x_data)
                self.reference_lines[ch_idx].setData(x=x_resampled, y=y_resampled, skipFiniteCheck=True)
            else:
                self.reference_lines[ch_idx].setData(x=x_data, y=y_data, skipFiniteCheck=True)
            self.reference_lines[ch_idx].setVisible(is_visible)

        # Remove reference lines that no longer exist
        for ch_idx in list(self.reference_lines.keys()):
            if ch_idx not in reference_data:
                self.plot.removeItem(self.reference_lines[ch_idx])
                del self.reference_lines[ch_idx]

        # Update math channel references
        for math_name, ref_data in math_reference_data.items():
            is_visible = math_reference_visible.get(math_name, False)

            # Get math channel definition once for all uses
            math_def = self._get_math_channel_definition(math_name)
            color = self._get_math_channel_color(math_name)
            ref_color = QColor(color)
            ref_color.setAlphaF(0.5)
            width = math_def.get('width', 2) if math_def else 2

            if math_name not in self.math_reference_lines:
                # Create reference line with semi-transparent pen matching math channel color and width
                pen = pg.mkPen(color=ref_color, width=width, style=QtCore.Qt.DashLine)

                self.math_reference_lines[math_name] = self.plot.plot(
                    pen=pen,
                    skipFiniteCheck=True,
                    connect="finite"
                )
            else:
                # Update the pen to match current math channel color and width
                pen = pg.mkPen(color=ref_color, width=width, style=QtCore.Qt.DashLine)
                self.math_reference_lines[math_name].setPen(pen)

            # Update data - need to convert from ns to current time units
            x_data_ns = ref_data['x_ns']
            y_data = ref_data['y']
            x_data = x_data_ns / self.state.nsunits  # Convert to current time units

            # Resample reference to match the stored doresamp setting for display
            # Use stored doresamp if available (for backward compatibility and for references)
            doresamp_to_use = ref_data.get('doresamp', 1)
            if doresamp_to_use > 1:
                from scipy.signal import resample
                y_resampled, x_resampled = resample(y_data, len(x_data) * doresamp_to_use, t=x_data)
                self.math_reference_lines[math_name].setData(x=x_resampled, y=y_resampled, skipFiniteCheck=True)
            else:
                self.math_reference_lines[math_name].setData(x=x_data, y=y_data, skipFiniteCheck=True)
            self.math_reference_lines[math_name].setVisible(is_visible)

        # Remove math reference lines that no longer exist
        for math_name in list(self.math_reference_lines.keys()):
            if math_name not in math_reference_data:
                self.plot.removeItem(self.math_reference_lines[math_name])
                del self.math_reference_lines[math_name]

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

    def _get_math_channel_definition(self, math_name):
        """Get the full definition for a math channel by name."""
        if self.parent_window and hasattr(self.parent_window, 'math_window') and self.parent_window.math_window:
            for math_def in self.parent_window.math_window.math_channels:
                if math_def['name'] == math_name:
                    return math_def
        return None  # Not found

    def set_markers(self, is_checked):
        """Set marker visibility on all zoom window plot lines.

        Args:
            is_checked: True to show markers, False to hide them
        """
        symbol = "o" if is_checked else None
        size = 3 if is_checked else 0

        # Set markers on physical channel lines
        for ch_idx, line in self.channel_lines.items():
            line.setSymbol(symbol)
            line.setSymbolSize(size)
            if is_checked and ch_idx < len(self.plot_manager.linepens):
                line.setSymbolPen(self.plot_manager.linepens[ch_idx].color())
                line.setSymbolBrush(self.plot_manager.linepens[ch_idx].color())

        # Set markers on math channel lines
        for math_name, line in self.math_channel_lines.items():
            line.setSymbol(symbol)
            line.setSymbolSize(size)

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

        # Remove reference lines
        for line in self.reference_lines.values():
            self.plot.removeItem(line)
        self.reference_lines.clear()

        # Remove math reference lines
        for line in self.math_reference_lines.values():
            self.plot.removeItem(line)
        self.math_reference_lines.clear()

    def closeEvent(self, event):
        """Called when window is closed - emit signal and update state."""
        self.window_closed.emit()
        super().closeEvent(event)
