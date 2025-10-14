# history_window.py

from datetime import datetime
import sys, os
import numpy as np
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QFileDialog, QMessageBox
from PyQt5.QtCore import Qt, pyqtSignal


class HistoryWindow(QWidget):
    """Window showing a list of historical waveform events with timestamps."""

    # Signal emitted when user selects a historical event
    event_selected = pyqtSignal(int)  # Emits the index of the selected event
    # Signal emitted when the window is closed
    window_closed = pyqtSignal()
    # Signal emitted when history is loaded (passes the event buffer list)
    history_loaded = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("History Window")
        self.setWindowFlags(Qt.Window)
        self.resize(300, 600)

        # Setup layout
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        # Create list widget
        self.list_widget = QListWidget()
        # Use currentItemChanged for arrow key navigation support
        self.list_widget.currentItemChanged.connect(self.on_item_changed)

        layout.addWidget(self.list_widget)

        # Add buttons for save/load
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save History")
        self.load_button = QPushButton("Load History")
        self.save_button.clicked.connect(self.save_history)
        self.load_button.clicked.connect(self.load_history)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.load_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Store references to event data for easy access
        self.event_indices = []  # Maps list position to actual event buffer index
        self.current_event_buffer = []  # Store current buffer for saving

    def update_event_list(self, event_buffer):
        """
        Update the list with events from the circular buffer.

        Args:
            event_buffer: List of dicts with keys 'timestamp', 'xydata', 'xydatainterleaved'
        """
        # Store the current buffer for saving
        self.current_event_buffer = event_buffer

        self.list_widget.clear()
        self.event_indices.clear()

        # Events are stored oldest to newest, but we want to display newest first
        for i, event in enumerate(reversed(event_buffer)):
            if event is not None:
                timestamp = event['timestamp']
                # Format timestamp nicely
                time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # milliseconds

                item = QListWidgetItem(f"Event {len(event_buffer) - 1 - i}: {time_str}")
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

    def save_history(self):
        """Save the current history buffer to a file."""
        if not self.current_event_buffer:
            QMessageBox.warning(self, "No History", "No history events to save.")
            return

        # Open file dialog for save location
        options = QFileDialog.Options()
        if sys.platform.startswith('linux'):
            options |= QFileDialog.DontUseNativeDialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save History",
            "",
            "History Files (*.npz);;All Files (*)",
            options=options
        )

        if not file_path:
            return  # User cancelled

        if not os.path.splitext(file_path)[1]:  # Check if there's no extension
            file_path += ".npz"

        try:
            # Prepare data for saving
            num_events = len(self.current_event_buffer)
            timestamps = []
            xydata_list = []
            xydatainterleaved_list = []

            for event in self.current_event_buffer:
                if event is not None:
                    # Save timestamp as ISO format string
                    timestamps.append(event['timestamp'].isoformat())
                    # Ensure arrays are proper float64 numpy arrays
                    xydata_list.append(np.asarray(event['xydata'], dtype=np.float64))
                    xydatainterleaved_list.append(
                        np.asarray(event['xydatainterleaved'], dtype=np.float64)
                        if event['xydatainterleaved'] is not None
                        else np.array([], dtype=np.float64)
                    )

            # Save to npz file
            np.savez_compressed(
                file_path,
                num_events=num_events,
                timestamps=np.array(timestamps, dtype=object),
                xydata=np.array(xydata_list, dtype=object),
                xydatainterleaved=np.array(xydatainterleaved_list, dtype=object)
            )

            QMessageBox.information(self, "Success", f"Saved {num_events} events to {file_path}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save history: {str(e)}")

    def load_history(self):
        """Load history buffer from a file."""
        # Open file dialog for load location
        options = QFileDialog.Options()
        if sys.platform.startswith('linux'):
            options |= QFileDialog.DontUseNativeDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load History",
            "",
            "History Files (*.npz);;All Files (*)",
            options=options
        )

        if not file_path:
            return  # User cancelled

        try:
            # Load from npz file
            data = np.load(file_path, allow_pickle=True)

            num_events = int(data['num_events'])
            timestamps = data['timestamps']
            xydata_list = data['xydata']
            xydatainterleaved_list = data['xydatainterleaved']

            # Reconstruct event buffer
            event_buffer = []
            for i in range(num_events):
                # Ensure arrays are proper numpy arrays with float dtype
                xydata_array = np.asarray(xydata_list[i], dtype=np.float64)
                xydatainterleaved_array = np.asarray(xydatainterleaved_list[i], dtype=np.float64) if xydatainterleaved_list[i].size > 0 else None

                event = {
                    'timestamp': datetime.fromisoformat(timestamps[i]),
                    'xydata': xydata_array,
                    'xydatainterleaved': xydatainterleaved_array
                }
                event_buffer.append(event)

            # Emit signal to update main window's history buffer
            self.history_loaded.emit(event_buffer)

            # Update the display
            self.update_event_list(event_buffer)

            QMessageBox.information(self, "Success", f"Loaded {num_events} events from {file_path}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load history: {str(e)}")
