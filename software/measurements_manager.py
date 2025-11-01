# measurements_manager.py

import time
import math
import numpy as np
from collections import deque
from pyqtgraph.Qt import QtCore
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QColor
from PyQt5.QtWidgets import QPushButton, QWidget, QHBoxLayout, QLabel
from data_processor import format_freq, format_period
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

        # Track active measurements per channel: {(measurement_name, channel_key): True}
        self.active_measurements = {}

        # Track which channel/math channel is being measured
        self.selected_math_channel = None  # None means use active channel

        # Histogram tracking
        self.current_histogram_measurement = None
        self.current_histogram_unit = ""

        # Setup histogram timer
        self.histogram_timer = QtCore.QTimer()
        self.histogram_timer.timeout.connect(self.update_histogram_display)

        # Connect table selection changes
        self.ui.tableView.selectionModel().selectionChanged.connect(self.on_measurement_selection_changed)

        # Set initial header
        self.update_measurement_header()

        # Connect menu actions to add measurements
        self.connect_measurement_actions()

        # Connect bulk operation actions
        self.ui.actionAdd_all_for_this_channel.triggered.connect(self.add_all_measurements_for_channel)
        self.ui.actionClear_all_for_this_channel.triggered.connect(self.clear_all_measurements_for_channel)
        self.ui.actionClear_all_for_all_channels.triggered.connect(self.clear_all_measurements)

    def create_measurement_name_widget(self, display_name, remove_callback, color=None):
        """Create a widget combining X button and measurement name.

        Args:
            display_name: The measurement name to display
            remove_callback: Callback function when X button is clicked
            color: QColor for the button border (optional, defaults to white)

        Returns:
            QWidget containing the button and label
        """
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(5)

        # Create X button with colored border
        remove_button = QPushButton("✕")
        remove_button.setFixedSize(20, 20)

        if color is None:
            color_str = "#FFFFFF"
        else:
            color_str = color.name()

        remove_button.setStyleSheet(
            f"QPushButton {{ font-size: 14px; font-weight: bold; border: 2px solid {color_str}; }}"
        )
        remove_button.clicked.connect(remove_callback)

        # Create label for name
        label = QLabel(display_name)

        layout.addWidget(remove_button)
        layout.addWidget(label)
        layout.addStretch()

        widget.label = label  # Store reference to update text later
        widget.button = remove_button  # Store reference to update color later
        return widget

    def get_current_channel_key(self):
        """Get the current channel identifier for measurements."""
        if self.selected_math_channel is not None:
            return self.selected_math_channel
        else:
            board = self.state.activexychannel // self.state.num_chan_per_board
            chan = self.state.activexychannel % self.state.num_chan_per_board
            return f"B{board} Ch{chan}"

    def get_current_board_key(self):
        """Get the current board identifier for board-level measurements (e.g., temperature)."""
        board = self.state.activeboard
        return f"B{board}"

    def get_channel_color(self, channel_key):
        """Get the color for a given channel key.

        Args:
            channel_key: Channel identifier (e.g., "B0 Ch1", "Math1", or "B0" for board-level)

        Returns:
            QColor for the channel
        """
        if channel_key.startswith("Math"):
            # Math channel
            if channel_key in self.plot_manager.math_channel_lines:
                return self.plot_manager.math_channel_lines[channel_key].opts['pen'].color()
            else:
                return QColor('white')
        elif " " in channel_key:
            # Regular channel (format: "B0 Ch1")
            parts = channel_key.split()
            board = int(parts[0][1:])  # Remove 'B' prefix
            chan = int(parts[1][2:])  # Get channel number (remove 'Ch' prefix)
            channel_index = board * self.state.num_chan_per_board + chan
            if channel_index < len(self.plot_manager.linepens):
                return self.plot_manager.linepens[channel_index].color()
            else:
                return QColor('white')
        else:
            # Board-level measurement (format: "B0")
            board = int(channel_key[1:])  # Remove 'B' prefix
            # Use the color of channel 0 on this board
            channel_index = board * self.state.num_chan_per_board
            if channel_index < len(self.plot_manager.linepens):
                return self.plot_manager.linepens[channel_index].color()
            else:
                return QColor('white')

    def connect_measurement_actions(self):
        """Connect menu actions to toggle measurements for current channel."""
        # Per-channel measurement actions
        measurement_actions = [
            (self.ui.actionMean, "Mean"),
            (self.ui.actionRMS, "RMS"),
            (self.ui.actionMinimum, "Min"),
            (self.ui.actionMaximum, "Max"),
            (self.ui.actionVpp, "Vpp"),
            (self.ui.actionFreq, "Freq"),
            (self.ui.actionPeriod, "Period"),
            (self.ui.actionDuty_cycle, "Duty cycle"),
            (self.ui.actionPulse_width, "Pulse width"),
            (self.ui.actionRisetime, "Risetime"),  # Special: also handles Falltime
            (self.ui.actionRisetime_error, "Risetime error"),  # Special: also handles Falltime error
            (self.ui.actionN_persist_lines, "Persist lines"),  # Per-channel persist line count
        ]

        for action, name in measurement_actions:
            action.triggered.connect(lambda checked, n=name: self.toggle_measurement(n, checked))

        # Per-board measurement actions (temperatures)
        board_measurement_actions = [
            (self.ui.actionADC_temperature, "ADC temp"),
            (self.ui.actionBoard_temperature, "Board temp"),
        ]

        for action, name in board_measurement_actions:
            action.triggered.connect(lambda checked, n=name: self.toggle_board_measurement(n, checked))

        # Global measurements (Trigger threshold) are handled in update_measurements_display

    def toggle_measurement(self, measurement_name, checked):
        """Add or remove a measurement for the current channel."""
        channel_key = self.get_current_channel_key()

        # Special handling for Risetime/Falltime - determine based on edge direction
        if measurement_name in ["Risetime", "Risetime error"]:
            # Check edge direction for the active board
            if not channel_key.startswith("Math"):
                parts = channel_key.split()
                board = int(parts[0][1:])
                is_falling = self.state.fallingedge[board]
                if measurement_name == "Risetime":
                    actual_name = "Falltime" if is_falling else "Risetime"
                else:  # "Risetime error"
                    actual_name = "Falltime error" if is_falling else "Risetime error"
            else:
                # For math channels, default to Risetime
                actual_name = measurement_name
            key = (actual_name, channel_key)
        else:
            key = (measurement_name, channel_key)

        if checked:
            # Add measurement
            self.active_measurements[key] = True
        else:
            # Remove measurement
            if key in self.active_measurements:
                del self.active_measurements[key]
            # Also remove from items and history
            if key in self.measurement_items:
                # Find and remove the row by matching the widget
                name_widget = self.measurement_items[key][0]  # Index 0 is the name widget
                for row in range(self.measurement_model.rowCount()):
                    if self.ui.tableView.indexWidget(self.measurement_model.index(row, 0)) == name_widget:
                        self.measurement_model.removeRow(row)
                        break
                del self.measurement_items[key]
            if key in self.measurement_history:
                del self.measurement_history[key]

    def toggle_board_measurement(self, measurement_name, checked):
        """Add or remove a board-level measurement (e.g., temperature) for the current board."""
        board_key = self.get_current_board_key()
        key = (measurement_name, board_key)

        if checked:
            # Add measurement
            self.active_measurements[key] = True
        else:
            # Remove measurement
            if key in self.active_measurements:
                del self.active_measurements[key]
            # Also remove from items and history
            if key in self.measurement_items:
                # Find and remove the row by matching the widget
                name_widget = self.measurement_items[key][0]  # Index 0 is the name widget
                for row in range(self.measurement_model.rowCount()):
                    if self.ui.tableView.indexWidget(self.measurement_model.index(row, 0)) == name_widget:
                        self.measurement_model.removeRow(row)
                        break
                del self.measurement_items[key]
            if key in self.measurement_history:
                del self.measurement_history[key]

    def remove_measurement(self, measurement_key):
        """Remove a measurement by its key."""
        if measurement_key in self.active_measurements:
            del self.active_measurements[measurement_key]
        if measurement_key in self.measurement_items:
            # Find and remove the row by matching the widget
            name_widget = self.measurement_items[measurement_key][0]  # Index 0 is the name widget
            for row in range(self.measurement_model.rowCount()):
                if self.ui.tableView.indexWidget(self.measurement_model.index(row, 0)) == name_widget:
                    self.measurement_model.removeRow(row)
                    break
            del self.measurement_items[measurement_key]
        if measurement_key in self.measurement_history:
            del self.measurement_history[measurement_key]

        # Update menu checkbox
        measurement_name = measurement_key[0]
        self.update_menu_checkboxes()

    def remove_global_measurement(self, measurement_name):
        """Remove a global measurement by unchecking its menu item."""
        if measurement_name == "Trig threshold":
            self.ui.actionTrigger_thresh.setChecked(False)

    def add_all_measurements_for_channel(self):
        """Add all available measurements for the current channel."""
        # Manually add each measurement (setting checkbox doesn't trigger the signal)
        measurement_types = ["Mean", "RMS", "Min", "Max", "Vpp", "Freq", "Period", "Duty cycle", "Pulse width",
                             "Risetime", "Risetime error", "Persist lines"]

        for measurement_name in measurement_types:
            self.toggle_measurement(measurement_name, True)

        # Update menu checkboxes to reflect the changes
        self.update_menu_checkboxes()

        # Force an immediate update to show the measurements
        self.update_measurements_display()

    def clear_all_measurements_for_channel(self):
        """Clear all measurements for the current channel."""
        channel_key = self.get_current_channel_key()

        # Find all measurements for this channel
        measurements_to_remove = [key for key in list(self.active_measurements.keys())
                                  if key[1] == channel_key]

        # Remove each measurement
        for key in measurements_to_remove:
            if key in self.active_measurements:
                del self.active_measurements[key]
            if key in self.measurement_items:
                name_widget = self.measurement_items[key][0]
                for row in range(self.measurement_model.rowCount()):
                    if self.ui.tableView.indexWidget(self.measurement_model.index(row, 0)) == name_widget:
                        self.measurement_model.removeRow(row)
                        break
                del self.measurement_items[key]
            if key in self.measurement_history:
                del self.measurement_history[key]

        # Update menu checkboxes
        self.update_menu_checkboxes()

    def clear_all_measurements(self):
        """Clear all measurements for all channels."""
        # Clear all active measurements
        self.active_measurements.clear()

        # Clear the table
        self.measurement_model.removeRows(0, self.measurement_model.rowCount())

        # Clear tracking dictionaries
        self.measurement_items.clear()
        self.measurement_history.clear()

        # Clear global measurement checkboxes
        self.ui.actionTrigger_thresh.setChecked(False)
        self.ui.actionN_persist_lines.setChecked(False)
        self.ui.actionADC_temperature.setChecked(False)
        self.ui.actionBoard_temperature.setChecked(False)

        # Update menu checkboxes for current channel
        self.update_menu_checkboxes()

    def update_menu_checkboxes(self):
        """Update measurement menu checkboxes based on current channel's active measurements."""
        channel_key = self.get_current_channel_key()
        board_key = self.get_current_board_key()

        # Check which measurements are active for this channel
        self.ui.actionMean.setChecked((("Mean", channel_key) in self.active_measurements))
        self.ui.actionRMS.setChecked((("RMS", channel_key) in self.active_measurements))
        self.ui.actionMinimum.setChecked((("Min", channel_key) in self.active_measurements))
        self.ui.actionMaximum.setChecked((("Max", channel_key) in self.active_measurements))
        self.ui.actionVpp.setChecked((("Vpp", channel_key) in self.active_measurements))
        self.ui.actionFreq.setChecked((("Freq", channel_key) in self.active_measurements))
        self.ui.actionPeriod.setChecked((("Period", channel_key) in self.active_measurements))
        self.ui.actionDuty_cycle.setChecked((("Duty cycle", channel_key) in self.active_measurements))
        self.ui.actionPulse_width.setChecked((("Pulse width", channel_key) in self.active_measurements))
        self.ui.actionRisetime.setChecked((("Risetime", channel_key) in self.active_measurements or ("Falltime",
                                                                                                     channel_key) in self.active_measurements))
        self.ui.actionRisetime_error.setChecked((("Risetime error", channel_key) in self.active_measurements or (
            "Falltime error", channel_key) in self.active_measurements))
        self.ui.actionN_persist_lines.setChecked((("Persist lines", channel_key) in self.active_measurements))

        # Check which board-level measurements are active for this board
        self.ui.actionADC_temperature.setChecked((("ADC temp", board_key) in self.active_measurements))
        self.ui.actionBoard_temperature.setChecked((("Board temp", board_key) in self.active_measurements))

    def update_measurement_header(self):
        """Update the measurement table header and menu checkboxes."""
        # Update the menu separator text to show the current channel
        channel_key = self.get_current_channel_key()
        if channel_key.startswith("Math"):
            menu_text = f"--- For {channel_key} ---"
        else:
            # Parse the channel key to get board and channel
            parts = channel_key.split()
            board = parts[0][1:]  # Remove 'B' prefix
            chan = parts[1][2:]  # Remove 'Ch' prefix
            menu_text = f"--- For Board {board} Channel {chan} ---"

        self.ui.action_For_Board_X_Channel_Y.setText(menu_text)

        # Update menu checkboxes for current channel
        self.update_menu_checkboxes()

    def select_math_channel_for_measurement(self, math_channel_name):
        """Select a math channel for measurement display.

        Args:
            math_channel_name: Name of the math channel (e.g., 'Math1') or None for active channel
        """
        self.selected_math_channel = math_channel_name
        self.update_measurement_header()
        # Clear measurement history when switching channels
        self.measurement_history.clear()

        # Update the math window button state if it exists
        if hasattr(self.main_window, 'math_window') and self.main_window.math_window is not None:
            self.main_window.math_window.sync_measure_button_state()

    def on_measurement_selection_changed(self):
        """Handle measurement table selection changes."""
        # Get selected indexes
        indexes = self.ui.tableView.selectionModel().selectedIndexes()

        if indexes:
            # Get the first selected row (column 0 = measurement name widget)
            row = indexes[0].row()
            name_widget = self.ui.tableView.indexWidget(self.measurement_model.index(row, 0))

            if name_widget:
                # Find the measurement key by matching the name_widget
                measurement_key = None
                for key, items in self.measurement_items.items():
                    if items[0] == name_widget:  # items[0] is the name widget
                        measurement_key = key
                        break

                if measurement_key and measurement_key in self.measurement_history:
                    measurement_name, channel_key = measurement_key
                    self.current_histogram_measurement = measurement_key
                    # Extract unit from display name if present
                    full_text = name_widget.label.text()
                    unit = ""
                    # Look for last parentheses which contains unit (not channel)
                    parts = full_text.split(')')
                    if len(parts) > 2:  # Has both channel and unit
                        unit_part = parts[-2].split('(')[-1].strip()
                        if unit_part not in ["B", "Ch", "Math"]:  # Not part of channel name
                            unit = unit_part
                    self.current_histogram_unit = unit

                    self.histogram_window.position_relative_to_table(self.ui.tableView, self.ui.plot)
                    self.histogram_window.show()

                    # Get color from measurement's channel
                    brush_color = self.get_channel_color(channel_key)
                    self.histogram_window.update_histogram(
                        f"{measurement_name} ({channel_key})",
                        self.measurement_history[measurement_key],
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
                measurement_name, channel_key = self.current_histogram_measurement
                # Get color from measurement's channel
                brush_color = self.get_channel_color(channel_key)
                self.histogram_window.update_histogram(
                    f"{measurement_name} ({channel_key})",
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

        # Helper for global measurements (not tied to a specific channel)
        def _set_global_measurement(name, value, value_unit=""):
            """Helper to add or update a global measurement row."""
            key = (name, "Global")  # Use "Global" as channel_key for global measurements
            value = round(value, 3)
            display_name = name
            if value_unit != "":
                display_name += f" ({value_unit})"

            if key not in self.measurement_history:
                self.measurement_history[key] = deque(maxlen=100)

            self.measurement_history[key].append(value)
            history = self.measurement_history[key]
            avg_value = round(np.mean(history), 3)
            rms_value = round(np.std(history), 3)

            if key in self.measurement_items:
                name_widget, value_item, avg_item, rms_item = self.measurement_items[key]
                value_item.setText(f"{value:.3f}")
                name_widget.label.setText(display_name)
                avg_item.setText(f"{avg_value:.3f}")
                rms_item.setText(f"{rms_value:.3f}")
            else:
                name_item = QStandardItem("")
                value_item = QStandardItem(f"{value:.3f}")
                avg_item = QStandardItem(f"{avg_value:.3f}")
                rms_item = QStandardItem(f"{rms_value:.3f}")
                self.measurement_model.appendRow([name_item, value_item, avg_item, rms_item])

                # Create name widget with X button for global measurements
                row = self.measurement_model.rowCount() - 1
                name_widget = self.create_measurement_name_widget(display_name, lambda checked=False,
                                                                n=name: self.remove_global_measurement(n))
                self.ui.tableView.setIndexWidget(self.measurement_model.index(row, 0), name_widget)

                self.measurement_items[key] = (name_widget, value_item, avg_item, rms_item)

        def _set_measurement(measurement_key, value, value_unit=""):
            """Helper to add or update a measurement row in the table.

            Args:
                measurement_key: Tuple of (measurement_name, channel_key)
                value: The measurement value
                value_unit: Optional unit string (e.g., "mV", "ns")
            """
            measurement_name, channel_key = measurement_key
            value = round(value, 3)

            # Display name includes channel
            display_name = f"{measurement_name} ({channel_key})"
            if value_unit != "":
                display_name += f" ({value_unit})"

            # Initialize history deque if this is a new measurement
            if measurement_key not in self.measurement_history:
                self.measurement_history[measurement_key] = deque(maxlen=100)

            # Add current value to history
            self.measurement_history[measurement_key].append(value)

            # Calculate average and RMS
            history = self.measurement_history[measurement_key]
            avg_value = round(np.mean(history), 3)
            rms_value = round(np.std(history), 3)

            # Get the color for this channel
            channel_color = self.get_channel_color(channel_key)

            if measurement_key in self.measurement_items:
                # Update existing item's value, average, and RMS
                name_widget, value_item, avg_item, rms_item = self.measurement_items[measurement_key]
                value_item.setText(f"{value:.3f}")
                name_widget.label.setText(display_name)
                avg_item.setText(f"{avg_value:.3f}")
                rms_item.setText(f"{rms_value:.3f}")
                # Update button color in case channel color changed
                name_widget.button.setStyleSheet(
                    f"QPushButton {{ font-size: 14px; font-weight: bold; border: 2px solid {channel_color.name()}; }}"
                )
            else:
                # Add new row
                name_item = QStandardItem("")
                value_item = QStandardItem(f"{value:.3f}")
                avg_item = QStandardItem(f"{avg_value:.3f}")
                rms_item = QStandardItem(f"{rms_value:.3f}")

                self.measurement_model.appendRow([name_item, value_item, avg_item, rms_item])

                # Create name widget with X button
                row = self.measurement_model.rowCount() - 1
                name_widget = self.create_measurement_name_widget(
                    display_name,
                    lambda checked=False, mk=measurement_key: self.remove_measurement(mk),
                    channel_color
                )
                self.ui.tableView.setIndexWidget(self.measurement_model.index(row, 0), name_widget)

                self.measurement_items[measurement_key] = (name_widget, value_item, avg_item, rms_item)

        if not self.state.dodrawing:
            return

        # Handle global measurements (not tied to specific channel)
        if self.ui.actionTrigger_thresh.isChecked():
            hline_val = self.plot_manager.otherlines['hline'].value()
            _set_global_measurement("Trig threshold", hline_val, "div")

        # Handle temperature measurements (per-board)
        # Cache for temperature readings per board (board_index: (adc_temp, board_temp, timestamp))
        if not hasattr(self, 'board_temp_cache'):
            self.board_temp_cache = {}

        # Check if we need to read temperatures for active board measurements
        active_board_measurements = [key for key in self.active_measurements.keys()
                                      if key[0] in ["ADC temp", "Board temp"]]

        for measurement_key in active_board_measurements:
            measurement_name, board_key = measurement_key
            board_idx = int(board_key[1:])  # Extract board number from "B0", "B1", etc.

            # Only read temperatures once per second (slow USB operation)
            current_time = time.time()
            needs_update = (board_idx not in self.board_temp_cache or
                           current_time - self.board_temp_cache[board_idx][2] >= 1.0)

            if needs_update and board_idx < self.state.num_board:
                usb = self.controller.usbs[board_idx]
                adctemp, boardtemp = gettemps(usb)
                self.board_temp_cache[board_idx] = (adctemp, boardtemp, current_time)

        # Remove global measurements that are no longer checked
        global_measurements_to_remove = []
        for key in self.measurement_items.keys():
            if key[1] == "Global":
                name = key[0]
                if name == "Trig threshold" and not self.ui.actionTrigger_thresh.isChecked():
                    global_measurements_to_remove.append(key)

        # Remove "Persist lines" per-channel measurements if checkbox is unchecked
        if not self.ui.actionN_persist_lines.isChecked():
            persist_measurements_to_remove = [key for key in self.measurement_items.keys()
                                              if key[0] == "Persist lines" and key[1].startswith("CH")]
            global_measurements_to_remove.extend(persist_measurements_to_remove)

        for key in global_measurements_to_remove:
            if key in self.measurement_items:
                name_widget = self.measurement_items[key][0]
                for row in range(self.measurement_model.rowCount()):
                    if self.ui.tableView.indexWidget(self.measurement_model.index(row, 0)) == name_widget:
                        self.measurement_model.removeRow(row)
                        break
                del self.measurement_items[key]
            if key in self.measurement_history:
                del self.measurement_history[key]

        # Cache fit_results for active channel to avoid recalculating
        cached_active_channel_fit_results = None
        current_channel_key = self.get_current_channel_key()

        # Group measurements by channel to avoid redundant calculations
        measurements_by_channel = {}
        for measurement_key in self.active_measurements.keys():
            measurement_name, channel_key = measurement_key
            if channel_key not in measurements_by_channel:
                measurements_by_channel[channel_key] = []
            measurements_by_channel[channel_key].append(measurement_name)

        # Cache to store calculated measurements per channel (to avoid recalculating)
        channel_measurements_cache = {}
        channel_fit_results_cache = {}

        # Process each active measurement
        for measurement_key in list(self.active_measurements.keys()):
            measurement_name, channel_key = measurement_key

            # Handle board-level measurements (temperatures)
            if measurement_name in ["ADC temp", "Board temp"]:
                board_idx = int(channel_key[1:])  # Extract board number from "B0", "B1", etc.
                if board_idx in self.board_temp_cache:
                    if measurement_name == "ADC temp":
                        _set_measurement(measurement_key, self.board_temp_cache[board_idx][0], "\u00b0C")
                    elif measurement_name == "Board temp":
                        _set_measurement(measurement_key, self.board_temp_cache[board_idx][1], "\u00b0C")
                continue  # Skip normal channel processing

            # Special case: "Persist lines" measurement doesn't need waveform data
            if measurement_name == "Persist lines":
                # Extract channel index from channel_key (format: "B0 Ch1")
                if " " in channel_key:
                    parts = channel_key.split()
                    board = int(parts[0][1:])  # Remove 'B' prefix
                    chan = int(parts[1][2:])  # Get channel number (remove 'Ch' prefix)
                    channel_index = board * self.state.num_chan_per_board + chan

                    # Get persist lines count for this channel
                    persist_lines = self.plot_manager.persist_lines_per_channel.get(channel_index, [])
                    num_persist = len(persist_lines)
                    _set_measurement(measurement_key, num_persist)
                continue  # Skip normal channel processing

            # Determine which channel's data to use
            if channel_key.startswith("Math"):
                # Math channel measurement
                if channel_key not in self.plot_manager.math_channel_lines:
                    continue  # Math channel no longer exists
                x_data = self.plot_manager.math_channel_lines[channel_key].xData
                y_data = self.plot_manager.math_channel_lines[channel_key].yData
            elif " " in channel_key:
                # Regular channel measurement (format: "B0 Ch1")
                parts = channel_key.split()
                board = int(parts[0][1:])  # Remove 'B' prefix
                chan = int(parts[1][2:])  # Get channel number (remove 'Ch' prefix)
                channel_index = board * self.state.num_chan_per_board + chan

                if channel_index >= len(self.plot_manager.lines):
                    continue  # Invalid channel

                x_data = self.plot_manager.lines[channel_index].xData
                y_data = self.plot_manager.lines[channel_index].yData
            else:
                # Unknown format, skip
                continue

            if y_data is None or len(y_data) == 0:
                continue

            # Check if we've already calculated measurements for this channel
            if channel_key not in channel_measurements_cache:
                # Calculate measurements based on type
                vline_val = self.plot_manager.otherlines['vline'].value()

                # Determine what measurements are needed for this channel
                channel_measurement_types = measurements_by_channel[channel_key]
                needs_risetime = any(m in ["Risetime", "Falltime", "Risetime error", "Falltime error"]
                                    for m in channel_measurement_types)
                needs_freq = any(m in ["Freq", "Period"] for m in channel_measurement_types)

                # For regular channels, pass channel_index; for math channels, use None (defaults to activexychannel)
                measurement_channel_index = channel_index if not channel_key.startswith("Math") else None

                measurements, fit_results = self.processor.calculate_measurements(
                    x_data, y_data, vline_val,
                    do_risetime_calc=needs_risetime,
                    use_edge_fit=self.ui.actionEdge_fit_method.isChecked(),
                    channel_index=measurement_channel_index,
                    needs_freq=needs_freq
                )

                # Cache results for this channel
                channel_measurements_cache[channel_key] = measurements
                channel_fit_results_cache[channel_key] = fit_results

                # Cache fit_results if this is a risetime/falltime measurement for the active channel
                if needs_risetime and channel_key == current_channel_key and fit_results is not None:
                    cached_active_channel_fit_results = fit_results
            else:
                # Reuse cached measurements for this channel
                measurements = channel_measurements_cache[channel_key]
                fit_results = channel_fit_results_cache.get(channel_key)

            # Set the measurement value based on type
            if measurement_name == "Mean":
                _set_measurement(measurement_key, measurements.get('Mean', 0), "mV")
            elif measurement_name == "RMS":
                _set_measurement(measurement_key, measurements.get('RMS', 0), "mV")
            elif measurement_name == "Min":
                _set_measurement(measurement_key, measurements.get('Min', 0), "mV")
            elif measurement_name == "Max":
                _set_measurement(measurement_key, measurements.get('Max', 0), "mV")
            elif measurement_name == "Vpp":
                _set_measurement(measurement_key, measurements.get('Vpp', 0), "mV")
            elif measurement_name == "Freq":
                freq = measurements.get('Freq', 0)
                freq, unit = format_freq(freq, "Hz", False)
                _set_measurement(measurement_key, freq, unit)
            elif measurement_name == "Period":
                freq = measurements.get('Freq', 0)
                if freq > 0:
                    period_ns = 1e9 / freq  # Convert frequency (Hz) to period (ns)
                    period, unit = format_period(period_ns, "s", False)
                    _set_measurement(measurement_key, period, unit)
                else:
                    _set_measurement(measurement_key, 0, "ns")
            elif measurement_name == "Duty cycle":
                duty_cycle = measurements.get('Duty cycle', 0)
                _set_measurement(measurement_key, duty_cycle, "%")
            elif measurement_name == "Pulse width":
                pulse_width_ns = measurements.get('Pulse width', 0)
                pulse_width, unit = format_period(pulse_width_ns, "s", False)
                _set_measurement(measurement_key, pulse_width, unit)
            elif measurement_name in ["Risetime", "Falltime"]:
                val = measurements.get(measurement_name, 0)
                if math.isfinite(val):
                    _set_measurement(measurement_key, val, "ns")
            elif measurement_name in ["Risetime error", "Falltime error"]:
                val = measurements.get(measurement_name, 0)
                if math.isfinite(val):
                    _set_measurement(measurement_key, val, "ns")

        # Update fit lines if risetime is being measured for active channel
        if hasattr(self.main_window, 'xydata') and self.state.num_board > 0:
            if (("Risetime", current_channel_key) in self.active_measurements or
                    ("Falltime", current_channel_key) in self.active_measurements):
                # Use cached fit_results if available (avoids recalculating)
                if cached_active_channel_fit_results is not None:
                    self.plot_manager.update_risetime_fit_lines(cached_active_channel_fit_results)
                else:
                    # If not cached, calculate now (shouldn't happen in normal operation)
                    x_data = self.plot_manager.lines[self.state.activexychannel].xData
                    y_data = self.plot_manager.lines[self.state.activexychannel].yData
                    if y_data is not None and len(y_data) > 0:
                        vline_val = self.plot_manager.otherlines['vline'].value()
                        _, fit_results = self.processor.calculate_measurements(
                            x_data, y_data, vline_val,
                            do_risetime_calc=True,
                            use_edge_fit=self.ui.actionEdge_fit_method.isChecked(),
                            channel_index=self.state.activexychannel
                        )
                        self.plot_manager.update_risetime_fit_lines(fit_results)
            else:
                self.plot_manager.update_risetime_fit_lines(None)

        # Remove measurements that are no longer in active_measurements (exclude global measurements)
        stale_keys = [key for key in self.measurement_items.keys()
                      if key not in self.active_measurements.keys() and key[1] != "Global"]

        rows_to_remove = []
        for key in stale_keys:
            if key in self.measurement_items:
                # Find the row by the name widget
                name_widget = self.measurement_items[key][0]
                for row in range(self.measurement_model.rowCount()):
                    if self.ui.tableView.indexWidget(self.measurement_model.index(row, 0)) == name_widget:
                        rows_to_remove.append(row)
                        break

        # Remove rows from bottom to top to avoid index shifting
        for row in sorted(set(rows_to_remove), reverse=True):
            self.measurement_model.removeRow(row)

        # Clean up tracking dictionaries
        for key in stale_keys:
            if key in self.measurement_items:
                del self.measurement_items[key]
            if key in self.measurement_history:
                del self.measurement_history[key]

    def adjust_table_view_geometry(self):
        """Sets the table view geometry to fill the bottom with the side panel."""
        frame_height = self.ui.frame.height()
        table_top_y = 600  # The Y coordinate where the table should start
        table_height = frame_height - table_top_y

        # Ensure the height is not negative if the window is very short
        if table_height < 50:
            table_height = 50

        # Also account for the frame's width
        frame_width = self.ui.frame.width()

        self.ui.tableView.setGeometry(
            0,  # x
            table_top_y,  # y
            frame_width-10,  # width
            table_height  # height
        )
