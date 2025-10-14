# cursor_manager.py
"""Manages cursor lines and readout display for measurements."""

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore
from PyQt5.QtGui import QColor
import numpy as np


class CursorManager:
    """Manages cursor lines and value readouts."""

    def __init__(self, plot, state, linepens, ui=None, otherlines=None, lines=None):
        """Initialize cursor manager.

        Args:
            plot: The pyqtgraph PlotItem
            state: The application state object
            linepens: List of pens for each channel (for color matching)
            ui: The UI object (for accessing actionTime_relative, actionSnap_to_waveform)
            otherlines: Dictionary of other plot lines (for accessing vline position)
            lines: List of plot lines (for snapping to waveform data)
        """
        self.plot = plot
        self.state = state
        self.linepens = linepens
        self.ui = ui
        self.otherlines = otherlines
        self.lines = lines
        self.cursor_lines = {}
        self.cursor_labels = {}
        self.cursor_arrows = {}  # Store arrow markers for cursor line ends
        self._snapping_in_progress = False  # Flag to prevent infinite recursion

    def setup_cursors(self):
        """Initialize cursor lines and labels."""
        # White cursors with width 2
        cursor_color = QColor('gray')
        cursor_pen = pg.mkPen(color=cursor_color, width=2.0, style=QtCore.Qt.DotLine)
        hover_pen = pg.mkPen(color=cursor_color, width=3.0, style=QtCore.Qt.DotLine)

        # Create two vertical cursors (for time measurements)
        # Position at 10% from edges
        x_range = self.state.max_x - self.state.min_x
        self.cursor_lines['t1'] = pg.InfiniteLine(pos=self.state.min_x + x_range * 0.1, angle=90, movable=True,
                                                   pen=cursor_pen, hoverPen=hover_pen)
        self.cursor_lines['t2'] = pg.InfiniteLine(pos=self.state.max_x - x_range * 0.1, angle=90, movable=True,
                                                   pen=cursor_pen, hoverPen=hover_pen)

        # Create two horizontal cursors (for voltage measurements)
        self.cursor_lines['v1'] = pg.InfiniteLine(pos=-3, angle=0, movable=True,
                                                   pen=cursor_pen, hoverPen=hover_pen)
        self.cursor_lines['v2'] = pg.InfiniteLine(pos=3, angle=0, movable=True,
                                                   pen=cursor_pen, hoverPen=hover_pen)

        # Add cursors to plot (initially hidden)
        for cursor in self.cursor_lines.values():
            self.plot.addItem(cursor)
            cursor.setVisible(False)

        # Create triangle markers at cursor line ends
        self._create_cursor_arrows()

        # Connect signals - snap first, then update readout
        self.cursor_lines['t1'].sigPositionChanged.connect(lambda: self.snap_cursor_to_waveform('t1', 'v1'))
        self.cursor_lines['t2'].sigPositionChanged.connect(lambda: self.snap_cursor_to_waveform('t2', 'v2'))

        # Update readout when any cursor moves
        for cursor in self.cursor_lines.values():
            cursor.sigPositionChanged.connect(self.update_cursor_readout)

        # Update arrow positions when cursors move - connect explicitly to avoid closure issues
        self.cursor_lines['t1'].sigPositionChanged.connect(lambda: self._update_cursor_arrows('t1'))
        self.cursor_lines['t2'].sigPositionChanged.connect(lambda: self._update_cursor_arrows('t2'))
        self.cursor_lines['v1'].sigPositionChanged.connect(lambda: self._update_cursor_arrows('v1'))
        self.cursor_lines['v2'].sigPositionChanged.connect(lambda: self._update_cursor_arrows('v2'))
        # Update arrow positions and text positions when view changes (pan/zoom)
        self.plot.getViewBox().sigRangeChanged.connect(self._update_all_cursor_arrows)
        self.plot.getViewBox().sigRangeChanged.connect(self._update_text_positions)

        # Create text labels for cursor readouts
        self.cursor_labels['readout'] = pg.TextItem(anchor=(0, 0), color='w')
        self.plot.addItem(self.cursor_labels['readout'])
        self.cursor_labels['readout'].setVisible(False)

        # Position the readout in top-left corner
        self.cursor_labels['readout'].setPos(self.state.min_x, self.state.max_y - 0.5)

        # Create text label for trigger threshold
        self.cursor_labels['trigger_thresh'] = pg.TextItem(anchor=(0, 1), color='w')
        self.plot.addItem(self.cursor_labels['trigger_thresh'])
        self.cursor_labels['trigger_thresh'].setVisible(False)

    def _create_cursor_arrows(self):
        """Create triangular arrow markers at the ends of cursor lines."""
        cursor_color = QColor('gray')

        # Create arrows for each cursor line
        # Vertical cursors (t1, t2) need top and bottom triangles
        for cursor_name in ['t1', 't2']:
            # Top triangle (pointing up)
            self.cursor_arrows[f'{cursor_name}_top'] = pg.ScatterPlotItem(
                size=12, brush=pg.mkBrush(cursor_color), pen=None,
                symbol='t'  # Triangle pointing up
            )
            # Bottom triangle (pointing down)
            self.cursor_arrows[f'{cursor_name}_bottom'] = pg.ScatterPlotItem(
                size=12, brush=pg.mkBrush(cursor_color), pen=None,
                symbol='t1'  # Triangle pointing down
            )
            self.plot.addItem(self.cursor_arrows[f'{cursor_name}_top'])
            self.plot.addItem(self.cursor_arrows[f'{cursor_name}_bottom'])
            self.cursor_arrows[f'{cursor_name}_top'].setVisible(False)
            self.cursor_arrows[f'{cursor_name}_bottom'].setVisible(False)

        # Horizontal cursors (v1, v2) need left and right triangles
        for cursor_name in ['v1', 'v2']:
            # Left triangle (pointing left)
            self.cursor_arrows[f'{cursor_name}_left'] = pg.ScatterPlotItem(
                size=12, brush=pg.mkBrush(cursor_color), pen=None,
                symbol='t2'  # Triangle pointing left
            )
            # Right triangle (pointing right)
            self.cursor_arrows[f'{cursor_name}_right'] = pg.ScatterPlotItem(
                size=12, brush=pg.mkBrush(cursor_color), pen=None,
                symbol='t3'  # Triangle pointing right
            )
            self.plot.addItem(self.cursor_arrows[f'{cursor_name}_left'])
            self.plot.addItem(self.cursor_arrows[f'{cursor_name}_right'])
            self.cursor_arrows[f'{cursor_name}_left'].setVisible(False)
            self.cursor_arrows[f'{cursor_name}_right'].setVisible(False)

    def _update_all_cursor_arrows(self):
        """Update all cursor arrows (called on view range changes)."""
        for cursor_name in self.cursor_lines.keys():
            self._update_cursor_arrows(cursor_name)

    def _update_text_positions(self):
        """Update text label positions when view changes (pan/zoom)."""
        if self.cursor_lines['t1'].isVisible():
            self._update_cursor_readout_position()
        if self.ui and hasattr(self.ui, 'actionTrigger_info') and self.ui.actionTrigger_info.isChecked():
            self._update_trigger_info_position()

    def _update_cursor_readout_position(self):
        """Update cursor readout position based on visible view range."""
        try:
            view_range = self.plot.getViewBox().viewRange()
            min_x, max_x = view_range[0]
            min_y, max_y = view_range[1]
        except:
            min_x = self.state.min_x
            max_x = self.state.max_x
            min_y = self.state.min_y
            max_y = self.state.max_y

        # Position in top-left corner of visible area
        self.cursor_labels['readout'].setPos(min_x + 0.1*(max_x - min_x), max_y - 0.1)

    def _update_trigger_info_position(self):
        """Update trigger info position based on visible view range."""
        try:
            view_range = self.plot.getViewBox().viewRange()
            min_x, max_x = view_range[0]
            min_y, max_y = view_range[1]
        except:
            min_x = self.state.min_x
            max_x = self.state.max_x
            min_y = self.state.min_y
            max_y = self.state.max_y

        # Position in lower-left corner of visible area
        self.cursor_labels['trigger_thresh'].setPos(
            min_x + 0.1*(max_x - min_x),
            min_y + 0.1
        )

    def _update_cursor_arrows(self, cursor_name):
        """Update the position of arrow markers for a specific cursor.

        Args:
            cursor_name: Name of the cursor ('t1', 't2', 'v1', or 'v2')
        """
        if cursor_name not in self.cursor_lines:
            return

        cursor = self.cursor_lines[cursor_name]
        pos = cursor.value()

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

        if cursor_name in ['t1', 't2']:
            # Vertical cursor - update top and bottom arrows
            top_arrow = self.cursor_arrows.get(f'{cursor_name}_top')
            bottom_arrow = self.cursor_arrows.get(f'{cursor_name}_bottom')

            if top_arrow and bottom_arrow:
                # Position at top and bottom of visible view area
                # Move slightly inward so they're visible (3 pixels inside the boundary)
                top_arrow.setData([pos], [max_y - y_offset])
                bottom_arrow.setData([pos], [min_y + y_offset])

        elif cursor_name in ['v1', 'v2']:
            # Horizontal cursor - update left and right arrows
            left_arrow = self.cursor_arrows.get(f'{cursor_name}_left')
            right_arrow = self.cursor_arrows.get(f'{cursor_name}_right')

            if left_arrow and right_arrow:
                # Position at left and right of visible view area
                # Move slightly inward so they're visible (3 pixels inside the boundary)
                left_arrow.setData([min_x + x_offset], [pos])
                right_arrow.setData([max_x - x_offset], [pos])

    def update_cursor_readout(self):
        """Update cursor value display when cursors are moved."""
        if not self.cursor_lines['t1'].isVisible():
            return

        # Get cursor positions
        t1_pos = self.cursor_lines['t1'].value()
        t2_pos = self.cursor_lines['t2'].value()
        v1_pos = self.cursor_lines['v1'].value()
        v2_pos = self.cursor_lines['v2'].value()

        # Calculate deltas
        delta_t = abs(t2_pos - t1_pos)
        delta_v = abs(v2_pos - v1_pos)

        # Calculate frequency from time delta (convert to seconds first)
        freq = 0
        freq_unit = "Hz"
        if delta_t > 0:
            # Convert time units to seconds
            delta_t_seconds = delta_t * self.state.nsunits / 1e9
            freq = 1.0 / delta_t_seconds

            # Format frequency with appropriate units
            if freq >= 1e9:
                freq = freq / 1e9
                freq_unit = "GHz"
            elif freq >= 1e6:
                freq = freq / 1e6
                freq_unit = "MHz"
            elif freq >= 1e3:
                freq = freq / 1e3
                freq_unit = "kHz"

        # Get voltage conversion factor for active channel
        if self.state.num_board > 0 and len(self.state.VperD) > 0:
            v_per_div = self.state.VperD[self.state.activexychannel]
            v1_volts = v1_pos * v_per_div
            v2_volts = v2_pos * v_per_div
            delta_v_volts = delta_v * v_per_div
            # Get active channel color
            active_color = self.linepens[self.state.activexychannel].color().name()
        else:
            v1_volts = v2_volts = delta_v_volts = 0
            active_color = "#ffffff"

        # Check if time should be displayed relative to trigger
        show_relative = False
        if self.ui and self.otherlines and hasattr(self.ui, 'actionTime_relative'):
            show_relative = self.ui.actionTime_relative.isChecked()

        # Format time cursor positions
        if show_relative and 'vline' in self.otherlines:
            vline_pos = self.otherlines['vline'].value()
            t1_rel = t1_pos - vline_pos
            t2_rel = t2_pos - vline_pos
            # Format with explicit + or - sign
            t1_str = f"{t1_rel:+.2f} {self.state.units}"
            t2_str = f"{t2_rel:+.2f} {self.state.units}"
        else:
            t1_str = f"{t1_pos:.2f} {self.state.units}"
            t2_str = f"{t2_pos:.2f} {self.state.units}"

        # Format the readout text with current time units and colored voltage values
        # Use &nbsp; for spacing and <br> for line breaks in HTML
        readout_text = f"T1: {t1_str}&nbsp;&nbsp;&nbsp;&nbsp;T2: {t2_str}&nbsp;&nbsp;&nbsp;&nbsp;ΔT: {delta_t:.2f} {self.state.units}&nbsp;&nbsp;&nbsp;&nbsp;Freq: {freq:.3f} {freq_unit}<br>"
        readout_text += f"V1: {v1_pos:.3f} div <span style='color:{active_color}'>({v1_volts:.3f} V)</span>&nbsp;&nbsp;&nbsp;&nbsp;V2: {v2_pos:.3f} div <span style='color:{active_color}'>({v2_volts:.3f} V)</span>&nbsp;&nbsp;&nbsp;&nbsp;ΔV: {delta_v:.3f} div <span style='color:{active_color}'>({delta_v_volts:.3f} V)</span>"

        self.cursor_labels['readout'].setHtml(readout_text)

        # Update readout position to stay in visible area (use actual view range for pan/zoom)
        self._update_cursor_readout_position()

    def update_trigger_threshold_text(self):
        """Update trigger info display when hline/vline moves or action is toggled."""
        # Check if the action is enabled
        if not self.ui or not hasattr(self.ui, 'actionTrigger_info'):
            return

        if not self.ui.actionTrigger_info.isChecked():
            self.cursor_labels['trigger_thresh'].setVisible(False)
            return

        # Get hline and vline positions
        if not self.otherlines or 'hline' not in self.otherlines or 'vline' not in self.otherlines:
            return

        hline_pos = self.otherlines['hline'].value()
        vline_pos = self.otherlines['vline'].value()

        # Convert to voltage (mV) using VperD for active channel
        if self.state.num_board > 0 and len(self.state.VperD) > 0:
            v_per_div = self.state.VperD[self.state.activexychannel]
            threshold_mV = hline_pos * v_per_div * 1000
        else:
            threshold_mV = 0

        # Get active board and channel numbers
        active_board = self.state.activeboard
        num_chan_per_board = self.state.num_chan_per_board
        active_channel = self.state.activexychannel % num_chan_per_board

        # Calculate trigger time from vline position (trigger time is at vline)
        # The vline represents the trigger point in time
        trigger_time_ns = vline_pos * self.state.nsunits

        # Calculate trigger time with delay
        # trigger_delay is in units where 1 = downsamplefactor*40/samplerate nanoseconds
        trigger_delay_value = self.state.trigger_delay[active_board]
        trigger_delay_ns = trigger_delay_value * self.state.downsamplefactor * 40.0 / self.state.samplerate
        trigger_time_with_delay_ns = trigger_time_ns - trigger_delay_ns

        # Format with appropriate units
        from data_processor import format_period
        trig_time_val, trig_time_unit = format_period(trigger_time_ns, "s", False)
        trig_delay_time_val, trig_delay_time_unit = format_period(trigger_time_with_delay_ns, "s", False)

        # Format the text with multiple lines
        info_lines = [
            f"Trigger info (Board {active_board} Channel {active_channel}):",
            f"  Threshold: {threshold_mV:.1f} mV",
            f"  Trigger time: {trig_time_val:.2f} {trig_time_unit}"]
        if trigger_delay_value>0: info_lines.append(f"  Trigger time - delay: {trig_delay_time_val:.2f} {trig_delay_time_unit}")
        info_text = "<br>".join(info_lines)
        self.cursor_labels['trigger_thresh'].setHtml(info_text)

        # Position in lower left corner (use actual view range for pan/zoom)
        self._update_trigger_info_position()

        self.cursor_labels['trigger_thresh'].setVisible(True)

    def snap_cursor_to_waveform(self, t_cursor_name, v_cursor_name):
        """Snap cursor to nearest waveform point.

        Args:
            t_cursor_name: Name of the time cursor ('t1' or 't2')
            v_cursor_name: Name of the voltage cursor ('v1' or 'v2')
        """
        # Prevent infinite recursion
        if self._snapping_in_progress:
            return

        # Check if snap is enabled
        if not self.ui or not hasattr(self.ui, 'actionSnap_to_waveform'):
            return
        if not self.ui.actionSnap_to_waveform.isChecked():
            return

        # Check if we have lines and a valid active channel
        if not self.lines or self.state.num_board < 1:
            return
        if self.state.activexychannel >= len(self.lines):
            return

        # Get waveform data from active channel
        active_line = self.lines[self.state.activexychannel]
        x_data = active_line.xData
        y_data = active_line.yData

        if x_data is None or y_data is None or len(x_data) == 0:
            return

        # Get current time cursor position
        t_pos = self.cursor_lines[t_cursor_name].value()

        # Find nearest x point on waveform
        idx = np.argmin(np.abs(x_data - t_pos))
        snap_x = x_data[idx]
        snap_y = y_data[idx]

        # Set flag to prevent recursion
        self._snapping_in_progress = True

        # Snap both cursors to the waveform point
        self.cursor_lines[t_cursor_name].setValue(snap_x)
        self.cursor_lines[v_cursor_name].setValue(snap_y)

        # Clear flag
        self._snapping_in_progress = False

    def show_cursors(self, visible):
        """Show or hide cursor lines and labels."""
        if visible:
            # Reset cursor positions to 10% from edges when showing
            x_range = self.state.max_x - self.state.min_x
            y_range = self.state.max_y - self.state.min_y

            self.cursor_lines['t1'].setValue(self.state.min_x + x_range * 0.1)
            self.cursor_lines['t2'].setValue(self.state.max_x - x_range * 0.1)
            self.cursor_lines['v1'].setValue(self.state.min_y + y_range * 0.3)
            self.cursor_lines['v2'].setValue(self.state.max_y - y_range * 0.3)

        for cursor in self.cursor_lines.values():
            cursor.setVisible(visible)
        self.cursor_labels['readout'].setVisible(visible)

        # Show/hide arrows
        for arrow in self.cursor_arrows.values():
            arrow.setVisible(visible)

        if visible:
            # Update arrow positions for all cursors
            for cursor_name in self.cursor_lines.keys():
                self._update_cursor_arrows(cursor_name)
            # Snap cursors to waveform if snap option is enabled
            if self.ui and hasattr(self.ui, 'actionSnap_to_waveform') and self.ui.actionSnap_to_waveform.isChecked():
                self.snap_all_cursors()
            self.update_cursor_readout()

    def update_active_channel(self):
        """Update cursor display when active channel changes."""
        if self.cursor_lines and self.cursor_lines['t1'].isVisible():
            self.update_cursor_readout()

    def snap_all_cursors(self):
        """Snap all cursors to waveform when snap is toggled on."""
        if not self.cursor_lines or not self.cursor_lines['t1'].isVisible():
            return

        # Snap T1/V1
        self.snap_cursor_to_waveform('t1', 'v1')
        # Snap T2/V2
        self.snap_cursor_to_waveform('t2', 'v2')

    def adjust_cursor_positions(self):
        """Adjust cursor positions to keep them within the visible window."""
        if not self.cursor_lines:
            return

        min_x = self.state.min_x
        max_x = self.state.max_x
        min_y = self.state.min_y
        max_y = self.state.max_y

        # Calculate 10% margins
        x_margin = (max_x - min_x) * 0.1
        y_margin = (max_y - min_y) * 0.1

        # Check if either time cursor is outside the allowed range
        t1_pos = self.cursor_lines['t1'].value()
        t2_pos = self.cursor_lines['t2'].value()

        t1_outside = t1_pos < (min_x + x_margin) or t1_pos > (max_x - x_margin)
        t2_outside = t2_pos < (min_x + x_margin) or t2_pos > (max_x - x_margin)

        # If either time cursor is outside, reset both to default positions
        if t1_outside or t2_outside:
            self.cursor_lines['t1'].setValue(min_x + x_margin)
            self.cursor_lines['t2'].setValue(max_x - x_margin)

        # Adjust voltage cursors (horizontal lines)
        v1_pos = self.cursor_lines['v1'].value()
        v2_pos = self.cursor_lines['v2'].value()

        if v1_pos < min_y:
            self.cursor_lines['v1'].setValue(min_y + y_margin)
        elif v1_pos > max_y:
            self.cursor_lines['v1'].setValue(max_y - y_margin)

        if v2_pos < min_y:
            self.cursor_lines['v2'].setValue(min_y + y_margin)
        elif v2_pos > max_y:
            self.cursor_lines['v2'].setValue(max_y - y_margin)

        # Update arrow positions for all cursors (plot area may have changed)
        for cursor_name in self.cursor_lines.keys():
            self._update_cursor_arrows(cursor_name)

        # Update readout position and values
        if self.cursor_lines['t1'].isVisible():
            self.update_cursor_readout()

        # Update trigger threshold text position
        self.update_trigger_threshold_text()
