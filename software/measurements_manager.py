# measurements_manager.py

import time
import math
import numpy as np
from collections import deque
from pyqtgraph.Qt import QtCore
from PyQt5.QtGui import QStandardItemModel, QStandardItem
from data_processor import format_freq
from board import gettemps


class MeasurementsManager:
    """Manages measurement display, history tracking, and histogram integration."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.state = main_window.state
        self.ui = main_window.ui
        self.processor = main_window.processor
        self.plot_manager = main_window.plot_manager
        self.controller = main_window.controller
        self.histogram_window = main_window.histogram_window

        # Initialize the table model and item tracking
        self.measurement_model = QStandardItemModel()
        self.measurement_model.setHorizontalHeaderLabels(['Measurement', 'Value', 'Avg', 'RMS'])
        self.ui.tableView.setModel(self.measurement_model)
        self.measurement_items = {}
        self.measurement_history = {}

        # Temperature caching
        self.cached_temps = (0, 0)
        self.last_temp_update_time = 0

        # Histogram tracking
        self.current_histogram_measurement = None
        self.current_histogram_unit = ""

        # Setup histogram timer
        self.histogram_timer = QtCore.QTimer()
        self.histogram_timer.timeout.connect(self.update_histogram_display)

        # Connect table selection changes
        self.ui.tableView.selectionModel().selectionChanged.connect(self.on_measurement_selection_changed)

    def on_measurement_selection_changed(self, selected, deselected):
        """Handle measurement table selection changes."""
        # Get selected indexes
        indexes = self.ui.tableView.selectionModel().selectedIndexes()

        if indexes:
            # Get the first selected row (column 0 = measurement name)
            row = indexes[0].row()
            name_item = self.measurement_model.item(row, 0)

            if name_item:
                full_text = name_item.text()
                measurement_name = full_text.split(' (')[0]  # Remove unit suffix
                # Extract unit if present
                unit = ""
                if ' (' in full_text and ')' in full_text:
                    unit = full_text.split(' (')[1].split(')')[0]

                if measurement_name in self.measurement_history:
                    self.current_histogram_measurement = measurement_name
                    self.current_histogram_unit = unit
                    self.histogram_window.position_relative_to_table(self.ui.tableView, self.ui.plot)
                    self.histogram_window.show()

                    # Get color from active channel
                    brush_color = self.plot_manager.linepens[self.state.activexychannel].color()
                    self.histogram_window.update_histogram(measurement_name,
                                                          self.measurement_history[measurement_name],
                                                          brush_color,
                                                          unit)
                    if not self.histogram_timer.isActive():
                        self.histogram_timer.start(100)  # Update at 10 Hz
        else:
            # No selection - hide histogram
            self.hide_histogram()

    def update_histogram_display(self):
        """Update the histogram window with current data."""
        if self.current_histogram_measurement and self.histogram_window.isVisible():
            if self.current_histogram_measurement in self.measurement_history:
                # Get color from active channel
                brush_color = self.plot_manager.linepens[self.state.activexychannel].color()
                self.histogram_window.update_histogram(
                    self.current_histogram_measurement,
                    self.measurement_history[self.current_histogram_measurement],
                    brush_color,
                    self.current_histogram_unit
                )

    def hide_histogram(self):
        """Hide the histogram window and stop updates."""
        self.histogram_window.hide()
        self.histogram_timer.stop()
        self.current_histogram_measurement = None

    def update_measurements_display(self):
        """Slow timer callback to update measurements in the table view without clearing it."""
        active_measurements = set()

        def _set_measurement(name, value, unit=""):
            """Helper to add or update a measurement row in the table."""
            active_measurements.add(name)
            value = round(value, 2)
            if unit != "":
                unit = " (" + unit + ")"

            # Initialize history deque if this is a new measurement
            if name not in self.measurement_history:
                self.measurement_history[name] = deque(maxlen=100)

            # Add current value to history
            self.measurement_history[name].append(value)

            # Calculate average and RMS
            history = self.measurement_history[name]
            avg_value = round(np.mean(history), 2)
            rms_value = round(np.std(history), 2)

            if name in self.measurement_items:
                # Update existing item's value, average, and RMS
                self.measurement_items[name][1].setText(str(value))
                self.measurement_items[name][0].setText(name + unit)
                self.measurement_items[name][2].setText(str(avg_value))
                self.measurement_items[name][3].setText(str(rms_value))
            else:
                # Add new row and store items
                name_item = QStandardItem(name + unit)
                value_item = QStandardItem(str(value))
                avg_item = QStandardItem(str(avg_value))
                rms_item = QStandardItem(str(rms_value))
                self.measurement_model.appendRow([name_item, value_item, avg_item, rms_item])
                self.measurement_items[name] = (name_item, value_item, avg_item, rms_item)

        if self.state.dodrawing:
            if self.ui.actionTrigger_thresh.isChecked():
                hline_val = self.plot_manager.otherlines['hline'].value()
                _set_measurement("Trig threshold", hline_val, "div")

            if self.ui.actionN_persist_lines.isChecked():
                num_persist = len(self.plot_manager.persist_lines)
                _set_measurement("Persist lines", num_persist)

            if self.ui.actionTemperatures.isChecked():
                # Only read temperatures once per second (slow USB operation)
                current_time = time.time()
                if current_time - self.last_temp_update_time >= 1.0:
                    if self.state.num_board > 0:
                        active_usb = self.controller.usbs[self.state.activeboard]
                        adctemp, boardtemp = gettemps(active_usb)
                        self.cached_temps = (adctemp, boardtemp)
                        self.last_temp_update_time = current_time

                # Always call _set_measurement with cached values to keep the row active
                if self.state.num_board > 0:
                    _set_measurement("ADC temp", self.cached_temps[0], "\u00b0C")
                    _set_measurement("Board temp", self.cached_temps[1], "\u00b0C")

            if hasattr(self.main_window, 'xydata'):
                x_data_for_analysis = self.plot_manager.lines[self.state.activexychannel].xData
                y_data_for_analysis = self.plot_manager.lines[self.state.activexychannel].yData

                if y_data_for_analysis is not None and len(y_data_for_analysis) > 0:
                    vline_val = self.plot_manager.otherlines['vline'].value()
                    measurements, fit_results = self.processor.calculate_measurements(
                        x_data_for_analysis, y_data_for_analysis, vline_val,
                        do_risetime_calc=self.ui.actionRisetime.isChecked()
                    )

                    if self.ui.actionMean.isChecked(): _set_measurement("Mean", measurements.get('Mean', 0), "mV")
                    if self.ui.actionRMS.isChecked(): _set_measurement("RMS", measurements.get('RMS', 0), "mV")
                    if self.ui.actionMinimum.isChecked(): _set_measurement("Min", measurements.get('Min', 0), "mV")
                    if self.ui.actionMaximum.isChecked(): _set_measurement("Max", measurements.get('Max', 0), "mV")
                    if self.ui.actionVpp.isChecked(): _set_measurement("Vpp", measurements.get('Vpp', 0), "mV")
                    if self.ui.actionFreq.isChecked():
                        freq = measurements.get('Freq', 0)
                        freq, unit = format_freq(freq, "Hz", False)
                        _set_measurement("Freq", freq, unit)
                    if self.ui.actionRisetime.isChecked():
                        self.plot_manager.update_risetime_fit_lines(fit_results)
                        risetime_val = measurements.get('Risetime', 0)
                        if math.isfinite(risetime_val): _set_measurement("Risetime", risetime_val, "ns")
                        if self.ui.actionRisetime_error.isChecked():
                            risetime_err_val = measurements.get('Risetime error', 0)
                            if math.isfinite(risetime_err_val):_set_measurement("Risetime error", risetime_err_val, "ns")

        # Remove stale measurements that are no longer selected
        stale_keys = list(self.measurement_items.keys() - active_measurements)

        rows_to_remove = []
        for key in stale_keys:
            # Find the item in the model by its text to avoid accessing a deleted C++ object
            items = self.measurement_model.findItems(key, QtCore.Qt.MatchStartsWith)
            if items:
                rows_to_remove.append(items[0].row())

        # Remove rows from the model, from bottom to top, to avoid index shifting issues
        for row in sorted(list(set(rows_to_remove)), reverse=True):
            self.measurement_model.removeRow(row)

        # Now, clean up the tracking dictionary and history
        for key in stale_keys:
            if key in self.measurement_items:
                del self.measurement_items[key]
            if key in self.measurement_history:
                del self.measurement_history[key]

    def adjust_table_view_geometry(self):
        """Sets the table view geometry to fill the bottom of the side panel."""
        frame_height = self.ui.frame.height()
        table_top_y = 600  # The Y coordinate where the table should start
        table_height = frame_height - table_top_y

        # Ensure the height is not negative if the window is very short
        if table_height < 50:
            table_height = 50

        # Also account for the frame's width
        frame_width = self.ui.frame.width()

        self.ui.tableView.setGeometry(
            0,            # x
            table_top_y,  # y
            frame_width,  # width
            table_height  # height
        )
