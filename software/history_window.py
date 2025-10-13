# history_window.py

from datetime import datetime
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem
from PyQt5.QtCore import Qt, pyqtSignal


class HistoryWindow(QWidget):
    """Window showing a list of historical waveform events with timestamps."""

    # Signal emitted when user selects a historical event
    event_selected = pyqtSignal(int)  # Emits the index of the selected event
    # Signal emitted when the window is closed
    window_closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("History Window")
        self.setWindowFlags(Qt.Window)
        self.resize(400, 600)

        # Setup layout
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        # Create list widget
        self.list_widget = QListWidget()
        # Use currentItemChanged for arrow key navigation support
        self.list_widget.currentItemChanged.connect(self.on_item_changed)

        layout.addWidget(self.list_widget)
        self.setLayout(layout)

        # Store references to event data for easy access
        self.event_indices = []  # Maps list position to actual event buffer index

    def update_event_list(self, event_buffer):
        """
        Update the list with events from the circular buffer.

        Args:
            event_buffer: List of dicts with keys 'timestamp', 'xydata', 'xydatainterleaved'
        """
        self.list_widget.clear()
        self.event_indices.clear()

        # Events are stored oldest to newest, but we want to display newest first
        for i, event in enumerate(reversed(event_buffer)):
            if event is not None:
                timestamp = event['timestamp']
                # Format timestamp nicely
                time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # milliseconds

                item = QListWidgetItem(f"Event {len(event_buffer) - i}: {time_str}")
                self.list_widget.addItem(item)

                # Store the actual index in the buffer (reversed)
                self.event_indices.append(len(event_buffer) - 1 - i)

    def on_item_changed(self, current_item, previous_item):
        """Handle when the selected item changes (mouse click or arrow keys)."""
        if current_item is not None:
            row = self.list_widget.row(current_item)
            if row < len(self.event_indices):
                event_index = self.event_indices[row]
                self.event_selected.emit(event_index)

    def closeEvent(self, event):
        """Handle window close event."""
        self.window_closed.emit()
        event.accept()

    def position_relative_to_main(self, main_window):
        """Position the window to the left of the main window with tops aligned."""
        # Get main window frame geometry (includes window decorations)
        main_frame = main_window.frameGeometry()

        # Position to the left of main window with 10px gap
        x = main_frame.x() - self.width() - 10
        y = main_frame.y()

        self.move(x, y)
