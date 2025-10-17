"""
Dialog for configuring dummy server waveform parameters.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QComboBox, QPushButton, QGroupBox)
from PyQt5.QtCore import Qt
import socket
import struct


class DummyServerConfigDialog(QDialog):
    """Dialog to configure dummy server waveform settings."""

    def __init__(self, parent, usbs):
        super().__init__(parent)
        self.usbs = usbs
        self.socket_usbs = []

        # Find all socket-based USB devices
        for usb in usbs:
            if hasattr(usb, 'socket_addr'):  # UsbSocketAdapter has socket_addr
                self.socket_usbs.append(usb)

        if not self.socket_usbs:
            return

        self.setWindowTitle("Dummy Server Configuration")
        self.setModal(False)
        self.resize(300, 200)

        # Channel config cache - stores the wave type for each channel
        self.channel_configs = {
            0: {"wave_type": "pulse"},  # Will be updated from server
            1: {"wave_type": "pulse"}
        }

        self.setup_ui()

        # Load initial config from server
        self.load_config_from_server()

    def setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout()

        # Channel selection group
        channel_group = QGroupBox("Channel Selection")
        channel_layout = QHBoxLayout()

        channel_layout.addWidget(QLabel("Channel:"))
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["0", "1"])
        self.channel_combo.currentIndexChanged.connect(self.on_channel_changed)
        channel_layout.addWidget(self.channel_combo)

        channel_group.setLayout(channel_layout)
        layout.addWidget(channel_group)

        # Wave type selection group
        wave_group = QGroupBox("Wave Type")
        wave_layout = QHBoxLayout()

        wave_layout.addWidget(QLabel("Type:"))
        self.wave_type_combo = QComboBox()
        self.wave_type_combo.addItems(["sine", "square", "pulse"])
        self.wave_type_combo.currentTextChanged.connect(self.on_wave_type_changed)
        wave_layout.addWidget(self.wave_type_combo)

        wave_group.setLayout(wave_layout)
        layout.addWidget(wave_group)

        # Buttons
        button_layout = QHBoxLayout()

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.apply_config)
        button_layout.addWidget(apply_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)
        layout.addStretch()

        self.setLayout(layout)

    def on_channel_changed(self):
        """Called when channel selection changes."""
        channel = int(self.channel_combo.currentText())
        wave_type = self.channel_configs[channel]["wave_type"]

        # Block signals to prevent triggering on_wave_type_changed
        self.wave_type_combo.blockSignals(True)
        index = self.wave_type_combo.findText(wave_type)
        if index >= 0:
            self.wave_type_combo.setCurrentIndex(index)
        self.wave_type_combo.blockSignals(False)

    def on_wave_type_changed(self, wave_type):
        """Called when wave type selection changes."""
        channel = int(self.channel_combo.currentText())
        self.channel_configs[channel]["wave_type"] = wave_type

    def load_config_from_server(self):
        """Query the dummy server for current configuration (placeholder for now)."""
        # For now, we'll assume default configuration
        # In the future, we could add a command to query the dummy server
        # For now just use the defaults
        pass

    def apply_config(self):
        """Send configuration to the dummy server."""
        if not self.socket_usbs:
            return

        # For each socket USB device, send configuration commands
        for usb in self.socket_usbs:
            # Send configuration for both channels
            for channel in [0, 1]:
                wave_type = self.channel_configs[channel]["wave_type"]

                # Create a custom command to configure the dummy server
                # We'll use opcode 12 (currently unused) for dummy server config
                # Format: [12, channel, wave_type_code, 0, 0, 0, 0, 0]
                wave_type_codes = {"sine": 0, "square": 1, "pulse": 2}
                wave_type_code = wave_type_codes.get(wave_type, 2)

                cmd = bytes([12, channel, wave_type_code, 0, 0, 0, 0, 0])

                try:
                    usb.send(cmd)
                    usb.recv(4)  # Read response
                except Exception as e:
                    print(f"Error sending config to dummy server: {e}")

        # Show confirmation
        print(f"Applied dummy server configuration:")
        for channel in [0, 1]:
            print(f"  Channel {channel}: {self.channel_configs[channel]['wave_type']}")
