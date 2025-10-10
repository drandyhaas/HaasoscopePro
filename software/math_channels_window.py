# math_channels_window.py
"""Window for creating and managing math channel operations."""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                             QPushButton, QListWidget, QLabel, QGroupBox, QColorDialog, QListWidgetItem, QCheckBox)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap, QIcon
import numpy as np


class RefreshingComboBox(QComboBox):
    """A QComboBox that refreshes its contents before showing the popup."""

    def __init__(self, refresh_callback=None, parent=None):
        super().__init__(parent)
        self.refresh_callback = refresh_callback

    def showPopup(self):
        """Override to refresh contents before showing popup."""
        if self.refresh_callback:
            self.refresh_callback()
        super().showPopup()


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

    @staticmethod
    def create_color_icon(color_string):
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
        self.channel_a_combo = RefreshingComboBox(refresh_callback=self.update_channel_list)
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
                                       'Integrate', 'Differentiate', 'Envelope', 'Smooth', 'Minimum', 'Maximum'])
        # Show all items in dropdown
        self.operation_combo.setMaxVisibleItems(20)
        op_layout.addWidget(self.operation_combo)
        selection_layout.addLayout(op_layout)

        # Channel B selector
        ch_b_layout = QHBoxLayout()
        self.channel_b_label = QLabel("Channel B:")
        ch_b_layout.addWidget(self.channel_b_label)
        self.channel_b_combo = RefreshingComboBox(refresh_callback=self.update_channel_list)
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

        self.remove_all_button = QPushButton("Remove All")
        self.remove_all_button.clicked.connect(self.remove_all_math_channels)
        buttons_layout_1.addWidget(self.remove_all_button)

        self.color_button = QPushButton("Change Color")
        self.color_button.clicked.connect(self.change_color)
        self.color_button.setEnabled(False)  # Initially disabled
        buttons_layout_1.addWidget(self.color_button)
        list_layout.addLayout(buttons_layout_1)

        # Buttons layout - Row 2
        buttons_layout_2 = QHBoxLayout()
        self.displayed_button = QCheckBox("Displayed")
        self.displayed_button.setChecked(True)
        self.displayed_button.clicked.connect(self.toggle_displayed)
        self.displayed_button.setEnabled(False)  # Initially disabled until a math channel is selected
        buttons_layout_2.addWidget(self.displayed_button)

        self.measure_button = QCheckBox("Use for Measurements Menu")
        self.measure_button.setChecked(False)
        self.measure_button.clicked.connect(self.toggle_use_for_measurements)
        self.measure_button.setEnabled(False)  # Initially disabled until a math channel is selected
        buttons_layout_2.addWidget(self.measure_button)
        list_layout.addLayout(buttons_layout_2)

        # Buttons layout - Row 3
        buttons_layout_3 = QHBoxLayout()
        self.fft_button = QCheckBox("Use for FFT")
        self.fft_button.setChecked(False)
        self.fft_button.clicked.connect(self.toggle_use_for_fft)
        self.fft_button.setEnabled(False)  # Initially disabled until a math channel is selected
        buttons_layout_3.addWidget(self.fft_button)
        list_layout.addLayout(buttons_layout_3)

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
        # Save current selections
        current_a_data = self.channel_a_combo.currentData()
        current_b_data = self.channel_b_combo.currentData()

        self.channel_a_combo.clear()
        self.channel_b_combo.clear()

        num_channels = self.state.num_board * self.state.num_chan_per_board

        # Add regular channels and track available (non-disabled) indices
        available_channels = []
        for i in range(num_channels):
            board = i // self.state.num_chan_per_board
            chan = i % self.state.num_chan_per_board
            channel_name = f"Board {board} Channel {chan}"

            # Check if this channel should be disabled
            is_disabled = chan == 1 and not self.state.dotwochannel[board]

            # Only add non-disabled channels
            if not is_disabled:
                self.channel_a_combo.addItem(channel_name, i)
                self.channel_b_combo.addItem(channel_name, i)
                available_channels.append(i)

        # Add reference channels if they exist
        if len(self.main_window.reference_data) > 0:
            separator_pos = self.channel_a_combo.count()
            self.channel_a_combo.insertSeparator(separator_pos)
            self.channel_b_combo.insertSeparator(separator_pos)

            for ref_idx in sorted(self.main_window.reference_data.keys()):
                board = ref_idx // self.state.num_chan_per_board
                chan = ref_idx % self.state.num_chan_per_board
                ref_identifier = f"Ref{ref_idx}"  # Use string identifier like "Ref0", "Ref1"
                ref_display_name = f"📌 Ref Board {board} Channel {chan}"
                self.channel_a_combo.addItem(ref_display_name, ref_identifier)
                self.channel_b_combo.addItem(ref_display_name, ref_identifier)

        # Add separator if there are math channels
        if len(self.math_channels) > 0:
            separator_pos = self.channel_a_combo.count()
            self.channel_a_combo.insertSeparator(separator_pos)
            self.channel_b_combo.insertSeparator(separator_pos)

            # Add math channels (use string identifier to distinguish from regular channels)
            for math_def in self.math_channels:
                math_name = math_def['name']
                self.channel_a_combo.addItem(f"🔢 {math_name}", math_name)  # Use string as data
                self.channel_b_combo.addItem(f"🔢 {math_name}", math_name)

        # Restore previous selections if they still exist and are not disabled
        restored_a = False
        restored_b = False

        if current_a_data is not None:
            # Check if the previous selection was a disabled channel
            if not self.uses_disabled_channel(current_a_data):
                index_a = self.channel_a_combo.findData(current_a_data)
                if index_a >= 0:
                    self.channel_a_combo.setCurrentIndex(index_a)
                    restored_a = True

        if current_b_data is not None:
            # Check if the previous selection was a disabled channel
            if not self.uses_disabled_channel(current_b_data):
                index_b = self.channel_b_combo.findData(current_b_data)
                if index_b >= 0:
                    self.channel_b_combo.setCurrentIndex(index_b)
                    restored_b = True

        # Set defaults to first and next available channels if not restored
        if not restored_a and len(available_channels) > 0:
            # Channel A defaults to first available
            index_a = self.channel_a_combo.findData(available_channels[0])
            if index_a >= 0:
                self.channel_a_combo.setCurrentIndex(index_a)

        if not restored_b and len(available_channels) > 1:
            # Channel B defaults to second available
            index_b = self.channel_b_combo.findData(available_channels[1])
            if index_b >= 0:
                self.channel_b_combo.setCurrentIndex(index_b)

        self.update_preview()

    @staticmethod
    def is_two_channel_operation(operation):
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

    def get_channel_display_name(self, ch_data):
        """Get display name for a channel (regular, reference, or math).

        Args:
            ch_data: Either an integer (regular channel) or string (reference/math channel name)

        Returns:
            Display name string
        """
        if isinstance(ch_data, str):
            # Check if it's a reference channel
            if ch_data.startswith("Ref"):
                # Extract the channel index from "Ref0", "Ref1", etc.
                ref_idx = int(ch_data[3:])
                board = ref_idx // self.state.num_chan_per_board
                chan = ref_idx % self.state.num_chan_per_board
                return f"Ref Board {board} Channel {chan}"
            else:
                # Math channel
                return ch_data
        else:
            # Regular channel
            board = ch_data // self.state.num_chan_per_board
            chan = ch_data % self.state.num_chan_per_board
            return f"Board {board} Channel {chan}"

    def update_preview(self):
        """Update the preview label showing what the math channel will be."""
        ch_a = self.channel_a_combo.currentData()
        op = self.operation_combo.currentText()

        if ch_a is not None:
            ch_a_text = self.get_channel_display_name(ch_a)

            if self.is_two_channel_operation(op):
                ch_b = self.channel_b_combo.currentData()
                if ch_b is not None:
                    ch_b_text = self.get_channel_display_name(ch_b)
                    # Replace A and B in the operation string with actual channel names
                    op_display = op.replace('B', " "+ch_b_text).replace('A', ch_a_text+" ")
                    self.preview_label.setText(f"Result: {op_display}")
                else:
                    # Replace A with channel name, keep B as placeholder
                    op_display = op.replace('B', ' CH?').replace('A', ch_a_text+" ")
                    self.preview_label.setText(f"Result: {op_display}")
            else:
                self.preview_label.setText(f"Result: {op}({ch_a_text})")

    def update_button_states(self):
        """Enable or disable buttons based on whether a math channel is selected."""
        has_selection = self.math_list.currentRow() >= 0
        self.remove_button.setEnabled(has_selection)
        self.color_button.setEnabled(has_selection)
        self.measure_button.setEnabled(has_selection)
        self.fft_button.setEnabled(has_selection)
        # Replace button is always enabled/disabled based on selection (now in top section)
        self.replace_button.setEnabled(has_selection)

        # Update displayed button state to match selected math channel
        if has_selection:
            current_row = self.math_list.currentRow()
            if 0 <= current_row < len(self.math_channels):
                math_def = self.math_channels[current_row]

                # Check if this math channel uses disabled channels
                uses_disabled = self.uses_disabled_channel(math_def['ch1']) or \
                               (math_def['ch2'] is not None and self.uses_disabled_channel(math_def['ch2']))

                # Disable the displayed button if using disabled channels
                self.displayed_button.setEnabled(has_selection and not uses_disabled)

                self.displayed_button.blockSignals(True)
                self.displayed_button.setChecked(math_def.get('displayed', True))
                self.displayed_button.blockSignals(False)

                # Update FFT button state
                self.fft_button.blockSignals(True)
                self.fft_button.setChecked(math_def.get('fft_enabled', False))
                self.fft_button.blockSignals(False)
        else:
            self.displayed_button.setEnabled(False)

        # If the measure button is checked and a math channel is selected, update the measurement channel
        if self.measure_button.isChecked() and has_selection:
            current_row = self.math_list.currentRow()
            if 0 <= current_row < len(self.math_channels):
                math_channel_name = self.math_channels[current_row]['name']
                # Check if we need to update (avoid unnecessary updates)
                if self.main_window.measurements.selected_math_channel != math_channel_name:
                    self.main_window.measurements.select_math_channel_for_measurement(math_channel_name)

    def uses_disabled_channel(self, ch_data):
        """Check if a channel is disabled (channel 1 on boards not in two-channel mode).

        Args:
            ch_data: Either an integer (regular channel) or string (reference/math channel)

        Returns:
            True if the channel is disabled, False otherwise
        """
        # Only regular channels can be disabled
        if not isinstance(ch_data, int):
            return False

        # Check if this is channel 1 on a board (odd channel index per board)
        num_chan_per_board = self.state.num_chan_per_board
        board = ch_data // num_chan_per_board
        chan = ch_data % num_chan_per_board

        # Channel 1 is the second channel (index 1) on each board
        if chan == 1:
            # Check if board is NOT in two-channel mode
            return not self.state.dotwochannel[board]

        return False

    def check_circular_dependency(self, math_name, ch1, ch2, exclude_name=None):
        """Check if using ch1 and ch2 would create a circular dependency.

        Args:
            math_name: Name of the math channel being created/updated
            ch1: First channel (int or string)
            ch2: Second channel (int or string) or None
            exclude_name: Name to exclude from dependency check (for replace operation)

        Returns:
            True if circular dependency detected, False otherwise
        """
        def get_dependencies(ch):
            """Get all dependencies for a channel recursively."""
            if not isinstance(ch, str):  # Regular channel, no dependencies
                return set()

            if ch.startswith("Ref"):  # Reference channel, no dependencies
                return set()

            thedeps = {ch}
            # Find the math channel definition
            for math_def in self.math_channels:
                if math_def['name'] == ch:
                    if math_def['name'] == exclude_name:
                        # Skip this one during replace operation
                        continue
                    # Add dependencies of ch1
                    if isinstance(math_def['ch1'], str) and not math_def['ch1'].startswith("Ref"):
                        thedeps.update(get_dependencies(math_def['ch1']))
                    # Add dependencies of ch2
                    if math_def['ch2'] is not None and isinstance(math_def['ch2'], str) and not math_def['ch2'].startswith("Ref"):
                        thedeps.update(get_dependencies(math_def['ch2']))
                    break
            return thedeps

        # Check if using ch1 or ch2 creates a circular dependency
        deps = set()
        if isinstance(ch1, str):
            deps.update(get_dependencies(ch1))
        if ch2 is not None and isinstance(ch2, str):
            deps.update(get_dependencies(ch2))

        return math_name in deps

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

        # Check for circular dependencies
        if self.check_circular_dependency(math_name, ch_a, ch_b):
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Circular Dependency",
                              f"Cannot create {math_name}: would create a circular dependency!")
            return

        # Assign a unique color from the default palette
        color = self.DEFAULT_COLORS[self.next_color_index % len(self.DEFAULT_COLORS)]
        self.next_color_index += 1

        # Check if using disabled channels (channel 1 on boards not in two-channel mode)
        uses_disabled_channel = self.uses_disabled_channel(ch_a) or (ch_b is not None and self.uses_disabled_channel(ch_b))

        # Get the current line width from the main window
        line_width = self.main_window.ui.linewidthBox.value()

        # Create the math channel definition
        math_def = {
            'name': math_name,
            'ch1': ch_a,
            'ch2': ch_b,  # Will be None for single-channel operations
            'operation': op,
            'color': color,
            'displayed': not uses_disabled_channel,  # False if using disabled channel, True otherwise
            'width': line_width,  # Store the line width that was active when math channel was created
            'fft_enabled': False  # Track FFT state for this math channel
        }

        self.math_channels.append(math_def)

        # Initialize running min/max tracking for this channel (will be set on first calculation)
        self.running_minmax[math_name] = None

        # Update the list display
        ch_a_text = self.get_channel_display_name(ch_a)
        if self.is_two_channel_operation(op):
            ch_b_text = self.get_channel_display_name(ch_b)
            # Replace A and B in the operation string with actual channel names
            op_display = op.replace('B', " "+ch_b_text).replace('A', ch_a_text+" ")
            display_text = f"{math_name}: {op_display}"
        else:
            display_text = f"{math_name}: {op}({ch_a_text})"

        # Create list item with colored icon
        item = QListWidgetItem(self.create_color_icon(color), display_text)
        self.math_list.addItem(item)

        # Update channel lists to include new math channel
        self.update_channel_list()

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

        # Get the math channel name
        math_name = self.math_channels[current_row]['name']

        # Check for circular dependencies (exclude current channel from check)
        if self.check_circular_dependency(math_name, ch_a, ch_b, exclude_name=math_name):
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Circular Dependency",
                              f"Cannot update {math_name}: would create a circular dependency!")
            return

        # Check if using disabled channels
        uses_disabled_channel = self.uses_disabled_channel(ch_a) or (ch_b is not None and self.uses_disabled_channel(ch_b))

        # Update the math channel definition
        self.math_channels[current_row]['ch1'] = ch_a
        self.math_channels[current_row]['ch2'] = ch_b
        self.math_channels[current_row]['operation'] = op
        # Update displayed state if using disabled channel
        if uses_disabled_channel:
            self.math_channels[current_row]['displayed'] = False

        # Reset running min/max tracking for this channel
        self.running_minmax[math_name] = None

        # Update the list display
        ch_a_text = self.get_channel_display_name(ch_a)
        if self.is_two_channel_operation(op):
            ch_b_text = self.get_channel_display_name(ch_b)
            # Replace A and B in the operation string with actual channel names
            op_display = op.replace('B', " "+ch_b_text).replace('A', ch_a_text+" ")
            display_text = f"{math_name}: {op_display}"
        else:
            display_text = f"{math_name}: {op}({ch_a_text})"

        # Update the item in the list
        item = self.math_list.item(current_row)
        item.setText(display_text)

        # Update button states to reflect new displayed state
        self.update_button_states()

        # Emit signal to update plots
        self.math_channels_changed.emit()

    def remove_math_channel(self):
        """Remove the selected math channel from the list."""
        current_row = self.math_list.currentRow()
        if current_row >= 0:
            # Check if the removed channel is being used for measurements or FFT
            removed_channel_name = self.math_channels[current_row]['name']
            was_used_for_measurements = (self.main_window.measurements.selected_math_channel == removed_channel_name)
            was_used_for_fft = self.math_channels[current_row].get('fft_enabled', False)

            # Remove from FFT state tracking
            if removed_channel_name in self.state.fft_enabled:
                del self.state.fft_enabled[removed_channel_name]

            self.math_list.takeItem(current_row)
            del self.math_channels[current_row]

            # Rebuild running_minmax with renumbered names and update references
            old_minmax = self.running_minmax.copy()
            self.running_minmax = {}
            name_mapping = {}  # Map old names to new names

            # Renumber remaining math channels and update running_minmax and FFT state
            for i, math_def in enumerate(self.math_channels):
                old_name = math_def['name']
                new_name = f"Math{i + 1}"
                math_def['name'] = new_name
                name_mapping[old_name] = new_name

                # Preserve running min/max data if it exists
                if old_name in old_minmax:
                    self.running_minmax[new_name] = old_minmax[old_name]
                else:
                    self.running_minmax[new_name] = None

                # Update FFT state tracking with new name
                if old_name in self.state.fft_enabled:
                    self.state.fft_enabled[new_name] = self.state.fft_enabled[old_name]
                    del self.state.fft_enabled[old_name]

            # Update references in all math channels
            for math_def in self.math_channels:
                if isinstance(math_def['ch1'], str) and math_def['ch1'] in name_mapping:
                    math_def['ch1'] = name_mapping[math_def['ch1']]
                if math_def['ch2'] is not None and isinstance(math_def['ch2'], str) and math_def['ch2'] in name_mapping:
                    math_def['ch2'] = name_mapping[math_def['ch2']]

            # If the removed channel was being used for measurements, switch to active channel
            if was_used_for_measurements:
                self.main_window.measurements.select_math_channel_for_measurement(None)
                self.measure_button.setChecked(False)
            # If a different channel was being used for measurements and it was renamed, update the reference
            elif self.main_window.measurements.selected_math_channel in name_mapping:
                old_selected = self.main_window.measurements.selected_math_channel
                new_selected = name_mapping[old_selected]
                self.main_window.measurements.selected_math_channel = new_selected
                self.main_window.measurements.update_measurement_header()

            # Update display
            self.math_list.clear()
            for math_def in self.math_channels:
                ch_a_text = self.get_channel_display_name(math_def['ch1'])

                if self.is_two_channel_operation(math_def['operation']):
                    ch_b_text = self.get_channel_display_name(math_def['ch2'])
                    # Replace A and B in the operation string with actual channel names
                    op_display = math_def['operation'].replace('B', " "+ch_b_text).replace('A', ch_a_text+" ")
                    display_text = f"{math_def['name']}: {op_display}"
                else:
                    display_text = f"{math_def['name']}: {math_def['operation']}({ch_a_text})"

                # Create list item with colored icon
                item = QListWidgetItem(self.create_color_icon(math_def['color']), display_text)
                self.math_list.addItem(item)

            # Update channel lists since math channels changed
            self.update_channel_list()

            # If the removed channel was used for FFT, update FFT window visibility
            if was_used_for_fft and self.main_window.fftui is not None:
                should_show = any(self.state.fft_enabled.values())
                if should_show:
                    self.main_window.fftui.show()
                else:
                    self.main_window.fftui.hide()

            # Emit signal to update plots
            self.math_channels_changed.emit()

    def remove_all_math_channels(self):
        """Remove all math channels from the list."""
        if len(self.math_channels) == 0:
            return

        # Check if any channel was being used for measurements or FFT
        was_used_for_measurements = (self.main_window.measurements.selected_math_channel is not None)
        had_fft_enabled = any(math_def.get('fft_enabled', False) for math_def in self.math_channels)

        # Remove all math channels from FFT state tracking
        for math_def in self.math_channels:
            math_name = math_def['name']
            if math_name in self.state.fft_enabled:
                del self.state.fft_enabled[math_name]

        # Clear all data
        self.math_channels.clear()
        self.running_minmax.clear()
        self.math_list.clear()

        # If a math channel was being used for measurements, switch back to active channel
        if was_used_for_measurements:
            self.main_window.measurements.select_math_channel_for_measurement(None)
            self.measure_button.setChecked(False)

        # If any math channel had FFT enabled, update FFT window visibility
        if had_fft_enabled and self.main_window.fftui is not None:
            should_show = any(self.state.fft_enabled.values())
            if should_show:
                self.main_window.fftui.show()
            else:
                self.main_window.fftui.hide()

        # Update button states
        self.update_button_states()

        # Emit signal to update plots
        self.math_channels_changed.emit()

    def change_color(self):
        """Change the color of the selected math channel."""
        current_row = self.math_list.currentRow()
        if 0 <= current_row < len(self.math_channels):
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

    def toggle_displayed(self, checked):
        """Toggle the displayed state of the selected math channel.

        Args:
            checked: True if channel should be displayed, False otherwise
        """
        current_row = self.math_list.currentRow()
        if 0 <= current_row < len(self.math_channels):
            self.math_channels[current_row]['displayed'] = checked
            # Emit signal to update plots
            self.math_channels_changed.emit()

    def toggle_use_for_measurements(self, checked):
        """Toggle between using selected math channel or active channel for measurements.

        Args:
            checked: True if button is checked (use math channel), False otherwise (use active channel)
        """
        if checked:
            # Use the selected math channel
            current_row = self.math_list.currentRow()
            if 0 <= current_row < len(self.math_channels):
                math_channel_name = self.math_channels[current_row]['name']
                self.main_window.measurements.select_math_channel_for_measurement(math_channel_name)
        else:
            # Use the active channel
            self.main_window.measurements.select_math_channel_for_measurement(None)

    def toggle_use_for_fft(self, checked):
        """Toggle FFT for the selected math channel.

        Args:
            checked: True if FFT should be enabled for this math channel, False otherwise
        """
        current_row = self.math_list.currentRow()
        if 0 <= current_row < len(self.math_channels):
            # Update the math channel's FFT state
            math_channel_name = self.math_channels[current_row]['name']
            self.math_channels[current_row]['fft_enabled'] = checked

            # Track this math channel in the state.fft_enabled dictionary
            self.state.fft_enabled[math_channel_name] = checked

            # Create FFT window if it doesn't exist
            if self.main_window.fftui is None:
                from FFTWindow import FFTWindow
                self.main_window.fftui = FFTWindow(self.main_window)
                # Connect the window_closed signal to our handler
                self.main_window.fftui.window_closed.connect(self.main_window.on_fft_window_closed)

            # Show or hide FFT window based on whether any channel has FFT enabled
            should_show = any(self.state.fft_enabled.values())
            if should_show:
                self.main_window.fftui.show()
            else:
                self.main_window.fftui.hide()

    def sync_measure_button_state(self):
        """Synchronize the measure button state with the current measurement channel selection."""
        selected_math_channel = self.main_window.measurements.selected_math_channel

        if selected_math_channel is not None:
            # A math channel is selected for measurements
            self.measure_button.setChecked(True)
            # Select it in the list if it's not already selected
            for i, math_def in enumerate(self.math_channels):
                if math_def['name'] == selected_math_channel:
                    if self.math_list.currentRow() != i:
                        self.math_list.setCurrentRow(i)
                    break
        else:
            # Active channel is selected for measurements
            self.measure_button.setChecked(False)

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

    def _topological_sort(self):
        """Sort math channels by dependencies using topological sort.

        Returns:
            List of math channel definitions sorted so dependencies come first
        """
        if not self.math_channels:
            return []

        # Build adjacency list (math_name -> list of math channels that depend on it)
        # and in-degree count (math_name -> number of dependencies)
        graph = {math_def['name']: [] for math_def in self.math_channels}
        in_degree = {math_def['name']: 0 for math_def in self.math_channels}

        # Build the dependency graph
        for math_def in self.math_channels:
            math_name = math_def['name']
            dependencies = []

            # Check if ch1 is a math channel (but not a reference channel)
            if isinstance(math_def['ch1'], str) and not math_def['ch1'].startswith("Ref"):
                dependencies.append(math_def['ch1'])

            # Check if ch2 is a math channel (but not a reference channel)
            if math_def['ch2'] is not None and isinstance(math_def['ch2'], str) and not math_def['ch2'].startswith("Ref"):
                dependencies.append(math_def['ch2'])

            # For each dependency, add an edge and increment in-degree
            for dep in dependencies:
                if dep in graph:  # Only if the dependency is a math channel we know about
                    graph[dep].append(math_name)
                    in_degree[math_name] += 1

        # Kahn's algorithm for topological sort
        queue = [math_def['name'] for math_def in self.math_channels if in_degree[math_def['name']] == 0]
        sorted_names = []

        while queue:
            # Remove a node with no incoming edges
            current = queue.pop(0)
            sorted_names.append(current)

            # For each node that depends on current
            for dependent in graph[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # Convert sorted names back to math definitions
        name_to_def = {math_def['name']: math_def for math_def in self.math_channels}
        return [name_to_def[name] for name in sorted_names]

    def calculate_math_channels(self, xy_data_array):
        """Calculate all math channels based on current data.

        Args:
            xy_data_array: The stabilized xydata array (list of tuples) or raw xydata array containing channel data

        Returns:
            Dictionary mapping math channel names to (x_data, y_data) tuples
        """
        results = {}

        # Sort math channels by dependencies (topological sort)
        sorted_channels = self._topological_sort()

        for math_def in sorted_channels:
            ch1_idx = math_def['ch1']
            operation = math_def['operation']

            # Get the data for channel 1 - check if it's a math channel, reference channel, or regular channel
            if isinstance(ch1_idx, str):
                if ch1_idx.startswith("Ref"):
                    # It's a reference channel - get from reference_data
                    ref_idx = int(ch1_idx[3:])
                    if ref_idx in self.main_window.reference_data:
                        ref_data = self.main_window.reference_data[ref_idx]
                        # Convert x from ns to current time units
                        x1 = ref_data['x_ns'] / self.state.nsunits
                        y1 = ref_data['y']
                    else:
                        # Reference doesn't exist, use zeros
                        # Check if data is available
                        if xy_data_array[0] is not None:
                            x1, y1 = xy_data_array[0]  # Get array shape from first channel
                            y1 = np.zeros_like(y1)
                        else:
                            # No data available yet, return empty results
                            return results
                else:
                    # It's a math channel - get from results
                    x1, y1 = results[ch1_idx]
            else:
                # It's a regular channel
                # Check if data is available
                if ch1_idx < len(xy_data_array) and xy_data_array[ch1_idx] is not None:
                    x1, y1 = xy_data_array[ch1_idx]
                else:
                    # No data available yet, return empty results
                    return results

            # Perform the operation
            try:
                if self.is_two_channel_operation(operation):
                    # Two-channel operations
                    ch2_idx = math_def['ch2']

                    # Get the data for channel 2 - check if it's a math channel, reference channel, or regular channel
                    if isinstance(ch2_idx, str):
                        if ch2_idx.startswith("Ref"):
                            # It's a reference channel - get from reference_data
                            ref_idx = int(ch2_idx[3:])
                            if ref_idx in self.main_window.reference_data:
                                ref_data = self.main_window.reference_data[ref_idx]
                                # Convert x from ns to current time units
                                x2 = ref_data['x_ns'] / self.state.nsunits
                                y2 = ref_data['y']
                            else:
                                # Reference doesn't exist, use zeros
                                # Check if data is available
                                if xy_data_array[0] is not None:
                                    x2, y2 = xy_data_array[0]  # Get array shape from first channel
                                    y2 = np.zeros_like(y2)
                                else:
                                    # No data available yet, skip this math channel
                                    continue
                        else:
                            # It's a math channel - get from results
                            x2, y2 = results[ch2_idx]
                    else:
                        # It's a regular channel
                        # Check if data is available
                        if ch2_idx < len(xy_data_array) and xy_data_array[ch2_idx] is not None:
                            x2, y2 = xy_data_array[ch2_idx]
                        else:
                            # No data available yet, skip this math channel
                            continue

                    # Ensure arrays have matching lengths (handle two-channel mode differences)
                    if len(y1) != len(y2):
                        # Upsample the shorter array to match the longer one
                        if len(y1) < len(y2):
                            # Interpolate y1 to match y2's length
                            y1 = np.interp(x2, x1, y1)
                            x1 = x2.copy()
                        else:
                            # Interpolate y2 to match y1's length
                            y2 = np.interp(x1, x2, y2)
                            x2 = x1.copy()

                    # Use x1 as the x-axis for the result (both are now the same length)
                    x_result = x1.copy()

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
                    # Use x1 as the x-axis for the result
                    x_result = x1.copy()

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
                    elif operation == 'Smooth':
                        # Moving average smoothing
                        window_size = 10  # this is how many samples we average
                        if self.state.doresamp: window_size *= self.state.doresamp
                        y_result = np.zeros_like(y1)
                        for i in range(len(y1)):
                            start = max(0, i - window_size // 2)
                            end = min(len(y1), i + window_size // 2 + 1)
                            y_result[i] = np.mean(y1[start:end])
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
        self.sync_measure_button_state()

        # Position the window to the right of the main window
        main_geometry = self.main_window.geometry()

        # Calculate position: 10 pixels to the right of main window's right edge
        x = main_geometry.x() + main_geometry.width() + 10

        # Align bottom edges
        y = main_geometry.y() + main_geometry.height() - self.height() - 32

        self.move(x, y)
