# math_channels_window.py
"""Window for creating and managing math channel operations."""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                             QPushButton, QListWidget, QLabel, QGroupBox)
from PyQt5.QtCore import Qt, pyqtSignal
import numpy as np


class MathChannelsWindow(QWidget):
    """Window for creating mathematical operations between channels."""

    # Signal emitted when math channels are updated
    math_channels_changed = pyqtSignal()

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.state = main_window.state

        # Storage for math channel definitions
        # Each entry: {'name': 'Math1', 'ch1': 0, 'ch2': 1, 'operation': '-'}
        self.math_channels = []

        self.setWindowTitle("Math Channels")
        self.setGeometry(100, 100, 400, 500)

        self.setup_ui()

    def setup_ui(self):
        """Setup the UI layout."""
        layout = QVBoxLayout()

        # --- Channel Selection Group ---
        selection_group = QGroupBox("Create Math Channel")
        selection_layout = QVBoxLayout()

        # Channel A selector
        ch_a_layout = QHBoxLayout()
        ch_a_layout.addWidget(QLabel("Channel A:"))
        self.channel_a_combo = QComboBox()
        ch_a_layout.addWidget(self.channel_a_combo)
        selection_layout.addLayout(ch_a_layout)

        # Operation selector
        op_layout = QHBoxLayout()
        op_layout.addWidget(QLabel("Operation:"))
        self.operation_combo = QComboBox()
        self.operation_combo.addItems(['-', '+', '*', '/'])
        op_layout.addWidget(self.operation_combo)
        selection_layout.addLayout(op_layout)

        # Channel B selector
        ch_b_layout = QHBoxLayout()
        ch_b_layout.addWidget(QLabel("Channel B:"))
        self.channel_b_combo = QComboBox()
        ch_b_layout.addWidget(self.channel_b_combo)
        selection_layout.addLayout(ch_b_layout)

        # Result preview label
        self.preview_label = QLabel("Result: CH? - CH?")
        self.preview_label.setAlignment(Qt.AlignCenter)
        selection_layout.addWidget(self.preview_label)

        # Add button
        self.add_button = QPushButton("Add Math Channel")
        self.add_button.clicked.connect(self.add_math_channel)
        selection_layout.addWidget(self.add_button)

        selection_group.setLayout(selection_layout)
        layout.addWidget(selection_group)

        # --- Active Math Channels List ---
        list_group = QGroupBox("Active Math Channels")
        list_layout = QVBoxLayout()

        self.math_list = QListWidget()
        list_layout.addWidget(self.math_list)

        # Remove button
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self.remove_math_channel)
        list_layout.addWidget(self.remove_button)

        list_group.setLayout(list_layout)
        layout.addWidget(list_group)

        self.setLayout(layout)

        # Connect signals for preview update
        self.channel_a_combo.currentIndexChanged.connect(self.update_preview)
        self.channel_b_combo.currentIndexChanged.connect(self.update_preview)
        self.operation_combo.currentIndexChanged.connect(self.update_preview)

    def update_channel_list(self):
        """Update the available channels in the combo boxes."""
        self.channel_a_combo.clear()
        self.channel_b_combo.clear()

        num_channels = self.state.num_board * self.state.num_chan_per_board

        for i in range(num_channels):
            board = i // self.state.num_chan_per_board
            chan = i % self.state.num_chan_per_board
            channel_name = f"Board {board} CH{chan}"
            self.channel_a_combo.addItem(channel_name, i)
            self.channel_b_combo.addItem(channel_name, i)

        self.update_preview()

    def update_preview(self):
        """Update the preview label showing what the math channel will be."""
        ch_a = self.channel_a_combo.currentData()
        ch_b = self.channel_b_combo.currentData()
        op = self.operation_combo.currentText()

        if ch_a is not None and ch_b is not None:
            ch_a_text = self.channel_a_combo.currentText()
            ch_b_text = self.channel_b_combo.currentText()
            self.preview_label.setText(f"Result: {ch_a_text} {op} {ch_b_text}")

    def add_math_channel(self):
        """Add a new math channel to the list."""
        ch_a = self.channel_a_combo.currentData()
        ch_b = self.channel_b_combo.currentData()
        op = self.operation_combo.currentText()

        if ch_a is None or ch_b is None:
            return

        # Create a unique name for this math channel
        math_name = f"Math{len(self.math_channels) + 1}"

        # Create the math channel definition
        math_def = {
            'name': math_name,
            'ch1': ch_a,
            'ch2': ch_b,
            'operation': op
        }

        self.math_channels.append(math_def)

        # Update the list display
        ch_a_text = self.channel_a_combo.currentText()
        ch_b_text = self.channel_b_combo.currentText()
        display_text = f"{math_name}: {ch_a_text} {op} {ch_b_text}"
        self.math_list.addItem(display_text)

        # Emit signal to update plots
        self.math_channels_changed.emit()

    def remove_math_channel(self):
        """Remove the selected math channel from the list."""
        current_row = self.math_list.currentRow()
        if current_row >= 0:
            self.math_list.takeItem(current_row)
            del self.math_channels[current_row]

            # Renumber remaining math channels
            for i, math_def in enumerate(self.math_channels):
                math_def['name'] = f"Math{i + 1}"

            # Update display
            self.math_list.clear()
            for math_def in self.math_channels:
                ch_a_text = f"Board {math_def['ch1'] // self.state.num_chan_per_board} CH{math_def['ch1'] % self.state.num_chan_per_board}"
                ch_b_text = f"Board {math_def['ch2'] // self.state.num_chan_per_board} CH{math_def['ch2'] % self.state.num_chan_per_board}"
                display_text = f"{math_def['name']}: {ch_a_text} {math_def['operation']} {ch_b_text}"
                self.math_list.addItem(display_text)

            # Emit signal to update plots
            self.math_channels_changed.emit()

    def calculate_math_channels(self, xy_data_array):
        """Calculate all math channels based on current data.

        Args:
            xy_data_array: The main xydata array containing channel data

        Returns:
            Dictionary mapping math channel names to (x_data, y_data) tuples
        """
        results = {}

        for math_def in self.math_channels:
            ch1_idx = math_def['ch1']
            ch2_idx = math_def['ch2']
            operation = math_def['operation']

            # Get the data for both channels
            x1, y1 = xy_data_array[ch1_idx]
            x2, y2 = xy_data_array[ch2_idx]

            # Use the x-axis from channel 1 (they should be the same)
            x_result = x1.copy()

            # Perform the operation
            try:
                if operation == '-':
                    y_result = y1 - y2
                elif operation == '+':
                    y_result = y1 + y2
                elif operation == '*':
                    y_result = y1 * y2
                elif operation == '/':
                    # Avoid division by zero
                    with np.errstate(divide='ignore', invalid='ignore'):
                        y_result = np.where(y2 != 0, y1 / y2, 0)
                else:
                    y_result = np.zeros_like(y1)

                results[math_def['name']] = (x_result, y_result)
            except Exception as e:
                print(f"Error calculating {math_def['name']}: {e}")
                results[math_def['name']] = (x1.copy(), np.zeros_like(y1))

        return results

    def showEvent(self, event):
        """Called when window is shown."""
        super().showEvent(event)
        self.update_channel_list()
