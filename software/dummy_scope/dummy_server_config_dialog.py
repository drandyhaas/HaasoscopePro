"""
Dialog for configuring dummy server waveform parameters.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QComboBox, QPushButton, QGroupBox, QSpinBox,
                              QDoubleSpinBox, QFormLayout)
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
        self.resize(400, 500)

        # Channel config cache - stores the wave parameters for each channel
        # Default values match the dummy_server.py defaults
        self.channel_configs = {
            0: {
                "wave_type": "sine",
                "frequency": 3.2e6,  # 3.2 MHz
                "amplitude": 1500,
                "square_rise_fall_k": 10.0,
                "pulse_tau_rise": 10.0,
                "pulse_tau_decay": 50.0,
                "pulse_amplitude_min": 100,
                "pulse_amplitude_max": 2000
            },
            1: {
                "wave_type": "pulse",
                "frequency": 100e6,  # 100 MHz
                "amplitude": 1500,
                "square_rise_fall_k": 10.0,
                "pulse_tau_rise": 8.0,
                "pulse_tau_decay": 40.0,
                "pulse_amplitude_min": 10,
                "pulse_amplitude_max": 500
            }
        }

        self.setup_ui()

        # Load initial config from server
        self.load_config_from_server()

    def position_relative_to_main(self, main_window):
        """Position the dialog to the right of the main window with tops aligned."""
        main_geo = main_window.geometry()
        x = main_geo.x() + main_geo.width() + 10  # 10 pixels to the right
        y = main_geo.y()  # Align tops
        self.move(x, y)

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

        # Common parameters group (frequency and amplitude)
        common_group = QGroupBox("Common Parameters")
        common_layout = QFormLayout()

        # Frequency control (in Hz, displayed in scientific notation)
        self.frequency_spin = QDoubleSpinBox()
        self.frequency_spin.setDecimals(2)
        self.frequency_spin.setMinimum(1e3)  # 1 kHz minimum
        self.frequency_spin.setMaximum(1e9)  # 1 GHz maximum
        self.frequency_spin.setSingleStep(1e6)  # 1 MHz step
        self.frequency_spin.setValue(3.2e6)
        self.frequency_spin.setSuffix(" Hz")
        common_layout.addRow("Frequency:", self.frequency_spin)

        # Amplitude control (in ADC counts, 0-4095 for 12-bit ADC)
        self.amplitude_spin = QSpinBox()
        self.amplitude_spin.setMinimum(0)
        self.amplitude_spin.setMaximum(2047)  # Max ADC value
        self.amplitude_spin.setSingleStep(100)
        self.amplitude_spin.setValue(1500)
        self.amplitude_spin.setSuffix(" counts")
        common_layout.addRow("Amplitude:", self.amplitude_spin)

        common_group.setLayout(common_layout)
        layout.addWidget(common_group)

        # Square-specific parameters group
        self.square_group = QGroupBox("Square Wave Parameters")
        square_layout = QFormLayout()

        # Rise/fall time parameter k
        self.square_k_spin = QDoubleSpinBox()
        self.square_k_spin.setDecimals(2)
        self.square_k_spin.setMinimum(1.0)
        self.square_k_spin.setMaximum(1e6)
        self.square_k_spin.setSingleStep(1.0)
        self.square_k_spin.setValue(10.0)
        square_layout.addRow("Rise/Fall Sharpness (k):", self.square_k_spin)

        self.square_group.setLayout(square_layout)
        layout.addWidget(self.square_group)

        # Pulse-specific parameters group
        self.pulse_group = QGroupBox("Pulse Parameters")
        pulse_layout = QFormLayout()

        # Rise time
        self.tau_rise_spin = QDoubleSpinBox()
        self.tau_rise_spin.setDecimals(2)
        self.tau_rise_spin.setMinimum(0.1)
        self.tau_rise_spin.setMaximum(1000.0)
        self.tau_rise_spin.setSingleStep(1.0)
        self.tau_rise_spin.setValue(10.0)
        self.tau_rise_spin.setSuffix(" samples")
        pulse_layout.addRow("Rise Time:", self.tau_rise_spin)

        # Decay time
        self.tau_decay_spin = QDoubleSpinBox()
        self.tau_decay_spin.setDecimals(2)
        self.tau_decay_spin.setMinimum(0.1)
        self.tau_decay_spin.setMaximum(1000.0)
        self.tau_decay_spin.setSingleStep(1.0)
        self.tau_decay_spin.setValue(50.0)
        self.tau_decay_spin.setSuffix(" samples")
        pulse_layout.addRow("Decay Time:", self.tau_decay_spin)

        # Pulse amplitude min
        self.pulse_amp_min_spin = QSpinBox()
        self.pulse_amp_min_spin.setMinimum(0)
        self.pulse_amp_min_spin.setMaximum(2047)
        self.pulse_amp_min_spin.setSingleStep(10)
        self.pulse_amp_min_spin.setValue(100)
        self.pulse_amp_min_spin.setSuffix(" counts")
        pulse_layout.addRow("Amplitude Min:", self.pulse_amp_min_spin)

        # Pulse amplitude max
        self.pulse_amp_max_spin = QSpinBox()
        self.pulse_amp_max_spin.setMinimum(0)
        self.pulse_amp_max_spin.setMaximum(2047)
        self.pulse_amp_max_spin.setSingleStep(10)
        self.pulse_amp_max_spin.setValue(2000)
        self.pulse_amp_max_spin.setSuffix(" counts")
        pulse_layout.addRow("Amplitude Max:", self.pulse_amp_max_spin)

        self.pulse_group.setLayout(pulse_layout)
        layout.addWidget(self.pulse_group)

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

        # Initially show/hide wave-type-specific parameters based on wave type
        self.update_parameter_visibility()

    def on_channel_changed(self):
        """Called when channel selection changes."""
        # First, save current UI values to the previous channel's config
        self.save_ui_to_config()

        # Load the new channel's config into the UI
        channel = int(self.channel_combo.currentText())
        config = self.channel_configs[channel]

        # Block signals to prevent triggering callbacks
        self.wave_type_combo.blockSignals(True)
        self.frequency_spin.blockSignals(True)
        self.amplitude_spin.blockSignals(True)
        self.square_k_spin.blockSignals(True)
        self.tau_rise_spin.blockSignals(True)
        self.tau_decay_spin.blockSignals(True)
        self.pulse_amp_min_spin.blockSignals(True)
        self.pulse_amp_max_spin.blockSignals(True)

        # Update UI with channel config
        index = self.wave_type_combo.findText(config["wave_type"])
        if index >= 0:
            self.wave_type_combo.setCurrentIndex(index)

        self.frequency_spin.setValue(config["frequency"])
        self.amplitude_spin.setValue(config["amplitude"])
        self.square_k_spin.setValue(config["square_rise_fall_k"])
        self.tau_rise_spin.setValue(config["pulse_tau_rise"])
        self.tau_decay_spin.setValue(config["pulse_tau_decay"])
        self.pulse_amp_min_spin.setValue(config["pulse_amplitude_min"])
        self.pulse_amp_max_spin.setValue(config["pulse_amplitude_max"])

        # Unblock signals
        self.wave_type_combo.blockSignals(False)
        self.frequency_spin.blockSignals(False)
        self.amplitude_spin.blockSignals(False)
        self.square_k_spin.blockSignals(False)
        self.tau_rise_spin.blockSignals(False)
        self.tau_decay_spin.blockSignals(False)
        self.pulse_amp_min_spin.blockSignals(False)
        self.pulse_amp_max_spin.blockSignals(False)

        # Update parameter visibility based on wave type
        self.update_parameter_visibility()

    def on_wave_type_changed(self, wave_type):
        """Called when wave type selection changes."""
        # Update parameter visibility
        self.update_parameter_visibility()

    def update_parameter_visibility(self):
        """Show/hide wave-type-specific parameters based on wave type."""
        wave_type = self.wave_type_combo.currentText()
        self.square_group.setVisible(wave_type == "square")
        self.pulse_group.setVisible(wave_type == "pulse")

    def save_ui_to_config(self):
        """Save current UI values to the channel config cache."""
        channel = int(self.channel_combo.currentText())
        config = self.channel_configs[channel]

        config["wave_type"] = self.wave_type_combo.currentText()
        config["frequency"] = self.frequency_spin.value()
        config["amplitude"] = self.amplitude_spin.value()
        config["square_rise_fall_k"] = self.square_k_spin.value()
        config["pulse_tau_rise"] = self.tau_rise_spin.value()
        config["pulse_tau_decay"] = self.tau_decay_spin.value()
        config["pulse_amplitude_min"] = self.pulse_amp_min_spin.value()
        config["pulse_amplitude_max"] = self.pulse_amp_max_spin.value()

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

        # Save current UI values first
        self.save_ui_to_config()

        # For each socket USB device, send configuration commands
        for usb in self.socket_usbs:
            # Send configuration for both channels
            for channel in [0, 1]:
                config = self.channel_configs[channel]

                try:
                    # Send wave type (subcommand 0)
                    wave_type_codes = {"sine": 0, "square": 1, "pulse": 2}
                    wave_type_code = wave_type_codes.get(config["wave_type"], 2)
                    cmd = bytes([12, channel, 0, wave_type_code, 0, 0, 0, 0])
                    usb.send(cmd)
                    usb.recv(4)

                    # Send amplitude (subcommand 1)
                    amplitude = int(config["amplitude"])
                    amplitude_bytes = struct.pack("<H", amplitude)
                    cmd = bytes([12, channel, 1]) + amplitude_bytes + bytes([0, 0, 0])
                    usb.send(cmd)
                    usb.recv(4)

                    # Send frequency (subcommand 2)
                    frequency = float(config["frequency"])
                    frequency_bytes = struct.pack("<f", frequency)
                    cmd = bytes([12, channel, 2]) + frequency_bytes + bytes([0])
                    usb.send(cmd)
                    usb.recv(4)

                    # Send square wave parameters if wave type is square
                    if config["wave_type"] == "square":
                        # Send square rise/fall k parameter (subcommand 7)
                        k = float(config["square_rise_fall_k"])
                        k_bytes = struct.pack("<f", k)
                        cmd = bytes([12, channel, 7]) + k_bytes + bytes([0])
                        usb.send(cmd)
                        usb.recv(4)

                    # Send pulse parameters if wave type is pulse
                    if config["wave_type"] == "pulse":
                        # Send pulse rise time (subcommand 3)
                        tau_rise = float(config["pulse_tau_rise"])
                        tau_rise_bytes = struct.pack("<f", tau_rise)
                        cmd = bytes([12, channel, 3]) + tau_rise_bytes + bytes([0])
                        usb.send(cmd)
                        usb.recv(4)

                        # Send pulse decay time (subcommand 4)
                        tau_decay = float(config["pulse_tau_decay"])
                        tau_decay_bytes = struct.pack("<f", tau_decay)
                        cmd = bytes([12, channel, 4]) + tau_decay_bytes + bytes([0])
                        usb.send(cmd)
                        usb.recv(4)

                        # Send pulse amplitude min (subcommand 5)
                        amp_min = int(config["pulse_amplitude_min"])
                        amp_min_bytes = struct.pack("<H", amp_min)
                        cmd = bytes([12, channel, 5]) + amp_min_bytes + bytes([0, 0, 0])
                        usb.send(cmd)
                        usb.recv(4)

                        # Send pulse amplitude max (subcommand 6)
                        amp_max = int(config["pulse_amplitude_max"])
                        amp_max_bytes = struct.pack("<H", amp_max)
                        cmd = bytes([12, channel, 6]) + amp_max_bytes + bytes([0, 0, 0])
                        usb.send(cmd)
                        usb.recv(4)

                except Exception as e:
                    print(f"Error sending config to dummy server: {e}")
