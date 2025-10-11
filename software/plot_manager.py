# plot_manager.py

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore
from PyQt5.QtGui import QColor, QPen
import numpy as np
import time
from collections import deque
import colorsys
from scipy.signal import resample
from scipy.interpolate import interp1d
from data_processor import find_crossing_distance
from cursor_manager import CursorManager
import math


# #############################################################################
# Plotting Helper Functions (Moved from utils.py)
# #############################################################################

def rainbow_colormap(n, start=0.0, end=0.66):
    """Generate rainbow colors using HSV color space.

    Args:
        n: Number of colors to generate
        start: Starting hue (0.0 = red, default)
        end: Ending hue (0.66 = blue, default 0.66 to match matplotlib rainbow)

    Returns:
        Array of RGBA colors with shape (n, 4)
    """
    hues = np.linspace(start, end, n)
    colors = np.zeros((n, 4))
    for i, hue in enumerate(hues):
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        colors[i] = [r, g, b, 1.0]  # RGBA
    return colors

def add_secondary_axis(plot_item, conversion_func, **axis_args):
    """Adds a secondary y-axis that is dynamically linked by a conversion function."""
    proxy_view = pg.ViewBox()
    proxy_view.setMouseEnabled(False,False)
    axis = plot_item.getAxis('right')
    plot_item.scene().addItem(proxy_view)
    axis.linkToView(proxy_view)
    proxy_view.setXLink(plot_item)
    axis.setLabel(**axis_args)

    def update_proxy_view():
        proxy_view.setGeometry(plot_item.getViewBox().sceneBoundingRect())
        main_yrange = plot_item.getViewBox().viewRange()[1]
        proxy_range = [conversion_func(y) for y in main_yrange]
        proxy_view.setYRange(*proxy_range, padding=0)

    plot_item.getViewBox().sigResized.connect(update_proxy_view)
    plot_item.getViewBox().sigYRangeChanged.connect(update_proxy_view)

    axis.update_function = update_proxy_view
    return axis


# #############################################################################
# PlotManager Class
# #############################################################################

