# zoom_window.py

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets
from PyQt5.QtGui import QColor, QPen
from PyQt5.QtCore import pyqtSignal
from plot_manager import add_secondary_axis
from heatmap_manager import HeatmapManager


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
        self.plot.showGrid(x=True, y=True, alpha=0.5)

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

        # Enable mouse tracking for cross-window pointer (but keep mouse enabled=False to prevent pan/zoom)
        self.plot_widget.setMouseTracking(True)
        self.plot.scene().sigMouseMoved.connect(self.on_mouse_moved)

        # Track window activation state
        self.is_active_window = False
        self.crosshairs_enabled = False  # Track if crosshairs should be shown

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
        runtpen = pg.mkPen(color=(255, 165, 0), width=1.0, style=QtCore.Qt.DashLine)  # Orange for runt threshold
        self.trigger_lines['vline'] = pg.InfiniteLine(pos=0.0, angle=90, movable=False, pen=dashedpen)
        self.trigger_lines['hline'] = pg.InfiniteLine(pos=0.0, angle=0, movable=False, pen=dashedpen)
        self.trigger_lines['hline_delta'] = pg.InfiniteLine(pos=0.0, angle=0, movable=False, pen=dashedpen)  # First threshold (hline+delta)
        self.trigger_lines['hline_runt'] = pg.InfiniteLine(pos=0.0, angle=0, movable=False, pen=runtpen)  # Runt threshold
        self.trigger_lines['vline_tot'] = pg.InfiniteLine(pos=0.0, angle=90, movable=False, pen=runtpen)  # TOT line
        self.trigger_lines['vline_holdoff'] = pg.InfiniteLine(pos=0.0, angle=90, movable=False, pen=runtpen)  # Holdoff line
        self.plot.addItem(self.trigger_lines['vline'])
        self.plot.addItem(self.trigger_lines['hline'])
        self.plot.addItem(self.trigger_lines['hline_delta'])
        self.plot.addItem(self.trigger_lines['hline_runt'])
        self.plot.addItem(self.trigger_lines['vline_tot'])
        self.plot.addItem(self.trigger_lines['vline_holdoff'])
        # Initially hidden - will be shown when main plot shows them
        self.trigger_lines['vline'].setVisible(False)
        self.trigger_lines['hline'].setVisible(False)
        self.trigger_lines['hline_delta'].setVisible(False)
        self.trigger_lines['hline_runt'].setVisible(False)
        self.trigger_lines['vline_tot'].setVisible(False)
        self.trigger_lines['vline_holdoff'].setVisible(False)

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

        # Create mouse pointer indicator (small crosshair - 20 pixels total)
        pointer_pen = pg.mkPen(color=QColor(255, 255, 0, 180), width=2, style=QtCore.Qt.SolidLine)  # Semi-transparent yellow
        self.mouse_pointer_vline = self.plot.plot(pen=pointer_pen, skipFiniteCheck=True)
        self.mouse_pointer_hline = self.plot.plot(pen=pointer_pen, skipFiniteCheck=True)
        self.mouse_pointer_vline.setVisible(False)
        self.mouse_pointer_hline.setVisible(False)
        self.mouse_pointer_x = 0.0
        self.mouse_pointer_y = 0.0

        # Create plot lines for each channel (will be created dynamically)
        self.channel_lines = {}  # {channel_index: plot_line}
        self.math_channel_lines = {}  # {math_name: plot_line}
        self.reference_lines = {}  # {channel_index: plot_line} for physical channel references
        self.math_reference_lines = {}  # {math_name: plot_line} for math channel references
        self.peak_max_lines = {}  # {channel_index: plot_line} for peak max lines
        self.peak_min_lines = {}  # {channel_index: plot_line} for peak min lines
        self.persist_lines = {}  # {channel_index: [plot_line, ...]} for persist lines
        self.average_persist_lines = {}  # {channel_index: plot_line} for average persist lines

        # Create heatmap manager for this zoom window
        # We'll adjust bin counts to match main plot's bin size
        self.heatmap_manager = HeatmapManager(self.plot, self.state)
        self.main_plot_manager = plot_manager  # Store reference to get main plot's bin size

        # Override heatmap's _init_heatmap_for_channel to use zoom ROI ranges
        self._patch_heatmap_manager()

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

        # Update heatmap bin counts to match main plot's bin size
        self._update_heatmap_bins()

    def _patch_heatmap_manager(self):
        """Patch heatmap manager to use zoom window's view range for both x and y."""
        # Store the original methods
        original_init = self.heatmap_manager._init_heatmap_for_channel
        original_regenerate = self.heatmap_manager.regenerate

        # Create a wrapper that uses view range for y as well
        def patched_init(line_idx):
            # Call original to set up most things
            original_init(line_idx)

            # Override the ranges to use actual view range for both x and y
            view_range = self.plot.getViewBox().viewRange()
            view_min_x, view_max_x = view_range[0]
            view_min_y, view_max_y = view_range[1]

            self.heatmap_manager.persist_heatmap_ranges[line_idx] = (
                (view_min_x, view_max_x),  # X from current view
                (view_min_y, view_max_y)   # Y from current view (not state!)
            )

        # Wrapper for regenerate to use view range for y
        def patched_regenerate(line_idx, persist_lines):
            # Update ranges to use current view before regenerating
            view_range = self.plot.getViewBox().viewRange()
            view_min_x, view_max_x = view_range[0]
            view_min_y, view_max_y = view_range[1]

            # Temporarily override state to set proper ranges
            self.heatmap_manager.persist_heatmap_ranges[line_idx] = (
                (view_min_x, view_max_x),  # X from current view
                (view_min_y, view_max_y)   # Y from current view (not state!)
            )

            # Call original regenerate
            original_regenerate(line_idx, persist_lines)

        # Replace the methods
        self.heatmap_manager._init_heatmap_for_channel = patched_init
        self.heatmap_manager.regenerate = patched_regenerate

    def _update_heatmap_bins(self):
        """Calculate heatmap bin counts for zoom window to match main plot's bin size."""
        if not self.main_plot_manager or not self.zoom_x_range or not self.zoom_y_range:
            return

        # Get main plot's view range
        main_view_range = self.main_plot_manager.plot.getViewBox().viewRange()
        main_x_min, main_x_max = main_view_range[0]
        main_y_min, main_y_max = main_view_range[1]

        # Get main plot's bin counts
        main_bins_x = self.main_plot_manager.heatmap_manager.get_heatmap_bins_x()
        main_bins_y = self.main_plot_manager.heatmap_manager.heatmap_bins_y

        # Calculate main plot's bin sizes
        main_x_range = main_x_max - main_x_min
        main_y_range = main_y_max - main_y_min
        if main_x_range == 0 or main_y_range == 0:
            return

        bin_size_x = main_x_range / main_bins_x
        bin_size_y = main_y_range / main_bins_y

        # Calculate zoom window's range
        zoom_x_min, zoom_x_max = self.zoom_x_range
        zoom_y_min, zoom_y_max = self.zoom_y_range
        zoom_x_range = zoom_x_max - zoom_x_min
        zoom_y_range = zoom_y_max - zoom_y_min

        # Calculate how many bins we need in the zoom window to maintain the same bin size
        zoom_bins_x = max(1, int(zoom_x_range / bin_size_x))
        zoom_bins_y = max(1, int(zoom_y_range / bin_size_y))

        # Update the zoom heatmap manager's bin counts
        self.heatmap_manager._base_heatmap_bins_x = zoom_bins_x
        self.heatmap_manager.heatmap_bins_y = zoom_bins_y

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

            # Hide main line if any persistence visualization is enabled
            has_persistence = (
                self.state.persist_time[ch_idx] > 0 and
                (self.state.persist_lines_enabled[ch_idx] or
                 self.state.persist_avg_enabled[ch_idx] or
                 self.state.persist_heatmap_enabled[ch_idx])
            )

            # Show and update line data (hide if persistence is on)
            self.channel_lines[ch_idx].setVisible(not has_persistence)
            self.channel_lines[ch_idx].setData(x=x_data, y=y_data, skipFiniteCheck=True)

        # Update math channels
        if math_results:
            for math_name, (x_data, y_data) in math_results.items():
                if x_data is None or y_data is None or len(x_data) == 0:
                    continue

                # Check if this math channel should be displayed
                math_def = self._get_math_channel_definition(math_name)
                is_displayed = math_def.get('displayed', True) if math_def else True

                # Get width from source channel (ch1)
                width = 2  # Default
                if math_def:
                    ch1_idx = math_def.get('ch1')
                    if not isinstance(ch1_idx, str) and ch1_idx < len(self.plot_manager.linepens):
                        # Source is a regular channel - use its current width
                        width = self.plot_manager.linepens[ch1_idx].width()
                    elif isinstance(ch1_idx, str) and ch1_idx.startswith("Ref"):
                        # Source is a reference - look up the original channel and use its current width
                        try:
                            ref_num = int(ch1_idx[3:])  # Extract number from "Ref0", "Ref1", etc.
                            if (self.parent_window and hasattr(self.parent_window, 'reference_data') and
                                ref_num in self.parent_window.reference_data and
                                ref_num < len(self.plot_manager.linepens)):
                                # Use the current width of the channel this reference came from
                                width = self.plot_manager.linepens[ref_num].width()
                            else:
                                width = math_def.get('width', 2)
                        except (ValueError, IndexError):
                            width = math_def.get('width', 2)
                    else:
                        # Source is another math channel or unknown - use default width
                        width = math_def.get('width', 2)

                # Create line if it doesn't exist
                if math_name not in self.math_channel_lines:
                    # Get color from math channel definition
                    color = self._get_math_channel_color(math_name)
                    # Use dashed pen for math channels, like in main window
                    pen = pg.mkPen(color=color, width=width, style=QtCore.Qt.DashLine)

                    self.math_channel_lines[math_name] = self.plot.plot(
                        pen=pen,
                        skipFiniteCheck=True,
                        connect="finite"
                    )
                else:
                    # Update pen to match current color and source channel width
                    color = self._get_math_channel_color(math_name)
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

            # Get stored width from reference (or use current channel width if not stored)
            stored_width = ref_data.get('width', None)

            if ch_idx not in self.reference_lines:
                # Create reference line with semi-transparent pen matching channel color
                if ch_idx < len(self.plot_manager.linepens):
                    color = QColor(self.plot_manager.linepens[ch_idx].color())
                    color.setAlphaF(0.5)
                    # Use stored width or current channel width
                    width = stored_width if stored_width is not None else self.plot_manager.linepens[ch_idx].width()
                    pen = pg.mkPen(color=color, width=width)
                else:
                    color = QColor('white')
                    color.setAlphaF(0.5)
                    width = stored_width if stored_width is not None else 1
                    pen = pg.mkPen(color=color, width=width)

                self.reference_lines[ch_idx] = self.plot.plot(
                    pen=pen,
                    skipFiniteCheck=True,
                    connect="finite"
                )
            else:
                # Update the pen to match current channel color (but use stored width)
                if ch_idx < len(self.plot_manager.linepens):
                    color = QColor(self.plot_manager.linepens[ch_idx].color())
                    color.setAlphaF(0.5)
                    # Use stored width or current channel width
                    width = stored_width if stored_width is not None else self.plot_manager.linepens[ch_idx].width()
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
                from scipy.signal import resample_poly, resample
                import numpy as np
                if self.state.polyphase_upsampling_enabled:
                    # Use polyphase resampling to reduce ringing artifacts
                    y_resampled = resample_poly(y_data, doresamp_to_use, 1)
                    # Reconstruct time axis with proper spacing to avoid time shift
                    dt_orig = (x_data[-1] - x_data[0]) / (len(x_data) - 1)
                    dt_new = dt_orig / doresamp_to_use
                    x_resampled = x_data[0] + np.arange(len(y_resampled)) * dt_new
                else:
                    # Use FFT-based resampling
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

            # Use stored width from reference, or current math channel width if not stored
            width = ref_data.get('width', math_def.get('width', 2) if math_def else 2)

            if math_name not in self.math_reference_lines:
                # Create reference line with semi-transparent pen matching math channel color
                pen = pg.mkPen(color=ref_color, width=width, style=QtCore.Qt.DashLine)

                self.math_reference_lines[math_name] = self.plot.plot(
                    pen=pen,
                    skipFiniteCheck=True,
                    connect="finite"
                )
            else:
                # Update the pen to match current math channel color (but use stored width)
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
                from scipy.signal import resample_poly, resample
                import numpy as np
                if self.state.polyphase_upsampling_enabled:
                    # Use polyphase resampling to reduce ringing artifacts
                    y_resampled = resample_poly(y_data, doresamp_to_use, 1)
                    # Reconstruct time axis with proper spacing to avoid time shift
                    dt_orig = (x_data[-1] - x_data[0]) / (len(x_data) - 1)
                    dt_new = dt_orig / doresamp_to_use
                    x_resampled = x_data[0] + np.arange(len(y_resampled)) * dt_new
                else:
                    # Use FFT-based resampling
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

        # Update trigger lines (vline, hline, hline_delta, hline_runt, vline_tot)
        if hasattr(main_plot_manager, 'otherlines'):
            if 'vline' in main_plot_manager.otherlines:
                vline = main_plot_manager.otherlines['vline']
                self.trigger_lines['vline'].setPos(vline.value())
                self.trigger_lines['vline'].setVisible(vline.isVisible())

            if 'hline' in main_plot_manager.otherlines:
                hline = main_plot_manager.otherlines['hline']
                self.trigger_lines['hline'].setPos(hline.value())
                self.trigger_lines['hline'].setVisible(hline.isVisible())

            if 'hline_delta' in main_plot_manager.otherlines:
                hline_delta = main_plot_manager.otherlines['hline_delta']
                self.trigger_lines['hline_delta'].setPos(hline_delta.value())
                self.trigger_lines['hline_delta'].setVisible(hline_delta.isVisible())

            if 'hline_runt' in main_plot_manager.otherlines:
                hline_runt = main_plot_manager.otherlines['hline_runt']
                self.trigger_lines['hline_runt'].setPos(hline_runt.value())
                self.trigger_lines['hline_runt'].setVisible(hline_runt.isVisible())

            if 'vline_tot' in main_plot_manager.otherlines:
                vline_tot = main_plot_manager.otherlines['vline_tot']
                self.trigger_lines['vline_tot'].setPos(vline_tot.value())
                self.trigger_lines['vline_tot'].setVisible(vline_tot.isVisible())

            if 'vline_holdoff' in main_plot_manager.otherlines:
                vline_holdoff = main_plot_manager.otherlines['vline_holdoff']
                self.trigger_lines['vline_holdoff'].setPos(vline_holdoff.value())
                self.trigger_lines['vline_holdoff'].setVisible(vline_holdoff.isVisible())

        # Update cursor lines (t1, t2, v1, v2)
        if hasattr(main_plot_manager, 'cursor_manager') and main_plot_manager.cursor_manager:
            cursor_mgr = main_plot_manager.cursor_manager
            if hasattr(cursor_mgr, 'cursor_lines'):
                for cursor_name in ['t1', 't2', 'v1', 'v2']:
                    if cursor_name in cursor_mgr.cursor_lines and cursor_name in self.cursor_lines:
                        main_cursor = cursor_mgr.cursor_lines[cursor_name]
                        self.cursor_lines[cursor_name].setPos(main_cursor.value())
                        self.cursor_lines[cursor_name].setVisible(main_cursor.isVisible())

    def update_peak_detect_lines(self, main_plot_manager):
        """Update the zoom window's peak detect lines to match the main plot.

        Args:
            main_plot_manager: The main window's plot manager to get peak detect data from
        """
        if not main_plot_manager:
            return

        # Iterate through all channels that have peak detect enabled
        for ch_idx, enabled in main_plot_manager.peak_detect_enabled.items():
            if enabled and ch_idx in main_plot_manager.peak_max_line:
                # Get pen from main plot manager
                if ch_idx < len(main_plot_manager.linepens):
                    base_pen = main_plot_manager.linepens[ch_idx]
                    color = base_pen.color()
                    width = base_pen.width()
                    peak_pen = pg.mkPen(color=color, width=width, style=QtCore.Qt.DotLine)
                else:
                    peak_pen = pg.mkPen(color='w', width=1, style=QtCore.Qt.DotLine)

                # Create peak lines if they don't exist
                if ch_idx not in self.peak_max_lines:
                    self.peak_max_lines[ch_idx] = self.plot.plot(pen=peak_pen, skipFiniteCheck=True, connect="finite")
                    self.peak_min_lines[ch_idx] = self.plot.plot(pen=peak_pen, skipFiniteCheck=True, connect="finite")
                else:
                    # Update pen color for existing peak lines
                    self.peak_max_lines[ch_idx].setPen(peak_pen)
                    self.peak_min_lines[ch_idx].setPen(peak_pen)

                # Update peak line data if available
                if (ch_idx in main_plot_manager.peak_x_data and
                    ch_idx in main_plot_manager.peak_max_data and
                    ch_idx in main_plot_manager.peak_min_data):
                    x_data = main_plot_manager.peak_x_data[ch_idx]
                    max_data = main_plot_manager.peak_max_data[ch_idx]
                    min_data = main_plot_manager.peak_min_data[ch_idx]

                    if x_data is not None and max_data is not None and min_data is not None:
                        self.peak_max_lines[ch_idx].setData(x=x_data, y=max_data, skipFiniteCheck=True)
                        self.peak_min_lines[ch_idx].setData(x=x_data, y=min_data, skipFiniteCheck=True)
                        self.peak_max_lines[ch_idx].setVisible(True)
                        self.peak_min_lines[ch_idx].setVisible(True)
            else:
                # Hide peak lines if peak detect is disabled
                if ch_idx in self.peak_max_lines:
                    self.peak_max_lines[ch_idx].setVisible(False)
                    self.peak_min_lines[ch_idx].setVisible(False)

    def update_persist_lines(self, main_plot_manager):
        """Update the zoom window's persist lines, heatmaps, and average persist lines to match the main plot.

        Args:
            main_plot_manager: The main window's plot manager to get persist data from
        """
        if not main_plot_manager:
            return

        # Update heatmap bin counts to match main plot's bin size
        self._update_heatmap_bins()

        # Clear all existing persist lines
        for ch_idx in list(self.persist_lines.keys()):
            for persist_line in self.persist_lines[ch_idx]:
                self.plot.removeItem(persist_line)
            self.persist_lines[ch_idx] = []

        # Clear all existing heatmaps
        for ch_idx in list(self.heatmap_manager.persist_heatmap_items.keys()):
            self.heatmap_manager.clear_channel(ch_idx)

        # Add persist lines from main plot manager
        if hasattr(main_plot_manager, 'persist_lines_per_channel'):
            for ch_idx, persist_deque in main_plot_manager.persist_lines_per_channel.items():
                if ch_idx not in self.persist_lines:
                    self.persist_lines[ch_idx] = []

                # Convert deque to list
                persist_list = list(persist_deque)

                # Only draw the last 16 persist lines for performance (matching main plot)
                # But use all 100 for heatmap
                max_visible_persist = 16
                lines_to_draw = persist_list[-max_visible_persist:] if len(persist_list) > max_visible_persist else persist_list

                # Iterate through the visible persist items only
                for item_data in lines_to_draw:
                    # Unpack the 5-tuple format (persist_item, timestamp, line_idx, x_data, y_data)
                    persist_item = item_data[0]
                    x_data = item_data[3] if len(item_data) >= 4 else None
                    y_data = item_data[4] if len(item_data) >= 5 else None

                    # Fallback to getData if x_data/y_data not in tuple (backwards compatibility)
                    if x_data is None or y_data is None:
                        x_data, y_data = persist_item.getData()

                    if x_data is not None and y_data is not None:
                        # Get the pen from the persist item to maintain the same alpha
                        pen = persist_item.opts['pen']

                        # Create a new persist line in the zoom window with the same pen
                        zoom_persist_line = self.plot.plot(x=x_data, y=y_data, pen=pen,
                                                          skipFiniteCheck=True, connect="finite")
                        # Show persist lines only if heatmap is disabled
                        is_heatmap_enabled = self.state.persist_heatmap_enabled[ch_idx]
                        zoom_persist_line.setVisible(persist_item.isVisible() and not is_heatmap_enabled)
                        self.persist_lines[ch_idx].append(zoom_persist_line)

                # Regenerate heatmap if enabled for this channel (uses ALL persist lines, not just 16)
                if self.state.persist_heatmap_enabled[ch_idx]:
                    # Sync smoothing settings from main plot manager
                    if hasattr(main_plot_manager, 'heatmap_manager'):
                        self.heatmap_manager.heatmap_smoothing_sigma = main_plot_manager.heatmap_manager.heatmap_smoothing_sigma
                    # Regenerate heatmap from all persist lines (full buffer of up to 100)
                    self.heatmap_manager.regenerate(ch_idx, persist_list)

        # Update average persist lines
        if hasattr(main_plot_manager, 'average_lines'):
            # Remove average persist lines that no longer exist in main plot
            for ch_idx in list(self.average_persist_lines.keys()):
                if ch_idx not in main_plot_manager.average_lines:
                    self.plot.removeItem(self.average_persist_lines[ch_idx])
                    del self.average_persist_lines[ch_idx]

            # Update or create average persist lines
            for ch_idx, avg_line in main_plot_manager.average_lines.items():
                x_data, y_data = avg_line.getData()
                if x_data is not None and y_data is not None and len(x_data) > 0:
                    # Get the pen from the main average line
                    pen = avg_line.opts['pen']

                    # Create or update the average persist line
                    if ch_idx not in self.average_persist_lines:
                        self.average_persist_lines[ch_idx] = self.plot.plot(
                            x=x_data, y=y_data, pen=pen,
                            skipFiniteCheck=True, connect="finite"
                        )
                    else:
                        self.average_persist_lines[ch_idx].setData(x=x_data, y=y_data, skipFiniteCheck=True)
                        self.average_persist_lines[ch_idx].setPen(pen)

                    # Match visibility to main plot
                    self.average_persist_lines[ch_idx].setVisible(avg_line.isVisible())
                else:
                    # Main plot's average line has no data - clear the zoom window's line
                    if ch_idx in self.average_persist_lines:
                        self.average_persist_lines[ch_idx].clear()

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

        # Remove persist lines
        for persist_list in self.persist_lines.values():
            for line in persist_list:
                self.plot.removeItem(line)
        self.persist_lines.clear()

        # Remove average persist lines
        for line in self.average_persist_lines.values():
            self.plot.removeItem(line)
        self.average_persist_lines.clear()

    def closeEvent(self, event):
        """Called when window is closed - emit signal and update state."""
        self.window_closed.emit()
        super().closeEvent(event)

    def on_mouse_moved(self, pos):
        """Handle mouse movement in zoom window - update crosshair if this window is active."""
        if not self.is_active_window or not self.plot_manager:
            return

        # Map scene position to view coordinates
        view_pos = self.plot.getViewBox().mapSceneToView(pos)
        x_zoom = view_pos.x()
        y_zoom = view_pos.y()

        # Get the zoom window's full view bounds (not just the ROI)
        view_range = self.plot.getViewBox().viewRange()
        view_x_min, view_x_max = view_range[0]
        view_y_min, view_y_max = view_range[1]

        # Check if mouse is within the zoom window's visible area
        if view_x_min <= x_zoom <= view_x_max and view_y_min <= y_zoom <= view_y_max:
            # Always update crosshair in zoom window
            self.update_crosshair_position(x_zoom, y_zoom, True)

            # Only update main window crosshair if within ROI bounds
            if self.zoom_x_range and self.zoom_y_range:
                x_min, x_max = self.zoom_x_range
                y_min, y_max = self.zoom_y_range
                within_roi = x_min <= x_zoom <= x_max and y_min <= y_zoom <= y_max

                if hasattr(self.plot_manager, 'update_crosshair_position'):
                    self.plot_manager.update_crosshair_position(x_zoom, y_zoom, within_roi)
            return

        # Mouse is outside zoom window view - hide crosshair in both windows
        self.update_crosshair_position(0, 0, False)
        if hasattr(self.plot_manager, 'update_crosshair_position'):
            self.plot_manager.update_crosshair_position(0, 0, False)

    def update_crosshair_position(self, x_pos, y_pos, visible):
        """Update the crosshair position (20 pixels long).

        Args:
            x_pos: X position in plot coordinates
            y_pos: Y position in plot coordinates
            visible: Whether the crosshair should be visible
        """
        self.mouse_pointer_x = x_pos
        self.mouse_pointer_y = y_pos

        # Only show if both visible flag is True AND crosshairs are enabled
        if visible and self.crosshairs_enabled:
            # Calculate 20 pixels in data coordinates (10 pixels each direction)
            view_range = self.plot.getViewBox().viewRange()
            view_rect = self.plot.getViewBox().sceneBoundingRect()

            if view_rect.width() > 0 and view_rect.height() > 0:
                # Pixels to data units
                x_range = view_range[0][1] - view_range[0][0]
                y_range = view_range[1][1] - view_range[1][0]
                pixels_to_x = x_range / view_rect.width()
                pixels_to_y = y_range / view_rect.height()

                # 10 pixels in each direction
                half_cross_x = 10 * pixels_to_x
                half_cross_y = 10 * pixels_to_y

                # Vertical line (constant x, varying y)
                self.mouse_pointer_vline.setData(
                    x=[x_pos, x_pos],
                    y=[y_pos - half_cross_y, y_pos + half_cross_y],
                    skipFiniteCheck=True
                )

                # Horizontal line (varying x, constant y)
                self.mouse_pointer_hline.setData(
                    x=[x_pos - half_cross_x, x_pos + half_cross_x],
                    y=[y_pos, y_pos],
                    skipFiniteCheck=True
                )

        self.mouse_pointer_vline.setVisible(visible and self.crosshairs_enabled)
        self.mouse_pointer_hline.setVisible(visible and self.crosshairs_enabled)

    def set_crosshairs_enabled(self, enabled):
        """Set whether crosshairs should be shown.

        Args:
            enabled: True to show crosshairs, False to hide them
        """
        self.crosshairs_enabled = enabled
        # If disabling, immediately hide the crosshair
        if not enabled:
            self.mouse_pointer_vline.setVisible(False)
            self.mouse_pointer_hline.setVisible(False)

    def enterEvent(self, event):
        """Called when mouse enters the zoom window."""
        self.is_active_window = True
        # Also notify plot manager that zoom window is now active
        if self.plot_manager and hasattr(self.plot_manager, 'set_zoom_window_active'):
            self.plot_manager.set_zoom_window_active(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Called when mouse leaves the zoom window."""
        self.is_active_window = False
        # Notify plot manager that zoom window is no longer active
        if self.plot_manager and hasattr(self.plot_manager, 'set_zoom_window_active'):
            self.plot_manager.set_zoom_window_active(False)
        super().leaveEvent(event)
