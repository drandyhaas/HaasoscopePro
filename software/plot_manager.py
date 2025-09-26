# plot_manager.py

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets
from PyQt5.QtGui import QColor, QPen
import numpy as np
import time
from collections import deque
import matplotlib.cm as cm
from scipy.signal import resample
from scipy.interpolate import interp1d
from utils import add_secondary_axis

# #############################################################################
# PlotManager Class
# #############################################################################

class PlotManager(pg.QtCore.QObject):
    """Manages all plotting and UI visual elements using pyqtgraph."""
    # Signals to notify MainWindow of user interaction with the plot
    vline_dragged_signal = pg.QtCore.Signal(float)
    hline_dragged_signal = pg.QtCore.Signal(float)

    def __init__(self, ui, state):
        super().__init__()
        self.ui = ui
        self.state = state
        self.plot = self.ui.plot
        self.lines = []
        self.linepens = []
        self.otherlines = {}  # For trigger lines, fit lines etc.
        self.average_line = None
        self.right_axis = None
        self.nlines = state.num_board * state.num_chan_per_board
        self.current_vline_pos = 0.0

        # Persistence attributes
        self.max_persist_lines = 16
        self.persist_time = 0
        self.persist_lines = deque(maxlen=self.max_persist_lines)
        self.persist_timer = QtCore.QTimer()
        self.persist_timer.timeout.connect(self.update_persist_effect)

    def setup_plots(self):
        """Initializes the plot area, lines, pens, and axes."""
        self.plot.setBackground(QColor('black'))
        self.plot.setLabel('bottom', "Time (ns)")
        self.plot.setLabel('left', "Voltage (divisions)")
        self.plot.getAxis("left").setTickSpacing(1, .1)
        self.plot.setMenuEnabled(False)  # Disables the right-click context menu
        self.set_grid(self.ui.actionGrid.isChecked())

        # Create lines for each channel
        colors = cm.rainbow(np.linspace(1.0, 0.1, self.nlines))
        for i in range(self.nlines):
            c = QColor.fromRgbF(*colors[i])
            pen = pg.mkPen(color=c)
            line = self.plot.plot(pen=pen, name=f"Channel {i}", skipFiniteCheck=True, connect="finite")
            self.lines.append(line)
            self.linepens.append(pen)

        # Trigger and fit lines
        dashedpen = pg.mkPen(color="w", width=1.0, style=QtCore.Qt.DashLine)
        hoverpen = pg.mkPen(color="w", width=2.0, style=QtCore.Qt.DashLine)
        self.otherlines['vline'] = pg.InfiniteLine(pos=0.0, angle=90, movable=True, pen=dashedpen, hoverPen=hoverpen)
        self.otherlines['hline'] = pg.InfiniteLine(pos=0.0, angle=0, movable=True, pen=dashedpen, hoverPen=hoverpen)
        self.plot.addItem(self.otherlines['vline'])
        self.plot.addItem(self.otherlines['hline'])
        self.otherlines['vline'].sigDragged.connect(self.on_vline_dragged)
        self.otherlines['hline'].sigPositionChanged.connect(self.on_hline_dragged)

        # Risetime fit lines (initially invisible)
        fit_pen = pg.mkPen(color="w", width=1.0, style=QtCore.Qt.DotLine)
        for i in range(3):
            line = self.plot.plot([0], [0], pen=fit_pen, name=f"fitline_{i}")
            line.setVisible(False)
            self.otherlines[f'fit_{i}'] = line

        # Persistence average line
        self.average_line = self.plot.plot(pen=pg.mkPen(color='w', width=1), name="persist_avg")
        self.average_line.setVisible(self.ui.persistavgCheck.isChecked())

        # Secondary Y-Axis
        if self.state.num_board > 0:
            self.right_axis = add_secondary_axis(
                plot_item=self.plot,
                conversion_func=lambda val: val * self.state.VperD[self.state.activexychannel],
                text='Voltage', units='V', color="w"
            )
            self.right_axis.setWidth(w=40)

        self.time_changed()

    def update_plots(self, xy_data, xydatainterleaved):
        """Updates all visible waveform plots with new data."""
        if not self.state.dodrawing:
            return

        for li in range(self.nlines):
            xdatanew, ydatanew = None, None
            if not self.state.dointerleaved[li // 2]:
                xdatanew, ydatanew = xy_data[li][0].copy(), xy_data[li][1].copy()
            else:
                if li % 4 == 0:
                    # Combine data from the two interleaved boards
                    primary_data = xy_data[li][1]
                    secondary_data = xy_data[li + self.state.num_chan_per_board][1]
                    xydatainterleaved[li // 2][1][0::2] = primary_data
                    xydatainterleaved[li // 2][1][1::2] = secondary_data

                    # Create a regularly spaced x-axis and interpolate
                    x_interleaved = xydatainterleaved[li // 2][0]
                    y_interleaved = xydatainterleaved[li // 2][1]
                    xdatanew = np.linspace(x_interleaved.min(), x_interleaved.max(), len(x_interleaved))
                    f_int = interp1d(x_interleaved, y_interleaved, kind='linear', bounds_error=False, fill_value=0.0)
                    ydatanew = f_int(xdatanew)

            if xdatanew is not None:
                # Resample for smooth zooming if enabled
                if self.state.doresamp and self.state.downsample < 0:
                    ydatanew, xdatanew = resample(ydatanew, len(xdatanew) * self.state.doresamp, t=xdatanew)

                # Update the plot item
                self.lines[li].setData(xdatanew, ydatanew)

                # Handle persistence for the active channel
                if li == self.state.activexychannel and self.persist_time > 0 and self.ui.chanonCheck.isChecked():
                    self._add_to_persistence(xdatanew, ydatanew, li)

        self.update_persist_average()

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
        self.plot.setRange(xRange=(state.min_x, state.max_x), yRange=(state.min_y, state.max_y), padding=0.00)

        self.draw_trigger_lines()

    def draw_trigger_lines(self):
        """Draws the horizontal and vertical trigger lines on the plot."""
        state = self.state
        vline_pos = 4 * 10 * (state.triggerpos + 1.0) * (state.downsamplefactor / state.nsunits / state.samplerate)
        self.otherlines['vline'].setValue(vline_pos)
        hline_pos = (state.triggerlevel - 127) * state.yscale * 256
        self.otherlines['hline'].setValue(hline_pos)
        self.current_vline_pos = vline_pos

    ### Persistence Methods ###
    def set_persistence(self, value):
        self.persist_time = 50 * pow(2, value) if value > 0 else 0
        if self.persist_time > 0:
            self.persist_timer.start(50)
        else:
            self.persist_timer.stop()
            self.clear_persist()
        self.ui.persistText.setText(f"{self.persist_time / 1000.0} s")

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
            self.average_line.setData(common_x_axis, y_average)

    def clear_persist(self):
        for item, _, _ in list(self.persist_lines):
            self.plot.removeItem(item)
        self.persist_lines.clear()
        self.average_line.clear()

    ### UI Control Methods ###
    def set_line_width(self, width):
        for pen in self.linepens:
            pen.setWidth(width)
        # Manually trigger redraw for all lines
        for i, line in enumerate(self.lines):
            line.setPen(self.linepens[i])
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

    def on_hline_dragged(self, line):
        self.hline_dragged_signal.emit(line.value())

    def update_right_axis(self):
        if not self.right_axis: return
        state = self.state
        active_pen = QPen(self.linepens[state.activexychannel])
        active_pen.setWidth(1)
        self.right_axis.setPen(active_pen)
        self.right_axis.setTextPen(color=active_pen.color())
        self.right_axis.setLabel(text=f"Voltage Ch {state.selectedchannel}", units='V')
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