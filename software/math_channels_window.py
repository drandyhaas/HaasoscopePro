# math_channels_window.py
"""Window for creating and managing math channel operations."""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                             QPushButton, QListWidget, QLabel, QGroupBox, QColorDialog, QListWidgetItem)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QPixmap, QIcon
import numpy as np


class MathChannelsWindow(QWidget):
    """Window for creating mathematical operations between channels."""

    # Signal emitted when math channels are updated
    math_channels_changed = pyqtSignal()

    # Default colors for math channels (cycle through these)
    DEFAULT_COLORS = ['#00FFFF', '#FF00FF', '#FFFF00', '#00FF00', '#FF8000', '#FF0080']

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.state = main_window.state

        # Storage for math channel definitions
        # Each entry: {'name': 'Math1', 'ch1': 0, 'ch2': 1, 'operation': '-', 'color': '#00FFFF'}
        self.math_channels = []
        self.next_color_index = 0  # Track which color to use next

        # Storage for running min/max tracking
        # Dictionary: {math_channel_name: {'min': array, 'max': array}}
        self.running_minmax = {}

        self.setWindowTitle("Math Channels")
        self.setGeometry(100, 100, 400, 500)

        self.setup_ui()

    def create_color_icon(self, color_string):
        """Create a colored square icon for the list item.

        Args:
            color_string: Hex color string like '#00FFFF'

        Returns:
            QIcon with a colored square
        """
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(color_string))
        return QIcon(pixmap)

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
        # Two-channel operations
        self.operation_combo.addItems(['A-B', 'A+B', 'A*B', 'A/B', 'min(A,B)', 'max(A,B)'])
        # Add multiple separators for bigger visual separation
        self.operation_combo.insertSeparator(6)
        self.operation_combo.addItem('--- Single Channel ---')
        self.operation_combo.model().item(7).setEnabled(False)  # Make it non-selectable
        # Single-channel operations
        self.operation_combo.addItems(['Invert', 'Abs', 'Square', 'Sqrt', 'Log', 'Exp',
                                       'Integrate', 'Differentiate', 'Envelope', 'Minimum', 'Maximum'])
        # Show all items in dropdown
        self.operation_combo.setMaxVisibleItems(20)
        op_layout.addWidget(self.operation_combo)
        selection_layout.addLayout(op_layout)

        # Channel B selector
        ch_b_layout = QHBoxLayout()
        self.channel_b_label = QLabel("Channel B:")
        ch_b_layout.addWidget(self.channel_b_label)
        self.channel_b_combo = QComboBox()
        ch_b_layout.addWidget(self.channel_b_combo)
        selection_layout.addLayout(ch_b_layout)

        # Result preview label
        self.preview_label = QLabel("Result: CH? - CH?")
        self.preview_label.setAlignment(Qt.AlignCenter)
        selection_layout.addWidget(self.preview_label)

        # Add and Replace buttons
        add_replace_layout = QHBoxLayout()
        self.add_button = QPushButton("Add Math Channel")
        self.add_button.clicked.connect(self.add_math_channel)
        add_replace_layout.addWidget(self.add_button)

        self.replace_button = QPushButton("Replace Selected")
        self.replace_button.clicked.connect(self.replace_math_channel)
        self.replace_button.setEnabled(False)  # Initially disabled
        add_replace_layout.addWidget(self.replace_button)
        selection_layout.addLayout(add_replace_layout)

        selection_group.setLayout(selection_layout)
        layout.addWidget(selection_group)

        # --- Active Math Channels List ---
        list_group = QGroupBox("Active Math Channels")
        list_layout = QVBoxLayout()

        self.math_list = QListWidget()
        list_layout.addWidget(self.math_list)

        # Buttons layout - Row 1
        buttons_layout_1 = QHBoxLayout()
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self.remove_math_channel)
        self.remove_button.setEnabled(False)  # Initially disabled
        buttons_layout_1.addWidget(self.remove_button)

        self.color_button = QPushButton("Change Color")
        self.color_button.clicked.connect(self.change_color)
        self.color_button.setEnabled(False)  # Initially disabled
        buttons_layout_1.addWidget(self.color_button)
        list_layout.addLayout(buttons_layout_1)

        # Buttons layout - Row 2
        buttons_layout_2 = QHBoxLayout()
        self.measure_button = QPushButton("Use for Measurements")
        self.measure_button.clicked.connect(self.use_for_measurements)
        self.measure_button.setEnabled(False)  # Initially disabled
        buttons_layout_2.addWidget(self.measure_button)

        self.measure_active_button = QPushButton("Measure Active Channel")
        self.measure_active_button.clicked.connect(self.measure_active_channel)
        buttons_layout_2.addWidget(self.measure_active_button)
        list_layout.addLayout(buttons_layout_2)

        list_group.setLayout(list_layout)
        layout.addWidget(list_group)

        # Close button at the bottom
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)

        self.setLayout(layout)

        # Connect signals for preview update
        self.channel_a_combo.currentIndexChanged.connect(self.update_preview)
        self.channel_b_combo.currentIndexChanged.connect(self.update_preview)
        self.operation_combo.currentIndexChanged.connect(self.on_operation_changed)

        # Connect list selection change to enable/disable buttons
        self.math_list.itemSelectionChanged.connect(self.update_button_states)

    def update_channel_list(self):
        """Update the available channels in the combo boxes."""
        self.channel_a_combo.clear()
        self.channel_b_combo.clear()

        num_channels = self.state.num_board * self.state.num_chan_per_board

        for i in range(num_channels):
            board = i // self.state.num_chan_per_board
            chan = i % self.state.num_chan_per_board
            channel_name = f"Board {board} Channel {chan}"
            self.channel_a_combo.addItem(channel_name, i)
            self.channel_b_combo.addItem(channel_name, i)

        # Set default: Channel A = 0, Channel B = 1 (if available)
        if num_channels > 1:
            self.channel_b_combo.setCurrentIndex(1)

        self.update_preview()

    def is_two_channel_operation(self, operation):
        """Check if an operation requires two channels.

        Args:
            operation: The operation string

        Returns:
            True if operation requires two channels, False otherwise
        """
        two_channel_ops = ['A-B', 'A+B', 'A*B', 'A/B', 'min(A,B)', 'max(A,B)',
                          '-', '+', '*', '/']  # Include old format for backward compatibility
        return operation in two_channel_ops

    def on_operation_changed(self):
        """Called when operation selection changes."""
        op = self.operation_combo.currentText()
        needs_two = self.is_two_channel_operation(op)

        # Enable/disable channel B based on operation
        self.channel_b_label.setEnabled(needs_two)
        self.channel_b_combo.setEnabled(needs_two)

        # Update preview
        self.update_preview()

    def update_preview(self):
        """Update the preview label showing what the math channel will be."""
        ch_a = self.channel_a_combo.currentData()
        op = self.operation_combo.currentText()

        if ch_a is not None:
            ch_a_text = self.channel_a_combo.currentText()

            if self.is_two_channel_operation(op):
                ch_b = self.channel_b_combo.currentData()
                if ch_b is not None:
                    ch_b_text = self.channel_b_combo.currentText()
                    self.preview_label.setText(f"Result: {ch_a_text} {op} {ch_b_text}")
                else:
                    self.preview_label.setText(f"Result: {ch_a_text} {op} CH?")
            else:
                self.preview_label.setText(f"Result: {op}({ch_a_text})")

    def update_button_states(self):
        """Enable or disable buttons based on whether a math channel is selected."""
        has_selection = self.math_list.currentRow() >= 0
        self.remove_button.setEnabled(has_selection)
        self.color_button.setEnabled(has_selection)
        self.measure_button.setEnabled(has_selection)
        # Replace button is always enabled/disabled based on selection (now in top section)
        self.replace_button.setEnabled(has_selection)

    def add_math_channel(self):
        """Add a new math channel to the list."""
        ch_a = self.channel_a_combo.currentData()
        op = self.operation_combo.currentText()

        if ch_a is None:
            return

        # For two-channel operations, check that ch_b is also selected
        if self.is_two_channel_operation(op):
            ch_b = self.channel_b_combo.currentData()
            if ch_b is None:
                return
        else:
            ch_b = None  # Single-channel operation

        # Create a unique name for this math channel
        math_name = f"Math{len(self.math_channels) + 1}"

        # Assign a unique color from the default palette
        color = self.DEFAULT_COLORS[self.next_color_index % len(self.DEFAULT_COLORS)]
        self.next_color_index += 1

        # Create the math channel definition
        math_def = {
            'name': math_name,
            'ch1': ch_a,
            'ch2': ch_b,  # Will be None for single-channel operations
            'operation': op,
            'color': color
        }

        self.math_channels.append(math_def)

        # Initialize running min/max tracking for this channel (will be set on first calculation)
        self.running_minmax[math_name] = None

        # Update the list display
        ch_a_text = self.channel_a_combo.currentText()
        if self.is_two_channel_operation(op):
            ch_b_text = self.channel_b_combo.currentText()
            display_text = f"{math_name}: {ch_a_text} {op} {ch_b_text}"
        else:
            display_text = f"{math_name}: {op}({ch_a_text})"

        # Create list item with colored icon
        item = QListWidgetItem(self.create_color_icon(color), display_text)
        self.math_list.addItem(item)

        # Emit signal to update plots
        self.math_channels_changed.emit()

    def replace_math_channel(self):
        """Replace the selected math channel with current settings."""
        current_row = self.math_list.currentRow()
        if current_row < 0 or current_row >= len(self.math_channels):
            return

        ch_a = self.channel_a_combo.currentData()
        op = self.operation_combo.currentText()

        if ch_a is None:
            return

        # For two-channel operations, check that ch_b is also selected
        if self.is_two_channel_operation(op):
            ch_b = self.channel_b_combo.currentData()
            if ch_b is None:
                return
        else:
            ch_b = None  # Single-channel operation

        # Update the math channel definition
        self.math_channels[current_row]['ch1'] = ch_a
        self.math_channels[current_row]['ch2'] = ch_b
        self.math_channels[current_row]['operation'] = op

        # Reset running min/max tracking for this channel
        math_name = self.math_channels[current_row]['name']
        self.running_minmax[math_name] = None

        # Update the list display
        ch_a_text = self.channel_a_combo.currentText()
        if self.is_two_channel_operation(op):
            ch_b_text = self.channel_b_combo.currentText()
            display_text = f"{math_name}: {ch_a_text} {op} {ch_b_text}"
        else:
            display_text = f"{math_name}: {op}({ch_a_text})"

        # Update the item in the list
        item = self.math_list.item(current_row)
        item.setText(display_text)

        # Emit signal to update plots
        self.math_channels_changed.emit()

    def remove_math_channel(self):
        """Remove the selected math channel from the list."""
        current_row = self.math_list.currentRow()
        if current_row >= 0:
            self.math_list.takeItem(current_row)
            del self.math_channels[current_row]

            # Rebuild running_minmax with renumbered names
            old_minmax = self.running_minmax.copy()
            self.running_minmax = {}

            # Renumber remaining math channels and update running_minmax
            for i, math_def in enumerate(self.math_channels):
                old_name = math_def['name']
                new_name = f"Math{i + 1}"
                math_def['name'] = new_name

                # Preserve running min/max data if it exists
                if old_name in old_minmax:
                    self.running_minmax[new_name] = old_minmax[old_name]
                else:
                    self.running_minmax[new_name] = None

            # Update display
            self.math_list.clear()
            for math_def in self.math_channels:
                ch_a_text = f"Board {math_def['ch1'] // self.state.num_chan_per_board} Channel {math_def['ch1'] % self.state.num_chan_per_board}"

                if self.is_two_channel_operation(math_def['operation']):
                    ch_b_text = f"Board {math_def['ch2'] // self.state.num_chan_per_board} Channel {math_def['ch2'] % self.state.num_chan_per_board}"
                    display_text = f"{math_def['name']}: {ch_a_text} {math_def['operation']} {ch_b_text}"
                else:
                    display_text = f"{math_def['name']}: {math_def['operation']}({ch_a_text})"

                # Create list item with colored icon
                item = QListWidgetItem(self.create_color_icon(math_def['color']), display_text)
                self.math_list.addItem(item)

            # Emit signal to update plots
            self.math_channels_changed.emit()

    def change_color(self):
        """Change the color of the selected math channel."""
        current_row = self.math_list.currentRow()
        if current_row >= 0 and current_row < len(self.math_channels):
            # Get the current color
            current_color = QColor(self.math_channels[current_row]['color'])

            # Open color dialog
            color = QColorDialog.getColor(current_color, self, "Select Math Channel Color")

            if color.isValid():
                # Update the math channel definition
                self.math_channels[current_row]['color'] = color.name()

                # Update the icon for this list item
                item = self.math_list.item(current_row)
                item.setIcon(self.create_color_icon(color.name()))

                # Emit signal to update plots
                self.math_channels_changed.emit()

    def use_for_measurements(self):
        """Use the selected math channel for measurements."""
        current_row = self.math_list.currentRow()
        if current_row >= 0 and current_row < len(self.math_channels):
            math_channel_name = self.math_channels[current_row]['name']
            self.main_window.measurements.select_math_channel_for_measurement(math_channel_name)

    def measure_active_channel(self):
        """Switch back to measuring the active channel."""
        self.main_window.measurements.select_math_channel_for_measurement(None)

    def select_math_channel_in_list(self, math_channel_name):
        """Select a specific math channel in the list by name.

        Args:
            math_channel_name: Name of the math channel to select (e.g., 'Math1')
        """
        # Find the index of the math channel with this name
        for i, math_def in enumerate(self.math_channels):
            if math_def['name'] == math_channel_name:
                self.math_list.setCurrentRow(i)
                return

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
            operation = math_def['operation']

            # Get the data for channel 1
            x1, y1 = xy_data_array[ch1_idx]
            x_result = x1.copy()

            # Perform the operation
            try:
                if self.is_two_channel_operation(operation):
                    # Two-channel operations
                    ch2_idx = math_def['ch2']
                    x2, y2 = xy_data_array[ch2_idx]

                    if operation == '-' or operation == 'A-B':
                        y_result = y1 - y2
                    elif operation == '+' or operation == 'A+B':
                        y_result = y1 + y2
                    elif operation == '*' or operation == 'A*B':
                        y_result = y1 * y2
                    elif operation == '/' or operation == 'A/B':
                        # Avoid division by zero
                        with np.errstate(divide='ignore', invalid='ignore'):
                            y_result = np.where(y2 != 0, y1 / y2, 0)
                    elif operation == 'min(A,B)':
                        y_result = np.minimum(y1, y2)
                    elif operation == 'max(A,B)':
                        y_result = np.maximum(y1, y2)
                    else:
                        y_result = np.zeros_like(y1)
                else:
                    # Single-channel operations
                    if operation == 'Invert':
                        y_result = -y1
                    elif operation == 'Abs':
                        y_result = np.abs(y1)
                    elif operation == 'Square':
                        y_result = y1 * y1
                    elif operation == 'Sqrt':
                        y_result = np.sqrt(np.abs(y1))
                    elif operation == 'Log':
                        with np.errstate(divide='ignore', invalid='ignore'):
                            y_result = np.where(y1 > 0, np.log10(y1), 0)
                    elif operation == 'Exp':
                        with np.errstate(over='ignore'):
                            y_result = np.exp(y1)
                            # Clip to reasonable values to avoid overflow display issues
                            y_result = np.clip(y_result, -1e10, 1e10)
                    elif operation == 'Integrate':
                        # Numerical integration using cumulative trapezoidal rule
                        # dx = time step (assume uniform spacing)
                        if len(x1) > 1:
                            dx = x1[1] - x1[0]
                            y_result = np.cumsum(y1) * dx
                        else:
                            y_result = y1.copy()
                    elif operation == 'Differentiate':
                        # Numerical differentiation
                        if len(x1) > 1:
                            dx = x1[1] - x1[0]
                            y_result = np.gradient(y1, dx)
                        else:
                            y_result = np.zeros_like(y1)
                    elif operation == 'Envelope':
                        # Simple envelope detection using max of absolute value in sliding window
                        window_size = max(10, len(y1) // 100)  # 1% of data or min 10 points
                        y_abs = np.abs(y1)
                        y_result = np.zeros_like(y1)
                        for i in range(len(y1)):
                            start = max(0, i - window_size // 2)
                            end = min(len(y1), i + window_size // 2 + 1)
                            y_result[i] = np.max(y_abs[start:end])
                    elif operation == 'Minimum':
                        # Running minimum - track minimum value seen at each time point
                        math_name = math_def['name']
                        if self.running_minmax[math_name] is None:
                            # First time - initialize with current data
                            self.running_minmax[math_name] = {'min': y1.copy(), 'max': y1.copy()}
                            y_result = y1.copy()
                        else:
                            # Update running minimum
                            self.running_minmax[math_name]['min'] = np.minimum(
                                self.running_minmax[math_name]['min'], y1
                            )
                            y_result = self.running_minmax[math_name]['min'].copy()
                    elif operation == 'Maximum':
                        # Running maximum - track maximum value seen at each time point
                        math_name = math_def['name']
                        if self.running_minmax[math_name] is None:
                            # First time - initialize with current data
                            self.running_minmax[math_name] = {'min': y1.copy(), 'max': y1.copy()}
                            y_result = y1.copy()
                        else:
                            # Update running maximum
                            self.running_minmax[math_name]['max'] = np.maximum(
                                self.running_minmax[math_name]['max'], y1
                            )
                            y_result = self.running_minmax[math_name]['max'].copy()
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
