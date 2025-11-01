# plot_manager.py

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore
from PyQt5.QtGui import QColor, QPen, QBrush
from PyQt5.QtWidgets import QGraphicsRectItem
import numpy as np
import time
from collections import deque
import colorsys
from scipy.signal import resample, filtfilt, savgol_filter
from scipy.interpolate import interp1d
from data_processor import find_crossing_distance
from cursor_manager import CursorManager
from heatmap_manager import HeatmapManager
import math


# #############################################################################
# Plotting Helper Functions (Moved from utils.py)
# #############################################################################

def rainbow_colormap(n, start, end):
    """Generate rainbow colors using HSV color space.

    Args:
        n: Number of colors to generate
        start: Starting hue (e.g. 0.0 = red)
        end: Ending hue (e.g. 0.66 = blue)

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
    proxy_view.setMenuEnabled(False)  # disables the right-click menu
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
    zoom_region_changed_signal = pg.QtCore.Signal(tuple, tuple)  # Emits (x_range, y_range)

    def __init__(self, ui, state):
        super().__init__()
        self.ui = ui
        self.state = state
        self.plot = self.ui.plot
        self.lines = []
        self.reference_lines = []
        self.math_channel_lines = {}  # Dictionary: {math_name: plot_line}
        self.math_reference_lines = {}  # Dictionary: {math_name: plot_line}
        self.linepens = []
        self.otherlines = {}  # For trigger lines, fit lines etc.
        self.trigger_arrows = {}  # Store arrow markers for trigger line ends
        self.average_lines = {}  # Dictionary: {channel_index: average line}
        self.right_axis = None
        self.nlines = state.num_board * state.num_chan_per_board
        self.current_vline_pos = 0.0

        # Stabilized data for math channel calculations (after trigger stabilizers)
        self.stabilized_data = [None] * self.nlines

        # Cursor manager (will be initialized after linepens are created)
        self.cursor_manager = None

        # Zoom window ROI
        self.zoom_roi = None

        # Persistence attributes (per-channel)
        self.max_persist_lines = 100  # Total buffer size for heatmap
        self.max_visible_persist_lines = 16  # Only show last 16 for performance
        self.persist_lines_per_channel = {}  # Dictionary: {channel_index: deque of persist lines}
        self.persist_timer = QtCore.QTimer()
        self.persist_timer.timeout.connect(self.update_persist_effect)

        # Heatmap manager for persist line visualization
        self.heatmap_manager = HeatmapManager(self.plot, self.state)

        # Peak detect attributes
        self.peak_detect_enabled = {}  # {channel_index: bool} - per-channel peak detect enabled state
        self.peak_max_line = {}  # {channel_index: PlotDataItem} - peak max line per channel
        self.peak_min_line = {}  # {channel_index: PlotDataItem} - peak min line per channel
        self.peak_max_data = {}  # {channel_index: y_data} - peak max values on fixed x-axis
        self.peak_min_data = {}  # {channel_index: y_data} - peak min values on fixed x-axis
        self.peak_x_data = {}    # {channel_index: x_data} - fixed reference x-axis
        self.peak_skip_events = 0  # Skip N events after clearing peak data

    def _create_click_handler(self, channel_index):
        """Creates a unique click handler function that remembers the channel index."""
        def handler(curve_item):
            # Only emit signal if channel is visible
            if self.state.channel_enabled[channel_index]:
                self.curve_clicked_signal.emit(channel_index)
        return handler

    def _create_math_click_handler(self, math_channel_name):
        """Creates a unique click handler function that remembers the math channel name."""
        def handler(curve_item):
            # Only emit signal if math channel is visible
            if math_channel_name in self.math_channel_lines:
                if self.math_channel_lines[math_channel_name].isVisible():
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
        if self.nlines>4:
            colors = rainbow_colormap(self.nlines, start=0.0, end=0.8)
        else:
            colors = [QColor("red"), QColor("cyan"), QColor("yellow"), QColor("magenta")]
        for i in range(self.nlines):
            if self.nlines>4:
                c = QColor.fromRgbF(*colors[i])
            else:
                c = colors[i]
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

        # Create triangle markers for trigger lines
        self._create_trigger_arrows()
        # Update arrow positions when trigger lines move
        self.otherlines['vline'].sigPositionChanged.connect(lambda: self._update_trigger_arrows('vline'))
        self.otherlines['hline'].sigPositionChanged.connect(lambda: self._update_trigger_arrows('hline'))
        # Update arrow positions when view changes (pan/zoom)
        self.plot.getViewBox().sigRangeChanged.connect(self._update_all_trigger_arrows)

        # Hide trigger lines and arrows initially (will be shown after PLL calibration)
        self.otherlines['vline'].setVisible(False)
        self.otherlines['hline'].setVisible(False)
        for arrow in self.trigger_arrows.values():
            arrow.setVisible(False)

        # Risetime fit lines (initially invisible)
        fit_pen = pg.mkPen(color="w", width=1.0, style=QtCore.Qt.DotLine)
        for i in range(3):
            line = self.plot.plot([0], [0], pen=fit_pen, name=f"fitline_{i}")
            line.setVisible(False)
            self.otherlines[f'fit_{i}'] = line

        # Zoom window ROI (initially invisible)
        # Create a rectangular ROI with semi-transparent gray fill
        # Create semi-transparent gray pen and brush
        roi_pen = pg.mkPen(color=QColor(128, 128, 128, 100), width=2)  # Semi-transparent gray border
        roi_hover_pen = pg.mkPen(color=QColor(255, 255, 255, 200), width=2)  # Semi-transparent white hover

        self.zoom_roi = pg.RectROI(
            pos=[0, 0],  # Will be set when shown
            size=[1, 1],  # Will be set when shown
            pen=roi_pen,
            movable=True,
            removable=False  # Don't allow removing the ROI
        )

        # Set the hover pen for the ROI border
        self.zoom_roi.pen = roi_pen
        self.zoom_roi.hoverPen = roi_hover_pen
        self.zoom_roi.currentPen = roi_pen

        # Add corner handles for resizing - this gives 4 corner handles
        # The RectROI by default has corner handles when created
        # But we'll explicitly set up the handle appearance

        # Set the handle colors to be more visible
        self.zoom_roi.handlePen = pg.mkPen(color=QColor(150, 150, 150, 200), width=2)
        self.zoom_roi.handleHoverPen = pg.mkPen(color=QColor(255, 255, 255, 255), width=3)

        # Add side handles for edge resizing (top, bottom, left, right)
        # This allows dragging individual edges
        self.zoom_roi.addScaleHandle([1, 0.5], [0, 0.5])  # Right edge
        self.zoom_roi.addScaleHandle([0, 0.5], [1, 0.5])  # Left edge
        self.zoom_roi.addScaleHandle([0.5, 1], [0.5, 0])  # Bottom edge
        self.zoom_roi.addScaleHandle([0.5, 0], [0.5, 1])  # Top edge

        # Create a semi-transparent fill by adding a rectangle inside the ROI
        self.zoom_roi_fill = QGraphicsRectItem(0, 0, 1, 1, self.zoom_roi)
        fill_brush = QBrush(QColor(128, 128, 128, 26))  # Gray with alpha ~0.1 (26/255)
        self.zoom_roi_fill.setBrush(fill_brush)
        self.zoom_roi_fill.setPen(pg.mkPen(None))  # No border for the fill

        self.plot.addItem(self.zoom_roi)
        self.zoom_roi.setVisible(False)
        # Connect signal to notify when ROI changes
        self.zoom_roi.sigRegionChanged.connect(self.on_zoom_roi_changed)
        self.zoom_roi.sigRegionChanged.connect(self._update_zoom_roi_fill)

        # Persistence average lines (created per-channel on demand)
        # self.average_lines = {} already initialized in __init__

        # Peak detect lines are created per-channel on demand (see set_peak_detect)

        # Cursor manager (initialized after linepens and lines are created)
        self.cursor_manager = CursorManager(self.plot, self.state, self.linepens, self.ui, self.otherlines, self.lines)
        self.cursor_manager.setup_cursors()

        # Legend for channel names
        self.legend_text = pg.TextItem(anchor=(1, 0), color='w')  # anchor=(1,0) means top-right
        self.plot.addItem(self.legend_text)
        self.legend_text.setPos(1.0, 1.0)  # Will be updated to actual position

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
        # Store non-resampled data for math channel calculations (before doresamp)
        self.stabilized_data_noresamp = [None] * self.nlines

        # Store processed data before applying extra trig stabilizer
        processed_data = [None] * self.nlines
        # Store non-resampled processed data (for math channels)
        processed_data_noresamp = [None] * self.nlines

        # First pass: process all data (interleaving, resampling)
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
                    # In two-channel mode, samples are spaced 2x further apart in time.
                    num_valid_samples = xy_data.shape[2] // 2
                    y_to_plot = y_data_full[:num_valid_samples]

                    # Use the raw x values directly but multiply by 2 to get correct sample spacing.
                    # The raw x-axis has corrections applied but wrong spacing (x_step1 instead of 2*x_step1).
                    # Multiplying by 2 gives correct spacing AND preserves corrections.
                    x_to_plot = x_data_full[:num_valid_samples] * 2.0
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

            if xdatanew is None:
                continue  # Skip if no data for this line (e.g., secondary interleaved line)

            # Store non-resampled data (before doresamp) for math channel calculations
            processed_data_noresamp[li] = (xdatanew.copy(), ydatanew.copy())

            # --- Resampling (if enabled) ---
            if s.doresamp[li]:
                ydatanew, xdatanew = resample(ydatanew, len(xdatanew) * s.doresamp[li], t=xdatanew)

            # Store the processed data (with resampling)
            processed_data[li] = (xdatanew, ydatanew)

        # Calculate extra trig stabilizer correction using noextboard
        extra_trig_correction = None
        if s.extra_trig_stabilizer_enabled and s.noextboard != -1: # and s.downsamplefactor==1: # disable at less zoom?
            # Use the first channel of the noextboard for correction calculation
            noext_li = s.noextboard * s.num_chan_per_board
            if s.dotwochannel: noext_li += s.triggerchan[s.noextboard]
            if processed_data[noext_li] is not None:
                xdatanew, ydatanew = processed_data[noext_li]
                vline_time = self.otherlines['vline'].value()
                hline_pos = (s.triggerlevel - 127) * s.yscale * 256
                # Include triggerdelta in the threshold (per-board setting)
                hline_threshold = hline_pos + s.triggerdelta[s.noextboard] * s.yscale * 256

                fitwidth = (s.max_x - s.min_x)
                xc = xdatanew[(xdatanew > vline_time - fitwidth) & (xdatanew < vline_time + fitwidth)]

                if xc.size > 2:
                    numsamp = s.distcorrsamp*10
                    if s.doresamp[noext_li]: numsamp *= s.doresamp[noext_li]
                    fitwidth *= numsamp / xc.size

                    xc = xdatanew[(xdatanew > vline_time - fitwidth) & (xdatanew < vline_time + fitwidth)]
                    yc = ydatanew[(xdatanew > vline_time - fitwidth) & (xdatanew < vline_time + fitwidth)]

                    # For falling edges, invert both the signal and the threshold
                    threshold_to_use = hline_threshold
                    if s.fallingedge[s.noextboard]:
                        yc = -yc
                        threshold_to_use = -hline_threshold

                    # Pulse stabilizer mode: use edge midpoint instead of threshold crossing
                    if s.pulse_stabilizer_enabled[s.noextboard] and yc.size > 0:
                        # Find index closest to trigger position
                        trigger_idx = np.argmin(np.abs(xc - vline_time))
                        delta_threshold = s.triggerdelta[s.noextboard] * s.yscale * 256

                        # Search forward for maximum (stops when data goes down by more than delta)
                        edge_max = yc[trigger_idx]
                        for i in range(trigger_idx, len(yc)):
                            if yc[i] > edge_max:
                                edge_max = yc[i]
                            elif edge_max - yc[i] > delta_threshold:
                                break

                        # Search backward for minimum (stops when data goes up by more than delta)
                        edge_min = yc[trigger_idx]
                        for i in range(trigger_idx, -1, -1):
                            if yc[i] < edge_min:
                                edge_min = yc[i]
                            elif yc[i] - edge_min > 0: # delta_threshold: # finding the min we just ask it to be about flat
                                break

                        threshold_to_use = (edge_min + edge_max) / 2.0
                        #print(edge_max, edge_min)

                    if xc.size > 1:
                        distcorrtemp = find_crossing_distance(yc, threshold_to_use, vline_time, xc[0], xc[1] - xc[0])
                        #print("distcorrtemp", distcorrtemp)
                        max_correction = s.distcorrtol * 10 * s.downsamplefactor / s.nsunits
                        #print("max_correction", max_correction)
                        if distcorrtemp is not None and abs(distcorrtemp) < max_correction:
                            # No need to clamp the correction to stay within the limit, since it is starting fresh every time
                            # Store the correction to apply to all boards
                            extra_trig_correction = distcorrtemp

        # Second pass: apply correction and plot
        for li in range(self.nlines):
            board_idx = li // s.num_chan_per_board

            if processed_data[li] is None:
                continue

            xdatanew, ydatanew = processed_data[li]

            # Also get non-resampled data
            if processed_data_noresamp[li] is not None:
                xdata_noresamp, ydata_noresamp = processed_data_noresamp[li]
            else:
                xdata_noresamp, ydata_noresamp = None, None

            # Apply extra trig stabilizer correction to non-secondary boards
            if extra_trig_correction is not None:
                is_oversample_secondary = s.dooversample[board_idx] and board_idx % 2 == 1
                if not is_oversample_secondary:
                    xdatanew = xdatanew - extra_trig_correction
                    if xdata_noresamp is not None:
                        xdata_noresamp = xdata_noresamp - extra_trig_correction

            # Apply per-channel time skew offset
            time_skew_offset = s.time_skew[li] / s.nsunits  # Convert ns to current time units
            xdatanew = xdatanew + time_skew_offset
            if xdata_noresamp is not None:
                xdata_noresamp = xdata_noresamp + time_skew_offset

            # Apply frequency response correction (FIR filter) if enabled
            if s.fir_correction_enabled:
                # Determine which FIR coefficients to use
                fir_coeffs = None

                if s.dooversample[board_idx] and s.dointerleaved[board_idx]:
                    # Interleaved oversampling mode: use interleaved coefficients (6.4 GHz)
                    fir_coeffs = s.fir_coefficients_interleaved
                elif s.dooversample[board_idx]:
                    # Oversampling only (not interleaved): use board-specific coefficients
                    # Board N uses oversample[0], Board N+1 uses oversample[1]
                    if board_idx % 2 == 0:
                        fir_coeffs = s.fir_coefficients_oversample[0]
                    else:
                        fir_coeffs = s.fir_coefficients_oversample[1]
                elif s.dotwochannel[board_idx]:
                    # Two-channel mode: use two-channel coefficients (1.6 GHz per channel)
                    fir_coeffs = s.fir_coefficients_twochannel
                else:
                    # Non-oversampling, single-channel mode: use regular coefficients (3.2 GHz)
                    fir_coeffs = s.fir_coefficients

                if fir_coeffs is not None:
                    ydatanew = filtfilt(fir_coeffs, [1.0], ydatanew)
                    if ydata_noresamp is not None:
                        ydata_noresamp = filtfilt(fir_coeffs, [1.0], ydata_noresamp)

            # Apply Savitzky-Golay polynomial filtering if enabled
            if s.polynomial_filtering_enabled:
                # Ensure window length is valid (odd and <= data length)
                window_length = s.savgol_window_length
                polyorder = s.savgol_polyorder

                # Validate and adjust window length if needed
                if window_length >= len(ydatanew):
                    window_length = len(ydatanew) - 1 if len(ydatanew) % 2 == 0 else len(ydatanew) - 2
                if window_length < 3:
                    window_length = 3
                if window_length % 2 == 0:  # Must be odd
                    window_length += 1

                # Ensure polyorder < window_length
                if polyorder >= window_length:
                    polyorder = window_length - 1

                # Apply filter
                try:
                    ydatanew = savgol_filter(ydatanew, window_length, polyorder, mode='interp')
                    if ydata_noresamp is not None:
                        # Apply same validation for noresamp data
                        wl_noresamp = window_length
                        if wl_noresamp >= len(ydata_noresamp):
                            wl_noresamp = len(ydata_noresamp) - 1 if len(ydata_noresamp) % 2 == 0 else len(ydata_noresamp) - 2
                        if wl_noresamp < 3:
                            wl_noresamp = 3
                        if wl_noresamp % 2 == 0:
                            wl_noresamp += 1
                        po_noresamp = polyorder if polyorder < wl_noresamp else wl_noresamp - 1
                        ydata_noresamp = savgol_filter(ydata_noresamp, wl_noresamp, po_noresamp, mode='interp')
                except Exception as e:
                    # If filter fails, continue without filtering
                    pass

            # --- Final plotting and persistence ---
            # Optimization: Use skipFiniteCheck for faster setData
            self.lines[li].setData(xdatanew, ydatanew, skipFiniteCheck=True)

            # Store stabilized data for math channel calculations
            self.stabilized_data[li] = (xdatanew, ydatanew)
            if xdata_noresamp is not None:
                self.stabilized_data_noresamp[li] = (xdata_noresamp, ydata_noresamp)
            else:
                self.stabilized_data_noresamp[li] = (xdatanew, ydatanew)  # Fallback to resampled

            # Add to persistence if channel is enabled and has persistence enabled
            # Accumulate if persist lines OR persist average OR persist heatmap is enabled
            if (s.persist_time[li] > 0 and s.channel_enabled[li] and
                (s.persist_lines_enabled[li] or s.persist_avg_enabled[li] or s.persist_heatmap_enabled[li])):
                self._add_to_persistence(xdatanew, ydatanew, li)

            # --- Peak detect update ---
            if li in self.peak_detect_enabled and self.peak_detect_enabled[li]:
                self._update_peak_data(li, xdatanew, ydatanew)

        self.update_persist_average()

        # Update peak detect lines for all enabled channels
        if self.peak_detect_enabled:  # Check if dictionary is not empty
            self._update_peak_lines()

    def update_reference_line_color(self, channel_index):
        """Update the reference line color to match the channel color."""
        if 0 <= channel_index < len(self.reference_lines) and channel_index < len(self.linepens):
            # Get the current channel color
            channel_pen = self.linepens[channel_index]
            channel_color = QColor(channel_pen.color())

            # Create reference color with transparency
            ref_color = QColor(channel_color)
            ref_color.setAlphaF(0.5)

            # Update reference line pen
            ref_pen = pg.mkPen(color=ref_color, width=channel_pen.width())
            self.reference_lines[channel_index].setPen(ref_pen)

    def update_reference_plot(self, channel_index, x_data, y_data, width=None):
        """Sets the data for a channel's reference waveform.

        Args:
            channel_index: The channel index
            x_data: X data for the reference
            y_data: Y data for the reference
            width: Optional line width (uses stored width from reference, or current channel width if None)
        """
        if 0 <= channel_index < len(self.reference_lines):
            ref_line = self.reference_lines[channel_index]

            # Update the reference line color and width
            if channel_index < len(self.linepens):
                # Get the current channel color
                channel_pen = self.linepens[channel_index]
                channel_color = QColor(channel_pen.color())

                # Create reference color with transparency
                ref_color = QColor(channel_color)
                ref_color.setAlphaF(0.5)

                # Use provided width or current channel width
                ref_width = width if width is not None else channel_pen.width()

                # Update reference line pen
                ref_pen = pg.mkPen(color=ref_color, width=ref_width)
                ref_line.setPen(ref_pen)

            # Optimization: Use skipFiniteCheck for faster setData
            ref_line.setData(x_data, y_data, skipFiniteCheck=True)
            ref_line.setVisible(True)

    def hide_reference_plot(self, channel_index):
        """Hides a specific reference plot."""
        if 0 <= channel_index < len(self.reference_lines):
            self.reference_lines[channel_index].setVisible(False)

    def update_legend(self):
        """Updates the legend with channel names in the top right corner."""
        # Only show legend if the action is checked
        if not self.ui.actionChannel_name_legend.isChecked():
            self.legend_text.setVisible(False)
            return

        s = self.state
        legend_items = []

        # Collect channels that have names and are visible
        for li in range(self.nlines):
            if s.channel_names[li] and self.lines[li].isVisible():
                # Get the channel color
                pen = self.linepens[li]
                color = pen.color()
                # Convert QColor to hex string
                color_hex = color.name()
                # Add to legend items
                legend_items.append(f'<span style="color:{color_hex};">{s.channel_names[li]}</span>')

        # Build HTML text
        if legend_items:
            html_text = '<br>'.join(legend_items)
            self.legend_text.setHtml(html_text)
            self.legend_text.setVisible(True)
            # Position in top right corner (in view coordinates)
            view_range = self.plot.viewRange()
            x_max = view_range[0][1]  # Right edge of view
            x_range = x_max - view_range[0][0]
            y_max = view_range[1][1]  # Top edge of view
            y_range = y_max - view_range[1][0]
            self.legend_text.setPos(x_max-0.01*x_range, y_max-0.01*y_range)
        else:
            self.legend_text.setVisible(False)

    def update_math_channel_lines(self, math_window=None, reference_data=None):
        """Updates the set of math channel plot lines based on current math channel definitions.

        Args:
            math_window: The MathChannelsWindow instance (optional, will try to find it if not provided)
            reference_data: Dictionary mapping channel indices to reference data (for looking up source channels)
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

            # Get width from source channel (ch1)
            ch1_idx = math_def.get('ch1')
            if not isinstance(ch1_idx, str) and ch1_idx < len(self.linepens):
                # Source is a regular channel - use its current width
                width = self.linepens[ch1_idx].width()
            elif isinstance(ch1_idx, str) and ch1_idx.startswith("Ref") and reference_data is not None:
                # Source is a reference - look up the original channel and use its current width
                try:
                    ref_num = int(ch1_idx[3:])  # Extract number from "Ref0", "Ref1", etc.
                    if ref_num in reference_data and ref_num < len(self.linepens):
                        # Use the current width of the channel this reference came from
                        width = self.linepens[ref_num].width()
                    else:
                        width = math_def.get('width', 2)
                except (ValueError, IndexError):
                    width = math_def.get('width', 2)
            else:
                # Source is another math channel or unknown - use default width
                width = math_def.get('width', 2)

            if math_name not in self.math_channel_lines:
                # Create a new dashed line with the specified color and width
                pen = pg.mkPen(color=color, width=width, style=QtCore.Qt.DashLine)
                line = self.plot.plot(pen=pen, name=math_name, skipFiniteCheck=True, connect="finite")
                # Make the line clickable
                line.curve.setClickable(True)
                line.curve.sigClicked.connect(self._create_math_click_handler(math_name))
                self.math_channel_lines[math_name] = line
                # Set initial visibility
                line.setVisible(displayed)
            else:
                # Update the color and width (from source channel) of existing line
                pen = pg.mkPen(color=color, width=width, style=QtCore.Qt.DashLine)
                self.math_channel_lines[math_name].setPen(pen)
                # Update visibility
                self.math_channel_lines[math_name].setVisible(displayed)

    def update_math_channel_data(self, math_results):
        """Update the math channel plot lines with calculated data.

        Args:
            math_results: Dictionary mapping math channel names to (x_data, y_data) tuples
        """
        for math_name, (x_data, y_data) in math_results.items():
            if math_name in self.math_channel_lines:
                # Optimization: Use skipFiniteCheck for faster setData
                self.math_channel_lines[math_name].setData(x_data, y_data, skipFiniteCheck=True)

    def update_math_reference_lines(self, math_window, main_window):
        """Updates the set of math reference lines based on reference data.

        Args:
            math_window: The MathChannelsWindow instance
            main_window: The MainWindow instance (for reference data)
        """
        if math_window is None:
            return

        # Get current math channel names that have references
        current_ref_names = set(main_window.math_reference_data.keys())

        # Remove lines for references that no longer exist
        for math_name in list(self.math_reference_lines.keys()):
            if math_name not in current_ref_names:
                line = self.math_reference_lines[math_name]
                self.plot.removeItem(line)
                del self.math_reference_lines[math_name]

        # Create or update reference lines
        for math_name, ref_data in main_window.math_reference_data.items():
            # Find the corresponding math channel definition for color and width
            math_def = next((m for m in math_window.math_channels if m['name'] == math_name), None)
            if math_def is None:
                continue  # Math channel no longer exists

            color = math_def.get('color', '#00FFFF')

            # Use stored width from reference, or current math channel width if not stored
            width = ref_data.get('width', math_def.get('width', 2))

            # Create reference color with transparency to match channel behavior
            ref_color = QColor(color)
            ref_color.setAlphaF(0.5)

            if math_name not in self.math_reference_lines:
                # Create a new dotted reference line with the same color but semi-transparent
                pen = pg.mkPen(color=ref_color, width=width, style=QtCore.Qt.DotLine)
                line = self.plot.plot(pen=pen, name=f"{math_name}_ref", skipFiniteCheck=True, connect="finite")
                self.math_reference_lines[math_name] = line
            else:
                # Update the color (and width from stored reference data)
                pen = pg.mkPen(color=ref_color, width=width, style=QtCore.Qt.DotLine)
                self.math_reference_lines[math_name].setPen(pen)

            # Update data and visibility
            x_data = ref_data['x_ns'] / self.state.nsunits
            y_data = ref_data['y']

            # Resample reference to match the stored doresamp setting for display
            # Use stored doresamp if available (for backward compatibility and for references)
            doresamp_to_use = ref_data.get('doresamp', 1)
            if doresamp_to_use > 1:
                from scipy.signal import resample
                y_resampled, x_resampled = resample(y_data, len(x_data) * doresamp_to_use, t=x_data)
                self.math_reference_lines[math_name].setData(x_resampled, y_resampled, skipFiniteCheck=True)
            else:
                self.math_reference_lines[math_name].setData(x_data, y_data, skipFiniteCheck=True)

            # Set visibility
            is_visible = main_window.math_reference_visible.get(math_name, False)
            self.math_reference_lines[math_name].setVisible(is_visible)

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
        # Update trigger arrow positions when plot area changes
        self._update_trigger_arrows('vline')
        self._update_trigger_arrows('hline')
        if self.cursor_manager:
            self.cursor_manager.adjust_cursor_positions()

        # Update zoom ROI if it's visible (units or range may have changed)
        self.update_zoom_roi_for_time_change()

    def draw_trigger_lines(self):
        """Draws the horizontal and vertical trigger lines on the plot."""
        state = self.state
        vline_pos = 4 * 10 * (state.triggerpos + 1.0) * (state.downsamplefactor / state.nsunits / state.samplerate)
        self.otherlines['vline'].setValue(vline_pos)
        hline_pos = (state.triggerlevel - 127) * state.yscale * 256
        self.otherlines['hline'].setValue(hline_pos)
        self.current_vline_pos = vline_pos

    # Persistence Methods
    def set_persistence(self, value, channel_index=None):
        """Set persistence time for a specific channel."""
        if channel_index is None:
            channel_index = self.state.activexychannel

        persist_time_ms = 50 * pow(2, value) if value > 0 else 0
        self.state.persist_time[channel_index] = persist_time_ms

        # Start/stop timer based on whether ANY channel has persistence active
        any_persist_active = any(t > 0 for t in self.state.persist_time)
        if any_persist_active:
            if not self.persist_timer.isActive():
                self.persist_timer.start(50)
        else:
            self.persist_timer.stop()
            self.clear_persist(channel_index)

        # Update the spinbox tooltip to show the actual time value
        time_str = f"{persist_time_ms / 1000.0:.1f} s" if persist_time_ms > 0 else "Off"
        self.ui.persistTbox.setToolTip(f"Persistence time: {time_str}")

    def _add_to_persistence(self, x, y, line_idx):
        """Add a trace to the persistence buffer for a specific channel."""
        # Initialize deque for this channel if needed
        if line_idx not in self.persist_lines_per_channel:
            self.persist_lines_per_channel[line_idx] = deque(maxlen=self.max_persist_lines)

        persist_lines = self.persist_lines_per_channel[line_idx]

        # If we're about to remove the oldest line, remove it from heatmap first
        if len(persist_lines) >= self.max_persist_lines:
            oldest_item, _, _, oldest_x, oldest_y = persist_lines.popleft()
            self.plot.removeItem(oldest_item)
            # Remove from heatmap
            if self.state.persist_heatmap_enabled[line_idx]:
                self.heatmap_manager.remove_trace(oldest_x, oldest_y, line_idx)

        # If heatmap mode is enabled, check if settings or view changed BEFORE adding to persist buffer
        if self.state.persist_heatmap_enabled[line_idx]:
            # Check if gain/offset changed - need to clear everything
            if self.heatmap_manager.check_gain_offset_changed(line_idx):
                # Clear all persist lines for this channel since they're in the old scale
                for item_data in list(persist_lines):
                    item = item_data[0]
                    self.plot.removeItem(item)
                persist_lines.clear()
                # Just clear the heatmap - don't regenerate with empty data
                # It will rebuild naturally as new traces come in
                self.heatmap_manager.clear_for_settings_change(line_idx)
                # Continue to add the current trace with the new scale
                # Don't return - let it fall through to add this trace
            # Check if view (pan/zoom) changed - regenerate heatmap from existing persist lines
            elif self.heatmap_manager.check_view_changed(line_idx):
                # Regenerate heatmap with new view range
                self.heatmap_manager.regenerate(line_idx, persist_lines)

        pen = self.linepens[line_idx]
        color = pen.color()
        color.setAlpha(100)
        new_pen = pg.mkPen(color, width=1)
        persist_item = self.plot.plot(x, y, pen=new_pen, skipFiniteCheck=True, connect="finite")
        # If heatmap mode is enabled, hide the individual persist lines
        persist_item.setVisible(self.state.persist_lines_enabled[line_idx] and not self.state.persist_heatmap_enabled[line_idx])

        # Store a copy of the data for later heatmap removal
        persist_lines.append((persist_item, time.time(), line_idx, x.copy(), y.copy()))

        # If heatmap mode is enabled, add this trace to the heatmap
        if self.state.persist_heatmap_enabled[line_idx]:
            # Don't recalculate ranges - use fixed ranges set during initialization
            # This prevents rect/data mismatch that causes scaling artifacts
            self.heatmap_manager.add_trace(x, y, line_idx, persist_lines)

    def update_persist_effect(self):
        """Updates the alpha/transparency of persistent lines for all channels."""
        if not self.persist_lines_per_channel:
            self.persist_timer.stop()
            return

        current_time = time.time()

        # Update each channel's persist lines
        for channel_idx, persist_lines in list(self.persist_lines_per_channel.items()):
            channel_persist_time = self.state.persist_time[channel_idx]

            if channel_persist_time == 0:
                continue

            items_to_remove = []
            # Only show the last max_visible_persist_lines (16) for performance
            # But keep all 100 in the buffer for heatmap
            total_lines = len(persist_lines)
            visible_start_idx = max(0, total_lines - self.max_visible_persist_lines)

            for idx, item_data in enumerate(persist_lines):
                item = item_data[0]
                creation_time = item_data[1]
                li = item_data[2]
                age = (current_time - creation_time) * 1000.0
                if age > channel_persist_time:
                    items_to_remove.append(item_data)
                else:
                    # Only make the last 16 lines visible
                    should_be_visible = (idx >= visible_start_idx and
                                        self.state.persist_lines_enabled[channel_idx] and
                                        not self.state.persist_heatmap_enabled[channel_idx])

                    if should_be_visible:
                        # Update alpha for visible lines
                        alpha = int(100 * (1 - (age / channel_persist_time)))
                        pen = self.linepens[li]
                        color = pen.color()
                        color.setAlpha(alpha)
                        new_pen = pg.mkPen(color, width=1)
                        item.setPen(new_pen)
                        item.setVisible(True)
                    else:
                        # Hide older lines to improve performance
                        item.setVisible(False)

            # Remove expired items
            for item_data in items_to_remove:
                item, _, _, x_data, y_data = item_data
                self.plot.removeItem(item)
                persist_lines.remove(item_data)
                # Remove from heatmap incrementally
                if self.state.persist_heatmap_enabled[channel_idx]:
                    self.heatmap_manager.remove_trace(x_data, y_data, channel_idx)

    def update_persist_average(self):
        """Calculates and plots the average of persistent traces for all channels with data."""
        s = self.state

        # Iterate over all channels that have persist lines
        for channel_idx, persist_lines in self.persist_lines_per_channel.items():
            if len(persist_lines) < 1:
                # Clear the average line for this channel if it exists
                if channel_idx in self.average_lines:
                    self.average_lines[channel_idx].clear()
                continue

            # Create average line for this channel if it doesn't exist
            if channel_idx not in self.average_lines:
                pen = self.linepens[channel_idx]
                avg_line = self.plot.plot(pen=pg.mkPen(color=pen.color(), width=1),
                                          name=f"persist_avg_ch{channel_idx}")
                # Make the average line clickable to select the channel
                avg_line.curve.setClickable(True)
                avg_line.curve.sigClicked.connect(self._create_click_handler(channel_idx))
                self.average_lines[channel_idx] = avg_line
                # Set initial visibility based on state
                avg_line.setVisible(s.persist_avg_enabled[channel_idx])

            # Only use the last 16 lines for averaging (for performance)
            lines_to_average = list(persist_lines)[-self.max_visible_persist_lines:]

            first_line_item = lines_to_average[0][0]
            min_x, max_x = first_line_item.xData.min(), first_line_item.xData.max()

            board_idx = channel_idx // s.num_chan_per_board
            num_points = s.expect_samples * 40 * (2 if s.dointerleaved[board_idx] else 1)
            common_x_axis = np.linspace(min_x, max_x, num_points)

            resampled_y_values = [np.interp(common_x_axis, item.xData, item.yData) for item, _, _, _, _ in lines_to_average]

            if resampled_y_values:
                y_average = np.mean(resampled_y_values, axis=0)
                if s.doresamp[channel_idx]:
                    y_average, common_x_axis = resample(y_average, len(common_x_axis) * s.doresamp[channel_idx],
                                                        t=common_x_axis)
                # Optimization: Use skipFiniteCheck for faster setData
                self.average_lines[channel_idx].setData(common_x_axis, y_average, skipFiniteCheck=True)

    def clear_persist(self, channel_index=None):
        """Clear persistence for a specific channel or all channels.

        Args:
            channel_index: If specified, clear only this channel. If None, clear all channels.
        """
        if channel_index is not None:
            # Clear only the specified channel
            if channel_index in self.persist_lines_per_channel:
                persist_lines = self.persist_lines_per_channel[channel_index]
                for item_data in list(persist_lines):
                    item = item_data[0]
                    self.plot.removeItem(item)
                persist_lines.clear()
            # Clear heatmap for this channel
            self.heatmap_manager.clear_channel(channel_index)
        else:
            # Clear all channels
            for channel_idx, persist_lines in list(self.persist_lines_per_channel.items()):
                for item_data in list(persist_lines):
                    item = item_data[0]
                    self.plot.removeItem(item)
                persist_lines.clear()
            self.persist_lines_per_channel.clear()
            # Clear all heatmaps
            for channel_idx in list(self.heatmap_manager.persist_heatmap_data.keys()):
                self.heatmap_manager.clear_channel(channel_idx)

        # Clear the average line(s) for the specified channel(s)
        if channel_index is not None:
            # Clear only the specified channel's average line
            if channel_index in self.average_lines:
                self.average_lines[channel_index].clear()
        else:
            # Clear all channels' average lines
            for avg_line in self.average_lines.values():
                avg_line.clear()

    # Peak Detect Methods
    def set_peak_detect(self, enabled):
        """Enable or disable peak detect mode for the active channel."""
        active_channel = self.state.activexychannel
        self.peak_detect_enabled[active_channel] = enabled

        if enabled:
            # Create peak lines for this channel if they don't exist
            if active_channel not in self.peak_max_line:
                peak_pen = pg.mkPen(color='w', width=1, style=QtCore.Qt.DotLine)
                self.peak_max_line[active_channel] = self.plot.plot(pen=peak_pen, name=f"Peak_Max_CH{active_channel+1}",
                                                                     skipFiniteCheck=True, connect="finite")
                self.peak_min_line[active_channel] = self.plot.plot(pen=peak_pen, name=f"Peak_Min_CH{active_channel+1}",
                                                                     skipFiniteCheck=True, connect="finite")

            # Set peak line colors and width to match active channel
            if active_channel < len(self.linepens):
                base_pen = self.linepens[active_channel]
                color = base_pen.color()
                width = base_pen.width()
                peak_pen = pg.mkPen(color=color, width=width, style=QtCore.Qt.DotLine)
                self.peak_max_line[active_channel].setPen(peak_pen)
                self.peak_min_line[active_channel].setPen(peak_pen)

            # Clear any existing peak data for this channel
            self.clear_peak_data()
            # Show the lines
            self.peak_max_line[active_channel].setVisible(True)
            self.peak_min_line[active_channel].setVisible(True)
        else:
            # Hide the lines and clear data
            if active_channel in self.peak_max_line:
                self.peak_max_line[active_channel].setVisible(False)
                self.peak_min_line[active_channel].setVisible(False)
            self.clear_peak_data()

    def clear_peak_data(self):
        """Clear peak detect data for the active channel."""
        active_channel = self.state.activexychannel
        if active_channel in self.peak_max_data:
            del self.peak_max_data[active_channel]
        if active_channel in self.peak_min_data:
            del self.peak_min_data[active_channel]
        if active_channel in self.peak_x_data:
            del self.peak_x_data[active_channel]
        if active_channel in self.peak_max_line:
            self.peak_max_line[active_channel].clear()
            self.peak_min_line[active_channel].clear()
        # Skip the next event to avoid glitches after timebase changes
        self.peak_skip_events = 1

    def _update_peak_data(self, channel_index, x_data, y_data):
        """Update peak max/min data for a channel.

        Uses a fixed x-axis and interpolates incoming waveforms onto it to avoid
        jitter from trigger stabilization.
        """
        # Skip first event after clearing to avoid glitches
        if self.peak_skip_events > 0:
            self.peak_skip_events -= 1
            return

        # Initialize with a fixed x-axis on first data
        if channel_index not in self.peak_x_data:
            # Create fixed reference x-axis from first frame
            self.peak_x_data[channel_index] = x_data.copy()
            self.peak_max_data[channel_index] = y_data.copy()
            self.peak_min_data[channel_index] = y_data.copy()
            return

        # Get the fixed reference x-axis
        fixed_x = self.peak_x_data[channel_index]

        # If array length changed (due to resamp or other settings), reset peak data
        if len(fixed_x) != len(x_data):
            self.peak_x_data[channel_index] = x_data.copy()
            self.peak_max_data[channel_index] = y_data.copy()
            self.peak_min_data[channel_index] = y_data.copy()
            return

        # Interpolate incoming y_data onto the fixed x-axis
        # Use linear interpolation with extrapolation fill
        y_interp = np.interp(fixed_x, x_data, y_data)

        # Update max data
        old_y_max = self.peak_max_data[channel_index]
        new_y_max = np.maximum(old_y_max, y_interp)
        self.peak_max_data[channel_index] = new_y_max

        # Update min data
        old_y_min = self.peak_min_data[channel_index]
        new_y_min = np.minimum(old_y_min, y_interp)
        self.peak_min_data[channel_index] = new_y_min

    def _update_peak_lines(self):
        """Update the peak detect line plots using the fixed reference x-axis."""
        # Update lines for all channels that have peak detect enabled
        for channel_index in self.peak_detect_enabled:
            if self.peak_detect_enabled[channel_index] and channel_index in self.peak_x_data:
                x_data = self.peak_x_data[channel_index]

                # Update max line
                if channel_index in self.peak_max_data and channel_index in self.peak_max_line:
                    y_data = self.peak_max_data[channel_index]
                    # Optimization: Use skipFiniteCheck for faster setData
                    self.peak_max_line[channel_index].setData(x_data, y_data, skipFiniteCheck=True)

                # Update min line
                if channel_index in self.peak_min_data and channel_index in self.peak_min_line:
                    y_data = self.peak_min_data[channel_index]
                    # Optimization: Use skipFiniteCheck for faster setData
                    self.peak_min_line[channel_index].setData(x_data, y_data, skipFiniteCheck=True)

    def update_peak_channel(self):
        """Called when the active channel changes - no longer needed with per-channel peak detect."""
        # Peak detect is now per-channel, so nothing to do here
        pass

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

        # Update peak line widths for all enabled channels
        for channel_index in self.peak_detect_enabled:
            if self.peak_detect_enabled[channel_index] and channel_index < len(self.linepens):
                if channel_index in self.peak_max_line:
                    base_pen = self.linepens[channel_index]
                    color = base_pen.color()
                    peak_pen = pg.mkPen(color=color, width=width, style=QtCore.Qt.DotLine)
                    self.peak_max_line[channel_index].setPen(peak_pen)
                    self.peak_min_line[channel_index].setPen(peak_pen)

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
        # Set markers on all average lines
        for avg_line in self.average_lines.values():
            avg_line.setSymbol(symbol)
            avg_line.setSymbolSize(size)

    def show_trigger_lines(self):
        """Show trigger lines and arrows after PLL calibration is complete."""
        self.otherlines['vline'].setVisible(True)
        self.otherlines['hline'].setVisible(True)
        for arrow in self.trigger_arrows.values():
            arrow.setVisible(True)

    def set_pan_and_zoom(self, is_checked):
        self.plot.setMouseEnabled(x=is_checked, y=is_checked)
        if is_checked:
            #self.plot.showButtons()
            # Disable autoscale button during pan/zoom
            view_box = self.plot.getViewBox()
            if hasattr(view_box, 'autoBtn') and view_box.autoBtn is not None:
                view_box.autoBtn.hide()
                view_box.autoBtn.setEnabled(False)
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

    def on_zoom_roi_changed(self):
        """Called when zoom ROI is moved or resized."""
        if self.zoom_roi and self.zoom_roi.isVisible():
            # Get the ROI bounds
            pos = self.zoom_roi.pos()
            size = self.zoom_roi.size()
            x_range = (pos[0], pos[0] + size[0])
            y_range = (pos[1], pos[1] + size[1])
            # Emit signal with the new range
            self.zoom_region_changed_signal.emit(x_range, y_range)

    def show_zoom_roi(self):
        """Show the zoom ROI and set its default position based on trigger lines."""
        if self.zoom_roi is None:
            return

        # Get current trigger positions
        vline_pos = self.otherlines['vline'].value()
        hline_pos = self.otherlines['hline'].value()

        # Get current plot range for calculating defaults
        view_range = self.plot.getViewBox().viewRange()
        x_range = view_range[0]
        y_range = view_range[1]

        # Calculate default region: ±10% around vline (time), ±25% around hline (voltage)
        x_span = x_range[1] - x_range[0]
        y_span = y_range[1] - y_range[0]

        roi_width = x_span * 0.2  # ±10% = 20% total width
        roi_height = y_span * 0.5  # ±25% = 50% total height

        # Center ROI on trigger lines
        roi_x = vline_pos - roi_width / 2
        roi_y = hline_pos - roi_height / 2

        # Set ROI position and size
        self.zoom_roi.setPos([roi_x, roi_y])
        self.zoom_roi.setSize([roi_width, roi_height])

        # Show the ROI
        self.zoom_roi.setVisible(True)

        # Update the fill to match the ROI size
        self._update_zoom_roi_fill()

        # Emit initial position
        self.on_zoom_roi_changed()

    def hide_zoom_roi(self):
        """Hide the zoom ROI."""
        if self.zoom_roi:
            self.zoom_roi.setVisible(False)

    def reset_zoom_roi_position(self):
        """Reset the zoom ROI to its default position centered on trigger lines."""
        if not self.zoom_roi or not self.zoom_roi.isVisible():
            return

        # Get current trigger positions
        vline_pos = self.otherlines['vline'].value()
        hline_pos = self.otherlines['hline'].value()

        # Get current plot range for calculating defaults
        view_range = self.plot.getViewBox().viewRange()
        x_range = view_range[0]
        y_range = view_range[1]

        # Calculate default region: ±10% around vline (time), ±25% around hline (voltage)
        x_span = x_range[1] - x_range[0]
        y_span = y_range[1] - y_range[0]

        roi_width = x_span * 0.2  # ±10% = 20% total width
        roi_height = y_span * 0.5  # ±25% = 50% total height

        # Center ROI on trigger lines
        roi_x = vline_pos - roi_width / 2
        roi_y = hline_pos - roi_height / 2

        # Set ROI position and size
        self.zoom_roi.setPos([roi_x, roi_y])
        self.zoom_roi.setSize([roi_width, roi_height])

        # Update the fill to match the ROI size
        self._update_zoom_roi_fill()

        # Emit new position
        self.on_zoom_roi_changed()

    def _update_zoom_roi_fill(self):
        """Update the fill rectangle to match the ROI size."""
        if hasattr(self, 'zoom_roi_fill') and self.zoom_roi_fill is not None:
            size = self.zoom_roi.size()
            self.zoom_roi_fill.setRect(0, 0, size[0], size[1])

    def adjust_zoom_roi_for_downsample(self):
        """Adjust the zoom ROI width based on downsample factor."""
        if not self.zoom_roi or not self.zoom_roi.isVisible():
            return

        # Get current plot range
        view_range = self.plot.getViewBox().viewRange()
        x_range = view_range[0]
        x_span = x_range[1] - x_range[0]

        # Calculate the zoom factor based on downsample
        # When downsample < 0, we're zoomed in by factor of 2^(-downsample)
        downsample = self.state.downsample
        if downsample < 0:
            zoom_factor = pow(2, -downsample)
        else:
            zoom_factor = 1

        # Base width is 20% of view (±10% around trigger)
        # Divide by zoom factor when zoomed in
        base_width = x_span * 0.2
        roi_width = base_width / zoom_factor

        # Maintain minimum width of 5% of full window width
        min_width = x_span * 0.05
        if roi_width < min_width:
            roi_width = min_width

        # Get current ROI position and height
        current_pos = self.zoom_roi.pos()
        current_size = self.zoom_roi.size()

        # Calculate new position to keep it centered on the same point
        # Current center x
        center_x = current_pos[0] + current_size[0] / 2
        # New position with adjusted width
        new_x = center_x - roi_width / 2

        # Update ROI size and position
        self.zoom_roi.setSize([roi_width, current_size[1]])
        self.zoom_roi.setPos([new_x, current_pos[1]])

        # Update the fill
        self._update_zoom_roi_fill()

        # Emit signal to update zoom window
        self.on_zoom_roi_changed()

    def update_zoom_roi_for_time_change(self):
        """Update zoom ROI position when time axis units/range change."""
        if not self.zoom_roi or not self.zoom_roi.isVisible():
            return

        # Get new trigger positions (already updated in new units)
        vline_pos = self.otherlines['vline'].value()
        hline_pos = self.otherlines['hline'].value()

        # Get current plot range (already in new units)
        view_range = self.plot.getViewBox().viewRange()
        x_range = view_range[0]
        y_range = view_range[1]
        x_span = x_range[1] - x_range[0]
        y_span = y_range[1] - y_range[0]

        # Get current ROI size to preserve it (don't resize based on downsample)
        current_size = self.zoom_roi.size()

        # If ROI has never been sized (first time), set a default based on view
        if current_size[0] == 1 and current_size[1] == 1:
            roi_width = x_span * 0.2  # 20% of view
            roi_height = y_span * 0.5  # 50% of view
        else:
            # Preserve current ROI dimensions (in terms of absolute units)
            roi_width = current_size[0]
            roi_height = current_size[1]

        # Center ROI on trigger lines
        roi_x = vline_pos - roi_width / 2
        roi_y = hline_pos - roi_height / 2

        # Update ROI position (but not size)
        self.zoom_roi.setPos([roi_x, roi_y])
        self.zoom_roi.setSize([roi_width, roi_height])

        # Update the fill
        self._update_zoom_roi_fill()

        # Emit signal to update zoom window
        self.on_zoom_roi_changed()

    def scale_zoom_roi_width(self, scale_factor):
        """Scale the zoom ROI width by a given factor.

        Args:
            scale_factor: Factor to multiply the width by (e.g., 0.5 to halve, 2.0 to double)
        """
        if not self.zoom_roi or not self.zoom_roi.isVisible():
            return

        # Get current ROI position and size
        current_pos = self.zoom_roi.pos()
        current_size = self.zoom_roi.size()

        # Calculate new width
        new_width = current_size[0] * scale_factor

        # Calculate new position to keep ROI centered
        center_x = current_pos[0] + current_size[0] / 2
        new_x = center_x - new_width / 2

        # Update ROI (keep height the same)
        self.zoom_roi.setPos([new_x, current_pos[1]])
        self.zoom_roi.setSize([new_width, current_size[1]])

        # Update the fill
        self._update_zoom_roi_fill()

        # Emit signal to update zoom window
        self.on_zoom_roi_changed()

    def _create_trigger_arrows(self):
        """Create triangular arrow markers at the ends of trigger lines."""
        trigger_color = QColor('white')

        # vline (vertical trigger line) needs top and bottom triangles
        # Top triangle (pointing up)
        self.trigger_arrows['vline_top'] = pg.ScatterPlotItem(
            size=12, brush=pg.mkBrush(trigger_color), pen=None,
            symbol='t'  # Triangle pointing up
        )
        # Bottom triangle (pointing down)
        self.trigger_arrows['vline_bottom'] = pg.ScatterPlotItem(
            size=12, brush=pg.mkBrush(trigger_color), pen=None,
            symbol='t1'  # Triangle pointing down
        )
        self.plot.addItem(self.trigger_arrows['vline_top'])
        self.plot.addItem(self.trigger_arrows['vline_bottom'])

        # hline (horizontal trigger line) needs left and right triangles
        # Left triangle (pointing left)
        self.trigger_arrows['hline_left'] = pg.ScatterPlotItem(
            size=12, brush=pg.mkBrush(trigger_color), pen=None,
            symbol='t2'  # Triangle pointing left
        )
        # Right triangle (pointing right)
        self.trigger_arrows['hline_right'] = pg.ScatterPlotItem(
            size=12, brush=pg.mkBrush(trigger_color), pen=None,
            symbol='t3'  # Triangle pointing right
        )
        self.plot.addItem(self.trigger_arrows['hline_left'])
        self.plot.addItem(self.trigger_arrows['hline_right'])

        # Initialize positions
        self._update_trigger_arrows('vline')
        self._update_trigger_arrows('hline')

    def _update_all_trigger_arrows(self):
        """Update all trigger arrows (called on view range changes)."""
        self._update_trigger_arrows('vline')
        self._update_trigger_arrows('hline')

    def _update_trigger_arrows(self, line_name):
        """Update the position of arrow markers for trigger lines.

        Args:
            line_name: Name of the line ('vline' or 'hline')
        """
        if line_name not in self.otherlines:
            return

        line = self.otherlines[line_name]
        pos = line.value()

        # Get the actual visible view range (handles pan/zoom)
        try:
            view_range = self.plot.getViewBox().viewRange()
            min_x, max_x = view_range[0]
            min_y, max_y = view_range[1]

            # Get pixel-to-data conversion for 3-pixel offset
            pixel_size = self.plot.getViewBox().viewPixelSize()
            x_offset = 3 * pixel_size[0]
            y_offset = 3 * pixel_size[1]
        except:
            # Fallback if viewRange fails
            min_x = self.state.min_x
            max_x = self.state.max_x
            min_y = self.state.min_y
            max_y = self.state.max_y
            x_offset = 0
            y_offset = 0

        if line_name == 'vline':
            # Vertical trigger line - update top and bottom arrows
            top_arrow = self.trigger_arrows.get('vline_top')
            bottom_arrow = self.trigger_arrows.get('vline_bottom')

            if top_arrow and bottom_arrow:
                # Position at top and bottom of visible view area
                # Move slightly inward so they're visible (3 pixels inside the boundary)
                top_arrow.setData([pos], [max_y - y_offset])
                bottom_arrow.setData([pos], [min_y + y_offset])

        elif line_name == 'hline':
            # Horizontal trigger line - update left and right arrows
            left_arrow = self.trigger_arrows.get('hline_left')
            right_arrow = self.trigger_arrows.get('hline_right')

            if left_arrow and right_arrow:
                # Position at left and right of visible view area
                # Move slightly inward so they're visible (3 pixels inside the boundary)
                left_arrow.setData([min_x + x_offset], [pos])
                right_arrow.setData([max_x - x_offset], [pos])

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
        """Update the pen for the active channel's average line."""
        active_channel = self.state.activexychannel
        if active_channel in self.average_lines:
            if self.ui.persistlinesCheck.isChecked():
                pen = pg.mkPen(color='w', width=self.ui.linewidthBox.value())
            else:
                pen = self.linepens[active_channel]
            self.average_lines[active_channel].setPen(pen)

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