class PlotManager(pg.QtCore.QObject):
    """Manages all plotting and UI visual elements using pyqtgraph."""
    # Signals to notify MainWindow of user interaction with the plot
    vline_dragged_signal = pg.QtCore.Signal(float)
    hline_dragged_signal = pg.QtCore.Signal(float)
    curve_clicked_signal = pg.QtCore.Signal(int)
    math_curve_clicked_signal = pg.QtCore.Signal(str)  # Emits math channel name

    def __init__(self, ui, state):
        super().__init__()
        self.ui = ui
        self.state = state
        self.plot = self.ui.plot
        self.lines = []
        self.reference_lines = []
        self.math_channel_lines = {}  # Dictionary: {math_name: plot_line}
        self.xy_line = None
        self.linepens = []
        self.otherlines = {}  # For trigger lines, fit lines etc.
        self.average_line = None
        self.right_axis = None
        self.nlines = state.num_board * state.num_chan_per_board
        self.current_vline_pos = 0.0

        # Stabilized data for math channel calculations (after trigger stabilizers)
        self.stabilized_data = [None] * self.nlines

        # Cursor manager (will be initialized after linepens are created)
        self.cursor_manager = None

        # Persistence attributes
        self.max_persist_lines = 16
        self.persist_time = 0
        self.persist_lines = deque(maxlen=self.max_persist_lines)
        self.persist_timer = QtCore.QTimer()
        self.persist_timer.timeout.connect(self.update_persist_effect)

        # Peak detect attributes
        self.peak_detect_enabled = False
        self.peak_max_line = None
        self.peak_min_line = None
        self.peak_max_data = {}  # {channel_index: (x_data, y_data)}
        self.peak_min_data = {}  # {channel_index: (x_data, y_data)}
        self.peak_skip_events = 0  # Skip N events after clearing peak data

    def _create_click_handler(self, channel_index):
        """Creates a unique click handler function that remembers the channel index."""
        def handler(curve_item):
            self.curve_clicked_signal.emit(channel_index)
        return handler

    def _create_math_click_handler(self, math_channel_name):
        """Creates a unique click handler function that remembers the math channel name."""
        def handler(curve_item):
            self.math_curve_clicked_signal.emit(math_channel_name)
        return handler

    def setup_plots(self):
        """Initializes the plot area, lines, pens, and axes."""
        self.plot.setBackground(QColor('black'))
        self.plot.setLabel('bottom', "Time (ns)")
        self.plot.setLabel('left', "Voltage (divisions)")
        self.plot.getAxis("left").setTickSpacing(1, .1)
        self.plot.setMenuEnabled(False)  # Disables the right-click context menu
        self.set_grid(self.ui.actionGrid.isChecked())

        # Create lines for each channel
        colors = rainbow_colormap(self.nlines, start=0.0, end=0.66)
        for i in range(self.nlines):
            c = QColor.fromRgbF(*colors[i])
            pen = pg.mkPen(color=c)
            line = self.plot.plot(pen=pen, name=f"Channel {i}", skipFiniteCheck=True, connect="finite")
            line.curve.setClickable(True)
            line.curve.sigClicked.connect(self._create_click_handler(i))
            self.lines.append(line)
            self.linepens.append(pen)

            # Add a corresponding reference line for each channel
            ref_c = QColor(c)
            ref_c.setAlphaF(0.5)
            ref_pen = pg.mkPen(color=ref_c, width=pen.width())
            ref_line = self.plot.plot(pen=ref_pen, name=f"Ref {i}", skipFiniteCheck=True, connect="finite")
            ref_line.setVisible(False)
            self.reference_lines.append(ref_line)

        # Trigger and fit lines
        dashedpen = pg.mkPen(color="w", width=1.0, style=QtCore.Qt.DashLine)
        hoverpen = pg.mkPen(color="w", width=2.0, style=QtCore.Qt.DashLine)
        self.otherlines['vline'] = pg.InfiniteLine(pos=0.0, angle=90, movable=True, pen=dashedpen, hoverPen=hoverpen)
        self.otherlines['hline'] = pg.InfiniteLine(pos=0.0, angle=0, movable=True, pen=dashedpen, hoverPen=hoverpen)
        self.plot.addItem(self.otherlines['vline'])
        self.plot.addItem(self.otherlines['hline'])
        self.otherlines['vline'].sigDragged.connect(self.on_vline_dragged)
        self.otherlines['vline'].sigPositionChangeFinished.connect(self.on_vline_drag_finished)
        self.otherlines['hline'].sigPositionChanged.connect(self.on_hline_dragged)

        # Risetime fit lines (initially invisible)
        fit_pen = pg.mkPen(color="w", width=1.0, style=QtCore.Qt.DotLine)
        for i in range(3):
            line = self.plot.plot([0], [0], pen=fit_pen, name=f"fitline_{i}")
            line.setVisible(False)
            self.otherlines[f'fit_{i}'] = line

        # Persistence average line
        self.average_line = self.plot.plot(pen=pg.mkPen(color='w', width=1), name="persist_avg")
        self.average_line.setVisible(self.ui.actionPersist_average.isChecked())

        # XY plot line (initially hidden)
        self.xy_line = self.plot.plot(pen=pg.mkPen(color="w"), name="XY_Plot", skipFiniteCheck=True, connect="finite")
        self.xy_line.setVisible(False)

        # Peak detect lines (initially hidden, will use active channel color when enabled)
        peak_pen = pg.mkPen(color='w', width=1, style=QtCore.Qt.DotLine)
        self.peak_max_line = self.plot.plot(pen=peak_pen, name="Peak_Max", skipFiniteCheck=True, connect="finite")
        self.peak_max_line.setVisible(False)
        self.peak_min_line = self.plot.plot(pen=peak_pen, name="Peak_Min", skipFiniteCheck=True, connect="finite")
        self.peak_min_line.setVisible(False)

        # Cursor manager (initialized after linepens and lines are created)
        self.cursor_manager = CursorManager(self.plot, self.state, self.linepens, self.ui, self.otherlines, self.lines)
        self.cursor_manager.setup_cursors()

        # Secondary Y-Axis
        if self.state.num_board > 0:
            self.right_axis = add_secondary_axis(
                plot_item=self.plot,
                conversion_func=lambda val: val * self.state.VperD[self.state.activexychannel],
                text='Voltage', units='V', color="w"
            )
            self.right_axis.setWidth(w=40)
            self.right_axis.setVisible(True)
        self.time_changed()

    def update_plots(self, xy_data, xydatainterleaved):
        """Updates all visible waveform plots with new data."""
        if not self.state.dodrawing:
            return
        s = self.state

        # Create a copy to store stabilized data for math channels
        self.stabilized_data = [None] * self.nlines

        for li in range(self.nlines):
            board_idx = li // s.num_chan_per_board
            xdatanew, ydatanew = None, None

            # --- LOGIC FOR NON-INTERLEAVED BOARDS ---
            if not s.dointerleaved[board_idx]:
                x_data_full = xy_data[li][0]
                y_data_full = xy_data[li][1]

                # Check the mode for the board this line belongs to
                if s.dotwochannel[board_idx]:
                    # For two-channel boards, we have half the samples.
                    # We need to plot these samples across the full time axis.
                    num_valid_samples = xy_data.shape[2] // 2
                    y_to_plot = y_data_full[:num_valid_samples]

                    # Create a new, correctly spaced time axis for this smaller dataset.
                    # It starts at the same time and ends at the same time.
                    x_to_plot = np.linspace(x_data_full[0], x_data_full[-1], num_valid_samples)
                    xdatanew, ydatanew = x_to_plot, y_to_plot
                else:
                    # For single-channel boards, use the data as is.
                    xdatanew, ydatanew = x_data_full, y_data_full

            # --- LOGIC FOR INTERLEAVED BOARDS ---
            else:
                if li % 4 == 0:
                    primary_data = xy_data[li][1]
                    secondary_data = xy_data[li + s.num_chan_per_board][1]
                    xydatainterleaved[board_idx][1][0::2] = primary_data
                    xydatainterleaved[board_idx][1][1::2] = secondary_data

                    x_interleaved = xydatainterleaved[board_idx][0]
                    y_interleaved = xydatainterleaved[board_idx][1]

                    # Interpolate to create a smooth, high-density trace
                    xdatanew = np.linspace(x_interleaved.min(), x_interleaved.max(), len(x_interleaved))
                    f_int = interp1d(x_interleaved, y_interleaved, kind='linear', bounds_error=False, fill_value=0.0)
                    ydatanew = f_int(xdatanew)

            if xdatanew is None: continue  # Skip if no data for this line (e.g., secondary interleaved line)

            # --- Resampling (if enabled) ---
            if s.doresamp:
                ydatanew, xdatanew = resample(ydatanew, len(xdatanew) * s.doresamp, t=xdatanew)

            # --- Per-Line Stabilizer (Correct Location) ---
            if s.extra_trig_stabilizer_enabled:
                is_oversample_secondary = s.dooversample[board_idx] and board_idx%2==1
                if not is_oversample_secondary: #and not s.doexttrig[board] ?
                    vline_time = self.otherlines['vline'].value()
                    hline_pos = (s.triggerlevel - 127) * s.yscale * 256
                    # Include triggerdelta in the threshold (per-board setting)
                    hline_threshold = hline_pos + s.triggerdelta[board_idx] * s.yscale*256

                    fitwidth = (s.max_x - s.min_x)
                    xc = xdatanew[(xdatanew > vline_time - fitwidth) & (xdatanew < vline_time + fitwidth)]

                    if xc.size > 2:
                        numsamp = s.distcorrsamp
                        if s.doresamp: numsamp *= s.doresamp
                        fitwidth *= numsamp / xc.size

                        xc = xdatanew[(xdatanew > vline_time - fitwidth) & (xdatanew < vline_time + fitwidth)]
                        yc = ydatanew[(xdatanew > vline_time - fitwidth) & (xdatanew < vline_time + fitwidth)]

                        # For falling edges, invert both the signal and the threshold
                        threshold_to_use = hline_threshold
                        if s.fallingedge[li // 2]:
                            yc = -yc
                            threshold_to_use = -hline_threshold

                        if xc.size > 1:
                            distcorrtemp = find_crossing_distance(yc, threshold_to_use, vline_time, xc[0], xc[1] - xc[0])
                            if distcorrtemp is not None and abs(
                                    distcorrtemp) < s.distcorrtol * s.downsamplefactor / s.nsunits:
                                xdatanew -= distcorrtemp

            # --- Final plotting and persistence ---
            # Optimization: Use skipFiniteCheck for faster setData
            self.lines[li].setData(xdatanew, ydatanew, skipFiniteCheck=True)

            # Store stabilized data for math channel calculations
            self.stabilized_data[li] = (xdatanew, ydatanew)

            if li == s.activexychannel and self.persist_time > 0 and self.ui.chanonCheck.isChecked():
                self._add_to_persistence(xdatanew, ydatanew, li)

            # --- Peak detect update ---
            if self.peak_detect_enabled and li == s.activexychannel:
                self._update_peak_data(li, xdatanew, ydatanew)

        self.update_persist_average()

        # Update peak detect lines if enabled
        if self.peak_detect_enabled:
            self._update_peak_lines()

    def toggle_xy_view(self, show_xy, board_num=0):
        """Switches between the time-domain view and the XY plot view."""
        self.state.xy_mode = show_xy

        # Explicitly hide or show all time-domain related plots
        is_time_domain_visible = not show_xy
        for line in self.lines:
            line.setVisible(is_time_domain_visible)
        for line in self.reference_lines:
            # Only show reference lines if they have data and we are in time domain
            line.setVisible(is_time_domain_visible and line.xData is not None)
        for key, line in self.otherlines.items():
            line.setVisible(is_time_domain_visible)
        # Hide/show math channel lines (only if they're marked as displayed)
        # We need to check with the math window to get the displayed state
        for math_name, line in self.math_channel_lines.items():
            # Default to showing in time domain if we can't check displayed state
            line.setVisible(is_time_domain_visible)
        # Also hide/show the right axis
        if self.right_axis:
            self.right_axis.setVisible(is_time_domain_visible)
        self.average_line.setVisible(is_time_domain_visible and self.ui.actionPersist_average.isChecked())

        if show_xy:
            self.plot.setLabel('bottom', f"Board {board_num} Ch 1 (V/div)")
            self.plot.setLabel('left', f"Board {board_num} Ch 0 (V/div)")
            self.plot.setRange(xRange=(-5, 5), yRange=(-5, 5), padding=0.01)
        else:
            self.time_changed() # Restore time-domain view
        
        # Finally, set the visibility of the XY line itself
        self.xy_line.setVisible(show_xy)

    def set_xy_pen(self, pen):
        """Sets the pen for the XY plot line."""
        color = pen.color()
        color.setAlphaF(0.5)
        self.xy_line.setPen(color=color, width=pen.width())

    def update_reference_plot(self, channel_index, x_data, y_data):
        """Sets the data for a channel's reference waveform."""
        if 0 <= channel_index < len(self.reference_lines):
            ref_line = self.reference_lines[channel_index]
            # Optimization: Use skipFiniteCheck for faster setData
            ref_line.setData(x_data, y_data, skipFiniteCheck=True)
            ref_line.setVisible(True)

    def hide_reference_plot(self, channel_index):
        """Hides a specific reference plot."""
        if 0 <= channel_index < len(self.reference_lines):
            self.reference_lines[channel_index].setVisible(False)

    def update_math_channel_lines(self, math_window=None):
        """Updates the set of math channel plot lines based on current math channel definitions.

        Args:
            math_window: The MathChannelsWindow instance (optional, will try to find it if not provided)
        """
        # Get the math window if not provided
        if math_window is None:
            return  # Can't update without math window reference

        current_math_names = {m['name'] for m in math_window.math_channels}

        # Remove lines for math channels that no longer exist
        for math_name in list(self.math_channel_lines.keys()):
            if math_name not in current_math_names:
                line = self.math_channel_lines[math_name]
                self.plot.removeItem(line)
                del self.math_channel_lines[math_name]

        # Create or update lines for math channels
        for math_def in math_window.math_channels:
            math_name = math_def['name']
            color = math_def.get('color', '#00FFFF')  # Default to cyan if no color specified
            displayed = math_def.get('displayed', True)  # Default to displayed if not specified
            width = math_def.get('width', 2)  # Use stored width, default to 2 if not specified

            if math_name not in self.math_channel_lines:
                # Create a new dashed line with the specified color and width
                pen = pg.mkPen(color=color, width=width, style=QtCore.Qt.DashLine)
                line = self.plot.plot(pen=pen, name=math_name, skipFiniteCheck=True, connect="finite")
                # Make the line clickable
                line.curve.setClickable(True)
                line.curve.sigClicked.connect(self._create_math_click_handler(math_name))
                self.math_channel_lines[math_name] = line
                # Set initial visibility
                line.setVisible(displayed and not self.state.xy_mode)
            else:
                # Update the color and width of existing line
                pen = pg.mkPen(color=color, width=width, style=QtCore.Qt.DashLine)
                self.math_channel_lines[math_name].setPen(pen)
                # Update visibility
                self.math_channel_lines[math_name].setVisible(displayed and not self.state.xy_mode)

    def update_math_channel_data(self, math_results):
        """Update the math channel plot lines with calculated data.

        Args:
            math_results: Dictionary mapping math channel names to (x_data, y_data) tuples
        """
        for math_name, (x_data, y_data) in math_results.items():
            if math_name in self.math_channel_lines:
                # Optimization: Use skipFiniteCheck for faster setData
                self.math_channel_lines[math_name].setData(x_data, y_data, skipFiniteCheck=True)

    def update_xy_plot(self, x_data, y_data):
        """Updates the XY plot with new data."""
        if self.state.xy_mode:
            # Optimization: Use skipFiniteCheck for faster setData
            self.xy_line.setData(x=x_data, y=y_data, skipFiniteCheck=True)

    def time_changed(self):
        """Updates the x-axis range and units, and handles zooming."""
        state = self.state
        max_x_ns = 4 * 10 * state.expect_samples * (state.downsamplefactor / state.samplerate)

        if max_x_ns > 5e9:
            state.nsunits, state.units = 1e9, "s"
        elif max_x_ns > 5e6:
            state.nsunits, state.units = 1e6, "ms"
        elif max_x_ns > 5e3:
            state.nsunits, state.units = 1e3, "us"
        else:
            state.nsunits, state.units = 1, "ns"

        # Calculate the full x-axis range first
        full_max_x = max_x_ns / state.nsunits

        # NEW: Apply zoom logic if the zoom factor is greater than 1
        if state.downsamplezoom > 1:
            trigger_pos = self.otherlines['vline'].value()
            trigger_frac = trigger_pos / full_max_x if full_max_x != 0 else 0.5

            view_width = full_max_x / state.downsamplezoom
            state.min_x = trigger_pos - (trigger_frac * view_width)
            state.max_x = trigger_pos + ((1 - trigger_frac) * view_width)
        else:
            state.min_x = 0
            state.max_x = full_max_x

        self.plot.setLabel('bottom', f"Time ({state.units})")
        self.plot.setRange(xRange=(state.min_x, state.max_x), yRange=(state.min_y, state.max_y), padding=0.01)

        self.draw_trigger_lines()
        if self.cursor_manager:
            self.cursor_manager.adjust_cursor_positions()

    def draw_trigger_lines(self):
        """Draws the horizontal and vertical trigger lines on the plot."""
        state = self.state
        vline_pos = 4 * 10 * (state.triggerpos + 1.0) * (state.downsamplefactor / state.nsunits / state.samplerate)
        self.otherlines['vline'].setValue(vline_pos)
        hline_pos = (state.triggerlevel - 127) * state.yscale * 256
        self.otherlines['hline'].setValue(hline_pos)
        self.current_vline_pos = vline_pos

    # Persistence Methods
    def set_persistence(self, value):
        self.persist_time = 50 * pow(2, value) if value > 0 else 0
        if self.persist_time > 0:
            self.persist_timer.start(50)
        else:
            self.persist_timer.stop()
            self.clear_persist()

        # Update the spinbox tooltip to show the actual time value
        time_str = f"{self.persist_time / 1000.0:.1f} s" if self.persist_time > 0 else "Off"
        self.ui.persistTbox.setToolTip(f"Persistence time: {time_str}")

    def _add_to_persistence(self, x, y, line_idx):
        if len(self.persist_lines) >= self.max_persist_lines:
            oldest_item, _, _ = self.persist_lines.popleft()  # Use popleft for deque
            self.plot.removeItem(oldest_item)

        pen = self.linepens[line_idx]
        color = pen.color()
        color.setAlpha(100)
        new_pen = pg.mkPen(color, width=1)
        persist_item = self.plot.plot(x, y, pen=new_pen, skipFiniteCheck=True, connect="finite")
        persist_item.setVisible(self.ui.persistlinesCheck.isChecked())
        self.persist_lines.append((persist_item, time.time(), line_idx))

    def update_persist_effect(self):
        """Updates the alpha/transparency of the persistent lines."""
        if len(self.persist_lines) == 0 and self.persist_time == 0:
            self.persist_timer.stop()
            return

        current_time = time.time()
        # Use a temporary list to avoid issues with modifying the deque while iterating
        items_to_remove = []
        for item, creation_time, li in self.persist_lines:
            age = (current_time - creation_time) * 1000.0
            if age > self.persist_time:
                items_to_remove.append((item, creation_time, li))
            else:
                alpha = int(100 * (1 - (age / self.persist_time)))
                pen = self.linepens[li]
                color = pen.color()
                color.setAlpha(alpha)
                new_pen = pg.mkPen(color, width=1)
                item.setPen(new_pen)

        for item_tuple in items_to_remove:
            self.plot.removeItem(item_tuple[0])
            self.persist_lines.remove(item_tuple)

    def update_persist_average(self):
        """Calculates and plots the average of persistent traces."""
        if len(self.persist_lines) < 2:
            self.average_line.clear()
            return

        first_line_item = self.persist_lines[0][0]
        min_x, max_x = first_line_item.xData.min(), first_line_item.xData.max()

        num_points = self.state.expect_samples * 40 * (2 if self.state.dointerleaved[self.state.activeboard] else 1)
        common_x_axis = np.linspace(min_x, max_x, num_points)

        resampled_y_values = [np.interp(common_x_axis, item.xData, item.yData) for item, _, _ in self.persist_lines]

        if resampled_y_values:
            y_average = np.mean(resampled_y_values, axis=0)
            if self.state.doresamp:
                y_average, common_x_axis = resample(y_average, len(common_x_axis) * self.state.doresamp,
                                                    t=common_x_axis)
            # Optimization: Use skipFiniteCheck for faster setData
            self.average_line.setData(common_x_axis, y_average, skipFiniteCheck=True)

    def clear_persist(self):
        for item, _, _ in list(self.persist_lines):
            self.plot.removeItem(item)
        self.persist_lines.clear()
        self.average_line.clear()

    # Peak Detect Methods
    def set_peak_detect(self, enabled):
        """Enable or disable peak detect mode."""
        self.peak_detect_enabled = enabled
        if enabled:
            # Set peak line colors to match active channel
            active_channel = self.state.activexychannel
            if active_channel < len(self.linepens):
                color = self.linepens[active_channel].color()
                peak_pen = pg.mkPen(color=color, width=1, style=QtCore.Qt.DotLine)
                self.peak_max_line.setPen(peak_pen)
                self.peak_min_line.setPen(peak_pen)
            # Clear any existing peak data for this channel
            self.clear_peak_data()
            # Show the lines
            self.peak_max_line.setVisible(True)
            self.peak_min_line.setVisible(True)
        else:
            # Hide the lines and clear data
            self.peak_max_line.setVisible(False)
            self.peak_min_line.setVisible(False)
            self.clear_peak_data()

    def clear_peak_data(self):
        """Clear all peak detect data."""
        active_channel = self.state.activexychannel
        if active_channel in self.peak_max_data:
            del self.peak_max_data[active_channel]
        if active_channel in self.peak_min_data:
            del self.peak_min_data[active_channel]
        self.peak_max_line.clear()
        self.peak_min_line.clear()
        # Skip the next event to avoid glitches after timebase changes
        self.peak_skip_events = 1

    def _update_peak_data(self, channel_index, x_data, y_data):
        """Update peak max/min data for a channel."""
        # Skip first event after clearing to avoid glitches
        if self.peak_skip_events > 0:
            self.peak_skip_events -= 1
            return

        # Initialize or update max data
        if channel_index not in self.peak_max_data:
            self.peak_max_data[channel_index] = (x_data.copy(), y_data.copy())
        else:
            old_x, old_y = self.peak_max_data[channel_index]
            # If array length changed (due to resamp or other settings), reset peak data
            if len(old_y) != len(y_data):
                self.peak_max_data[channel_index] = (x_data.copy(), y_data.copy())
            else:
                # Take element-wise maximum
                new_y = np.maximum(old_y, y_data)
                self.peak_max_data[channel_index] = (x_data.copy(), new_y)

        # Initialize or update min data
        if channel_index not in self.peak_min_data:
            self.peak_min_data[channel_index] = (x_data.copy(), y_data.copy())
        else:
            old_x, old_y = self.peak_min_data[channel_index]
            # If array length changed (due to resamp or other settings), reset peak data
            if len(old_y) != len(y_data):
                self.peak_min_data[channel_index] = (x_data.copy(), y_data.copy())
            else:
                # Take element-wise minimum
                new_y = np.minimum(old_y, y_data)
                self.peak_min_data[channel_index] = (x_data.copy(), new_y)

    def _update_peak_lines(self):
        """Update the peak detect line plots."""
        active_channel = self.state.activexychannel

        # Update max line
        if active_channel in self.peak_max_data:
            x_data, y_data = self.peak_max_data[active_channel]
            # Optimization: Use skipFiniteCheck for faster setData
            self.peak_max_line.setData(x_data, y_data, skipFiniteCheck=True)

        # Update min line
        if active_channel in self.peak_min_data:
            x_data, y_data = self.peak_min_data[active_channel]
            # Optimization: Use skipFiniteCheck for faster setData
            self.peak_min_line.setData(x_data, y_data, skipFiniteCheck=True)

    def update_peak_channel(self):
        """Called when the active channel changes - update peak line colors and clear data."""
        if self.peak_detect_enabled:
            # Clear old channel's peak data
            self.clear_peak_data()

            # Update peak line colors to match new active channel
            active_channel = self.state.activexychannel
            if active_channel < len(self.linepens):
                color = self.linepens[active_channel].color()
                peak_pen = pg.mkPen(color=color, width=1, style=QtCore.Qt.DotLine)
                self.peak_max_line.setPen(peak_pen)
                self.peak_min_line.setPen(peak_pen)

    # UI Control Methods
    def set_line_width(self, width):
        for pen in self.linepens:
            pen.setWidth(width)
        # Manually trigger redraw for all lines
        for i, line in enumerate(self.lines):
            line.setPen(self.linepens[i])
            ref_pen = self.reference_lines[i].opts['pen']
            ref_pen.setWidth(width)
        self.set_average_line_pen()

    def set_grid(self, is_checked):
        self.plot.showGrid(x=is_checked, y=is_checked, alpha=0.8)

    def set_markers(self, is_checked):
        symbol = "o" if is_checked else None
        size = 3 if is_checked else 0
        for i, line in enumerate(self.lines):
            line.setSymbol(symbol)
            line.setSymbolSize(size)
            line.setSymbolPen(self.linepens[i].color())
            line.setSymbolBrush(self.linepens[i].color())
        self.average_line.setSymbol(symbol)
        self.average_line.setSymbolSize(size)

    def set_pan_and_zoom(self, is_checked):
        self.plot.setMouseEnabled(x=is_checked, y=is_checked)
        if is_checked:
            self.plot.showButtons()
        else:
            self.plot.hideButtons()

    def on_vline_dragged(self, line):
        self.vline_dragged_signal.emit(line.value())
        # Update trigger info text if it's enabled (includes trigger time)
        if self.cursor_manager:
            self.cursor_manager.update_trigger_threshold_text()

    def on_vline_drag_finished(self, line):
        """Called when vline dragging is finished - update cursor positions and display."""
        if self.cursor_manager:
            self.cursor_manager.adjust_cursor_positions()

    def on_hline_dragged(self, line):
        self.hline_dragged_signal.emit(line.value())
        # Update trigger threshold text if it's enabled
        if self.cursor_manager:
            self.cursor_manager.update_trigger_threshold_text()

    def show_cursors(self, visible):
        """Show or hide cursor lines and labels."""
        if self.cursor_manager:
            self.cursor_manager.show_cursors(visible)

    def update_cursor_display(self):
        """Update cursor display when active channel changes."""
        if self.cursor_manager:
            self.cursor_manager.update_active_channel()
            self.cursor_manager.update_trigger_threshold_text()

    def update_trigger_threshold_display(self):
        """Update trigger threshold text display."""
        if self.cursor_manager:
            self.cursor_manager.update_trigger_threshold_text()

    def on_snap_toggled(self, checked):
        """Handle snap to waveform toggle."""
        if self.cursor_manager and checked:
            self.cursor_manager.snap_all_cursors()

    def update_right_axis(self):
        if not self.right_axis: return
        state = self.state
        active_pen = QPen(self.linepens[state.activexychannel])
        active_pen.setWidth(1)
        self.right_axis.setPen(active_pen)
        self.right_axis.setTextPen(color=active_pen.color())
        self.right_axis.setLabel(text=f"Voltage for Board {state.activeboard} Channel {state.selectedchannel}", units='V')
        self.right_axis.conversion_func = lambda val: val * state.VperD[state.activexychannel]

        tick_span = round(2 * 5 * state.VperD[state.activexychannel], 1)
        self.right_axis.setTickSpacing(tick_span, 0.1 * tick_span)
        self.right_axis.update_function()

    def set_average_line_pen(self):
        if self.ui.persistlinesCheck.isChecked():
            pen = pg.mkPen(color='w', width=self.ui.linewidthBox.value())
        else:
            pen = self.linepens[self.state.activexychannel]
        self.average_line.setPen(pen)

    def update_risetime_fit_lines(self, fit_results):
        """Draws or hides the risetime fit visualization lines."""
        # Always hide the lines by default
        for i in range(3):
            self.otherlines[f'fit_{i}'].setVisible(False)

        # Only proceed if the user wants to see the lines and a valid fit exists
        if not self.ui.actionRisetime_fit_lines.isChecked() or fit_results is None:
            return

        try:
            risetime_err = fit_results['risetime_err']

            # If the fit error is infinite, the fit is unreliable, so don't draw
            if abs(risetime_err) == math.inf:
                return

            fit_type = fit_results.get('fit_type', 'piecewise')

            if fit_type == 'edge':
                # New edge-based fitting: draw the linear fit line
                slope = fit_results['slope']
                intercept = fit_results['intercept']
                x_fit = fit_results['x_fit']

                if slope == 0: return

                # Calculate the fitted line over the fit region
                y_fit_line = slope * x_fit + intercept

                # Draw the linear fit line
                # Optimization: Use skipFiniteCheck for faster setData
                self.otherlines['fit_1'].setData(x_fit, y_fit_line, skipFiniteCheck=True)
                self.otherlines['fit_1'].setVisible(True)

                # Optionally, draw horizontal lines at the fit endpoints to show the fit region
                # self.otherlines['fit_0'].setData([x_fit[0], x_fit[0]], [y_fit_line[0]-10, y_fit_line[0]+10])
                # self.otherlines['fit_2'].setData([x_fit[-1], x_fit[-1]], [y_fit_line[-1]-10, y_fit_line[-1]+10])
                # self.otherlines['fit_0'].setVisible(True)
                # self.otherlines['fit_2'].setVisible(True)

            else:  # 'piecewise'
                # Original piecewise fitting: draw the three-segment fit
                popt, xc = fit_results['popt'], fit_results['xc']
                top, left, slope, bot = popt[0], popt[1], popt[2], popt[3]

                if slope == 0: return

                right = left + (top - bot) / slope

                # Set data for the three line segments
                # Optimization: Use skipFiniteCheck for faster setData
                self.otherlines['fit_0'].setData([right, xc[-1]], [top, top], skipFiniteCheck=True)  # Top line
                self.otherlines['fit_1'].setData([left, right], [bot, top], skipFiniteCheck=True)  # Sloped line
                self.otherlines['fit_2'].setData([xc[0], left], [bot, bot], skipFiniteCheck=True)  # Bottom line

                # Make all three segments visible
                for i in range(3):
                    self.otherlines[f'fit_{i}'].setVisible(True)

        except (KeyError, IndexError):
            # Fail silently if the fit_results dictionary is malformed
            pass

