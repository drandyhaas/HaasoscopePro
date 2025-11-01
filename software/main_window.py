# main_window.py

import time, math, sys
from datetime import datetime
from collections import deque
import numpy as np
import threading
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets, loadUiType
from PyQt5.QtWidgets import QMessageBox, QColorDialog, QFrame
from PyQt5.QtGui import QPalette, QColor

# Import all the refactored components
from scope_state import ScopeState
from hardware_controller import HardwareController
from data_processor import DataProcessor, format_freq
from plot_manager import PlotManager
from data_recorder import DataRecorder
from histogram_window import HistogramWindow
from xy_window import XYWindow
from zoom_window import ZoomWindow
from history_window import HistoryWindow
from measurements_manager import MeasurementsManager
from calibration import autocalibration, do_meanrms_calibration
from settings_manager import save_setup, load_setup
from math_channels_window import MathChannelsWindow
from frequency_calibration import FrequencyCalibration, save_fir_filter, load_fir_filter
from reference_manager import save_reference_lines, load_reference_lines
from dummy_scope.dummy_server_config_dialog import DummyServerConfigDialog
from update_checker import UpdateChecker

# Import remaining dependencies
from FFTWindow import FFTWindow
from SCPIsocket import DataSocket
from board import setupboard
from utils import get_pwd
from dummy_scope.USB_Socket import UsbSocketAdapter
import ftd2xx

pwd = get_pwd()
print(f"Current dir is {pwd}")


WindowTemplate, TemplateBaseClass = loadUiType(pwd + "/HaasoscopePro.ui")
class MainWindow(TemplateBaseClass):
    def __init__(self, usbs, testing_mode=False):
        super().__init__()

        # Testing mode flag (disables dynamic status bar updates)
        self.testing_mode = testing_mode

        # Check for dummy scope
        self.usbs = usbs
        self.dummy_scope = None
        for usb in self.usbs:
            if hasattr(usb, 'socket_addr'):  # UsbSocketAdapter has socket_addr
                #print(f"  -> Connected to dummy scope server at: {}")
                self.dummy_scope = usb.socket_addr

        # 1. Initialize core components
        self.state = ScopeState(num_boards=len(usbs), num_chan_per_board=2)
        print(f"Haasoscope Pro Software Version: {self.state.softwareversion:.2f}")
        self.controller = HardwareController(usbs, self.state)
        self.processor = DataProcessor(self.state)
        self.recorder = DataRecorder(self.state)

        # 2. Setup UI from template
        self.ui = WindowTemplate()
        self.ui.setupUi(self)

        # 3. Initialize UI/Plot manager
        self.plot_manager = PlotManager(self.ui, self.state)
        self.plot_manager.setup_plots()

        # 4. Connect all signals from UI widgets to slots in this class
        self._connect_signals()

        # 4b. Sync persistence UI to match state defaults (before any other operations)
        self.sync_persistence_ui()

        # 5. Initialize network socket and other components
        self.socket = None
        self.socket_thread = None
        self.fftui = None
        self.math_window = None
        self.xy_window = None
        self.zoom_window = None
        self.dummy_server_config_dialog = None
        # Initialize boardBox ComboBox with board numbers
        self.ui.boardBox.blockSignals(True)
        self.ui.boardBox.setMaxVisibleItems(self.state.num_board)
        self.ui.boardBox.clear()
        for i in range(self.state.num_board):
            # Check if this board is a dummy board (UsbSocketAdapter)
            if isinstance(self.usbs[i], UsbSocketAdapter):
                self.ui.boardBox.addItem(f"{i} (D)")
            else:
                self.ui.boardBox.addItem(str(i))
        self.ui.boardBox.blockSignals(False)
        self.setup_successful = False
        self.reference_data = {}  # Stores {channel_index: {'x_ns': array, 'y': array}}
        self.math_reference_data = {}  # Stores {math_channel_name: {'x_ns': array, 'y': array}}
        self.math_results_noresamp = {}  # Stores non-resampled math channel results for FFT and references

        # Initialize reference visibility to True for all channels by default
        num_channels = self.state.num_board * self.state.num_chan_per_board
        self.reference_visible = {i: True for i in range(num_channels)}
        self.math_reference_visible = {}  # Stores {math_channel_name: bool}

        # Histogram window for measurements
        self.histogram_window = HistogramWindow(self, self.plot_manager)

        # History window and circular buffer for storing past events
        self.history_window = HistoryWindow(self)
        self.history_window.event_selected.connect(self.on_history_event_selected)
        self.history_window.window_closed.connect(self.on_history_window_closed)
        self.history_window.history_loaded.connect(self.on_history_loaded)
        self.history_buffer = deque(maxlen=100)  # Circular buffer for 100 events
        self.displaying_history = False  # Flag to indicate if showing historical data
        self.current_history_index = None  # Index of currently displayed historical event
        self.was_running_before_history = False  # Track if we were running when history opened

        # 6. Initialize measurements manager (handles table, histogram, etc.)
        self.measurements = MeasurementsManager(self)

        # 7. Setup timers for data acquisition and measurement updates
        self.update_timer = QtCore.QTimer()
        self.update_timer.timeout.connect(self.update_plot_loop)
        self.measurement_timer = QtCore.QTimer()
        self.measurement_timer.timeout.connect(self.measurements.update_measurements_display)
        self.status_timer = QtCore.QTimer()
        self.status_timer.timeout.connect(self.update_status_bar)
        self.fan_timer = QtCore.QTimer()
        self.fan_timer.timeout.connect(self.controller.update_fan)

        # 7. Run the main initialization and hardware setup sequence
        if self.state.num_board > 0:
            try:
                setup_good = self.controller.setup_all_boards()
            except:
                setup_good = False
            if setup_good:
                self.controller.send_trigger_info_all()
                self.ui.ToffBox.setValue(self.state.toff)
                #self.ui.resampBox.setValue(self.state.doresamp)
                self.allocate_xy_data()
                self.controller.set_rolling(self.state.isrolling)
                self.select_channel()  # Updates UI and LEDs
                self.time_changed()
                self.open_socket()

                if self.state.num_board < 2:
                    self.ui.ToffBox.setEnabled(False)
                    self.ui.tadBox.setEnabled(False)
                    self.ui.actionDo_autocalibration.setEnabled(False)
                    self.ui.actionAuto_oversample_alignment.setEnabled(False)
                else:
                    # Update autocalibration enabled state based on initial board configuration
                    self.update_autocalibration_enabled()

                self.dostartstop()  # Start acquisition
                self.setup_successful = True
            else:
                # This block runs if setup_all_boards fails for any reason.
                title = "Board Setup Failed"
                message = (f"Board Setup Failed.\n\n"
                           "Please check the USB power and connection and restart the application.")
                self.handle_critical_error(title, message)
            # Firmware Version Check (only if setup passed)
            if self.setup_successful:
                req_firmware_ver = 28
                min_firmware_ver = min(self.state.firmwareversion)
                if min_firmware_ver < req_firmware_ver:
                    if not self.state.paused: self.dostartstop()
                    self.ui.runButton.setEnabled(False)
                    QMessageBox.warning(self, "Firmware Update Required",
                                        f"The firmware on a board is outdated.\n"
                                        f"Firmware {min_firmware_ver} found but v{req_firmware_ver}+ required\n\n"
                                        "Please update to the latest firmware.\n"
                                        "Data acquisition has been disabled.")
                if min_firmware_ver < 30:
                    self.ui.trigger_delay_box.setEnabled(False)
                    self.ui.trigger_holdoff_box.setEnabled(False)
                    print("Warning: Firmware v30+ needed for trigger delay and holdoff, disabling control.")

        else:  # Handle the case where no boards were found
            print("WARNING: No Haasoscope Pro boards found. Running in offline mode.")
            self.ui.runButton.setEnabled(False)
            self.ui.statusBar.showMessage("No hardware detected. Connect a device and restart.")
            self.setup_successful = False
            QMessageBox.warning(self, "Hardware Not Found",
                                "No Haasoscope Pro boards were detected.\n\n"
                                "The application is running in a disconnected state. "
                                "Please connect a device and restart the program to continue.")

        self.last_time = time.time()
        self.fps = None

        # DEFER UI sync until after the constructor is finished and the event loop starts
        QtCore.QTimer.singleShot(10, self._sync_initial_ui_state)

        # Perform an initial adjustment of the table geometry
        self.measurements.adjust_table_view_geometry()

        # Set column widths for the measurement table
        self.ui.tableView.setColumnWidth(0, 210)  # Measurement name column, wider for X button + name
        self.ui.tableView.setColumnWidth(1, 60)  # Measurement value column
        self.ui.tableView.setColumnWidth(2, 60)  # Measurement avg column
        self.ui.tableView.setColumnWidth(3, 60)  # Measurement rms column

        # Show main window
        self.show()

        # Check for software updates (non-blocking, runs in background thread)
        self.update_checker = UpdateChecker(self.state.softwareversion)
        self.update_checker.update_available.connect(self._show_update_notification)
        self.update_checker.check_for_updates()

    def _sync_initial_ui_state(self):
        """A one-time function to sync the UI's visual state after the window has loaded."""
        # This function is called just after the main event loop starts.
        self.ui.rollingButton.setChecked(bool(self.state.isrolling))
        self.ui.rollingButton.setText(" Auto " if self.state.isrolling else " Normal ")
        self.ui.runButton.setText(" Run ")
        self.controller.update_fan() # update fan once right away
        self.fan_timer.start(10031) # every 10 seconds or so afterwares
        self.ui.actionPan_and_zoom.setChecked(False)
        self.plot_manager.set_pan_and_zoom(False)
        # Initialize line width from state
        self.ui.linewidthBox.setValue(self.state.line_width)
        self.line_width_changed(self.state.line_width)
        # Initialize persistence UI controls from state
        self.sync_persistence_ui()

    def _sync_board_settings_to_hardware(self, board_idx):
        """
        Re-applies all stored state settings (gain, offset, etc.) for a specific
        board to the physical hardware. Called after a disruptive mode change.
        """
        s = self.state
        #print(f"Re-syncing hardware settings for board {board_idx}...")

        # Sync settings for both channels on this board
        for chan_on_board in range(s.num_chan_per_board):
            global_chan_idx = board_idx * s.num_chan_per_board + chan_on_board

            # Re-apply Gain
            self.controller.set_channel_gain(board_idx, chan_on_board, s.gain[global_chan_idx])

            # Re-apply Offset (this requires calculating the scaling factor)
            scaling = 1000 * s.VperD[global_chan_idx] / 160.0
            if s.acdc[global_chan_idx]:
                scaling *= 245.0 / 160.0
            final_scaling = scaling / s.tenx[global_chan_idx]
            self.controller.set_channel_offset(board_idx, chan_on_board, s.offset[global_chan_idx], final_scaling)

            # Re-apply AC/DC, Impedance, and Attenuation
            self.controller.set_acdc(board_idx, chan_on_board, s.acdc[global_chan_idx])
            self.controller.set_mohm(board_idx, chan_on_board, s.mohm[global_chan_idx])
            self.controller.set_att(board_idx, chan_on_board, s.att[global_chan_idx])

    def _connect_signals(self):
        """Connect all UI element signals to their corresponding slots."""
        # Main controls
        self.ui.runButton.clicked.connect(self.dostartstop)
        self.ui.singleButton.clicked.connect(self.single_clicked)
        self.ui.rollingButton.clicked.connect(self.rolling_clicked)

        # Timebase controls
        self.ui.timeslowButton.clicked.connect(self.time_slow)
        self.ui.timefastButton.clicked.connect(self.time_fast)
        self.ui.depthBox.valueChanged.connect(self.depth_changed)

        # Trigger controls
        self.ui.threshold.valueChanged.connect(self.trigger_level_changed)
        self.ui.thresholdLabel.clicked.connect(lambda: self.trigger_level_changed(127))
        self.ui.thresholdPos.valueChanged.connect(self.trigger_pos_changed)
        self.ui.thresholdPosLabel.clicked.connect(self.trigger_pos_reset)
        self.ui.thresholdDelta.valueChanged.connect(self.trigger_delta_changed)
        self.ui.risingfalling_comboBox.currentIndexChanged.connect(self.rising_falling_changed)
        self.ui.totBox.valueChanged.connect(self.tot_changed)
        self.ui.trigger_delay_box.valueChanged.connect(self.trigger_delay_changed)
        self.ui.trigger_holdoff_box.valueChanged.connect(self.trigger_holdoff_changed)

        # Channel controls
        self.ui.boardBox.currentIndexChanged.connect(self.select_channel)
        self.ui.chanBox.currentIndexChanged.connect(self.select_channel)
        self.ui.chanonCheck.stateChanged.connect(self.chanon_changed)
        self.ui.gainBox.valueChanged.connect(self.gain_changed)
        self.ui.offsetBox.valueChanged.connect(self.offset_changed)
        self.ui.skewBox.valueChanged.connect(self.skew_changed)
        self.ui.channameEdit.editingFinished.connect(self.channel_name_changed)
        self.ui.acdcCheck.stateChanged.connect(self.acdc_changed)
        self.ui.ohmCheck.stateChanged.connect(self.mohm_changed)
        self.ui.attCheck.stateChanged.connect(self.att_changed)
        self.ui.tenxCheck.stateChanged.connect(self.tenx_changed)
        self.ui.twochanCheck.clicked.connect(self.twochan_changed)
        self.ui.oversampCheck.stateChanged.connect(self.oversamp_changed)
        self.ui.interleavedCheck.stateChanged.connect(self.interleave_changed)
        # Make chanColor clickable to change channel color
        self.ui.chanColor.installEventFilter(self)
        self.ui.chanColor.viewport().installEventFilter(self)

        # Processing and Display controls
        self.ui.actionDrawing.triggered.connect(self.drawing_toggled)
        self.ui.actionGrid.triggered.connect(lambda checked: self.plot_manager.set_grid(checked))
        self.ui.actionMarkers.triggered.connect(self.toggle_markers_slot)
        self.ui.actionPan_and_zoom.triggered.connect(lambda checked: self.plot_manager.set_pan_and_zoom(checked))
        self.ui.actionVoltage_axis.triggered.connect(lambda checked: self.plot_manager.right_axis.setVisible(checked))
        self.ui.actionCursors.triggered.connect(lambda checked: self.plot_manager.show_cursors(checked))
        self.ui.actionSnap_to_waveform.triggered.connect(lambda checked: self.plot_manager.on_snap_toggled(checked))
        self.ui.actionTime_relative.triggered.connect(lambda checked: self.plot_manager.update_cursor_display())
        self.ui.actionTrigger_info.triggered.connect(lambda checked: self.plot_manager.update_trigger_threshold_display())
        self.ui.actionPeak_detect.triggered.connect(lambda checked: self.plot_manager.set_peak_detect(checked))
        self.ui.actionChannel_name_legend.triggered.connect(lambda checked: self.plot_manager.update_legend())
        self.ui.linewidthBox.valueChanged.connect(self.line_width_changed)
        self.ui.lpfBox.currentIndexChanged.connect(self.lpf_changed)
        self.ui.resampBox.valueChanged.connect(self.resamp_changed)
        self.ui.fftCheck.stateChanged.connect(self.fft_clicked)
        self.ui.persistTbox.valueChanged.connect(self.set_persistence)
        self.ui.persistAvgCheck.stateChanged.connect(self.set_average_line_pen)
        self.ui.persistlinesCheck.clicked.connect(self.set_average_line_pen)
        self.ui.persistheatCheck.clicked.connect(self.set_average_line_pen)
        self.ui.actionLine_color.triggered.connect(self.change_channel_color)
        self.ui.actionHigh_resolution.triggered.connect(self.high_resolution_toggled)

        # Advanced/Hardware controls
        self.ui.pllresetButton.clicked.connect(self.dopllreset)
        self.ui.tadBox.valueChanged.connect(self.tad_changed)
        self.ui.ToffBox.valueChanged.connect(lambda val: setattr(self.state, 'toff', val))
        self.ui.Auxout_comboBox.currentIndexChanged.connect(self.auxout_changed)
        self.ui.actionToggle_PLL_controls.triggered.connect(self.toggle_pll_controls)
        self.ui.actionOversampling_controls.triggered.connect(self.toggle_oversampling_controls)
        self.ui.actionClock_reset.triggered.connect(lambda: self.controller.adfreset(self.state.activeboard))
        self.ui.upposButton0.clicked.connect(self.uppos)
        self.ui.upposButton1.clicked.connect(self.uppos1)
        self.ui.upposButton2.clicked.connect(self.uppos2)
        self.ui.upposButton3.clicked.connect(self.uppos3)
        self.ui.upposButton4.clicked.connect(self.uppos4)
        self.ui.downposButton0.clicked.connect(self.downpos)
        self.ui.downposButton1.clicked.connect(self.downpos1)
        self.ui.downposButton2.clicked.connect(self.downpos2)
        self.ui.downposButton3.clicked.connect(self.downpos3)
        self.ui.downposButton4.clicked.connect(self.downpos4)
        self.ui.actionForce_split.triggered.connect(self.force_split_toggled)
        self.ui.actionForce_switch_clocks.triggered.connect(self.force_switch_clocks_triggered)
        if self.dummy_scope is not None:
            self.ui.actionConfigure_dummy_scope.triggered.connect(self.open_dummy_server_config)
            self.ui.actionConfigure_dummy_scope.setEnabled(True)

        # Menu actions
        self.ui.actionAbout.triggered.connect(self.about_dialog)
        self.ui.actionTake_screenshot.triggered.connect(self.take_screenshot)
        self.ui.actionRecord.triggered.connect(self.toggle_recording)
        self.ui.actionSave_setup.triggered.connect(self.save_setup)
        self.ui.actionLoad_setup.triggered.connect(self.load_setup)
        self.ui.actionVerify_firmware.triggered.connect(self.verify_firmware)
        self.ui.actionUpdate_firmware.triggered.connect(self.update_firmware)
        self.ui.actionDo_autocalibration.triggered.connect(lambda: autocalibration(self))
        self.ui.actionOversampling_mean_and_RMS.triggered.connect(lambda: do_meanrms_calibration(self))
        self.ui.actionToggle_trig_stabilizer.triggered.connect(self.trig_stabilizer_toggled)
        self.ui.actionToggle_extra_trig_stabilizer.triggered.connect(self.extra_trig_stabilizer_toggled)
        self.ui.actionPulse_stabilizer.triggered.connect(self.pulse_stabilizer_toggled)
        self.ui.actionMeasure_10_MHz_square_FIR.triggered.connect(self.measure_fir_calibration)
        self.ui.actionApply_FIR_corrections.triggered.connect(self.fir_correction_toggled)
        self.ui.actionSave_FIR_filter.triggered.connect(self.save_fir_filter)
        self.ui.actionLoad_FIR_filter.triggered.connect(self.load_fir_filter)
        self.ui.actionPolynomial_filtering.triggered.connect(self.polynomial_filtering_toggled)

        # Plot manager signals
        self.plot_manager.vline_dragged_signal.connect(self.on_vline_dragged)
        self.plot_manager.hline_dragged_signal.connect(self.on_hline_dragged)
        self.plot_manager.curve_clicked_signal.connect(self.on_curve_clicked)
        self.plot_manager.math_curve_clicked_signal.connect(self.on_math_curve_clicked)

        # Reference menu actions
        self.ui.actionTake_Reference.triggered.connect(self.take_reference_waveform)
        self.ui.actionShow_Reference.triggered.connect(self.toggle_reference_waveform_visibility)
        self.ui.actionClear_all.triggered.connect(self.clear_all_references)
        self.ui.actionSave_reference_lines.triggered.connect(self.save_reference_lines_slot)
        self.ui.actionLoad_reference_lines.triggered.connect(self.load_reference_lines_slot)

        # View menu actions
        self.ui.actionXY_Plot.triggered.connect(self.toggle_xy_view_slot)
        self.ui.actionZoom_window.triggered.connect(self.toggle_zoom_window_slot)
        self.ui.actionMath_channels.triggered.connect(self.open_math_channels)
        self.ui.actionHistory_window.triggered.connect(self.open_history_window)

        # Plot manager signals
        self.plot_manager.curve_clicked_signal.connect(self.on_curve_clicked)
        self.plot_manager.zoom_region_changed_signal.connect(self.on_zoom_region_changed)

        # Connect the controller's error signal to our handler slot
        self.controller.signals.critical_error_occurred.connect(self.handle_critical_error)

    def _update_channel_mode_ui(self):
        """
        A centralized function to synchronize all UI elements related to the
        channel mode (Single, Two Channel, Oversampling).
        """
        s = self.state
        if s.num_board<1: return

        # 1. Determine the CHECKED state of the oversampling box.
        #    The box should remain checked if the PAIR is in oversampling mode,
        #    regardless of which board in the pair is currently selected.
        primary_board_of_pair = (s.activeboard // 2) * 2
        is_pair_oversampling = s.dooversample[primary_board_of_pair]
        # Block signals to prevent triggering oversamp_changed when switching boards
        self.ui.oversampCheck.blockSignals(True)
        self.ui.oversampCheck.setChecked(is_pair_oversampling)
        self.ui.oversampCheck.blockSignals(False)

        # Update interleavedCheck to reflect the interleaved state of the board pair
        is_pair_interleaved = s.dointerleaved[primary_board_of_pair]
        self.ui.interleavedCheck.blockSignals(True)
        self.ui.interleavedCheck.setChecked(is_pair_interleaved)
        self.ui.interleavedCheck.blockSignals(False)

        # 2. Determine the ENABLED state of the oversampling box.
        #    The user should only be able to CHANGE the oversampling setting
        #    when the primary (even) board of a pair is selected.
        can_change_oversampling = (s.num_board > 1 and s.activeboard % 2 == 0 and not s.dotwochannel[s.activeboard])
        self.ui.oversampCheck.setEnabled(can_change_oversampling)
        self.ui.interleavedCheck.setEnabled(can_change_oversampling and self.ui.oversampCheck.isChecked())

        # Update chanBox ComboBox based on two-channel mode
        current_chan = self.ui.chanBox.currentIndex()
        self.ui.chanBox.blockSignals(True)
        if s.dotwochannel[s.activeboard]:
            # Two-channel mode: show channels 0 and 1
            self.ui.chanBox.setMaxVisibleItems(s.num_chan_per_board)
            self.ui.chanBox.clear()
            for i in range(self.state.num_chan_per_board):
                self.ui.chanBox.addItem(str(i))
            # Restore previous selection if valid
            if current_chan < s.num_chan_per_board:
                self.ui.chanBox.setCurrentIndex(current_chan)
            else:
                self.ui.chanBox.setCurrentIndex(0)
        else:
            # Single-channel mode: only channel 0
            self.ui.chanBox.setMaxVisibleItems(1)
            self.ui.chanBox.clear()
            for i in range(1):
                self.ui.chanBox.addItem(str(i))
            self.ui.chanBox.setCurrentIndex(0)
        self.ui.chanBox.blockSignals(False)

        # Enable/disable Ch 1 trigger options based on two-channel mode
        model = self.ui.risingfalling_comboBox.model()
        is_two_channel = s.dotwochannel[s.activeboard]
        # Indices 2 and 3 are "Rising (Ch 1)" and "Falling (Ch 1)"
        for idx in [2, 3]:
            item = model.item(idx)
            if item:
                item.setEnabled(is_two_channel)

        # Loop through all boards to set plot line visibility
        for board_idx in range(s.num_board):
            # The index of the second channel on this board
            ch1_idx = board_idx * s.num_chan_per_board + 1

            # Update channel enabled state based on two-channel mode
            if not s.dotwochannel[board_idx]:
                # In single-channel mode, ch1 doesn't exist - must be disabled
                s.channel_enabled[ch1_idx] = False
                self.plot_manager.lines[ch1_idx].clear()
            # In two-channel mode: don't force enable - let user control visibility

            # Apply correct visibility based on all state (including persistence)
            self.update_channel_visibility(ch1_idx)

        # Update reference menu states based on initial data
        self.update_clear_all_reference_state()

        # Update persistence UI to reflect the current channel's settings
        # (important when switching modes causes channel selection to change)
        self.sync_persistence_ui()

        # Also update visibility for the active channel
        self.update_channel_visibility(s.activexychannel)

    def open_socket(self):
        print("Starting SCPI socket thread...")
        self.socket = DataSocket()
        self.socket.hspro = self
        self.socket.runthethread = True
        self.socket_thread = threading.Thread(target=self.socket.open_socket, args=(10,))
        self.socket_thread.start()

    def close_socket(self):
        """Safely stops and joins the SCPI socket thread before exiting."""
        if self.socket is not None:
            print("Closing SCPI socket...")
            self.socket.runthethread = False
            # Check if the thread is alive before trying to join it
            if self.socket_thread and self.socket_thread.is_alive():
                self.socket_thread.join()

    # #########################################################################
    # ## Core Application Logic
    # #########################################################################

    def sync_depth_ui_from_state(self):
        """Ensures the depthBox UI widget always matches the state.expect_samples."""
        if self.ui.depthBox.value() != self.state.expect_samples:
            self.ui.depthBox.blockSignals(True)
            self.ui.depthBox.setValue(self.state.expect_samples)
            self.ui.depthBox.blockSignals(False)

    def trig_stabilizer_toggled(self, checked):
        """Updates the state for the board-level trigger stabilizer."""
        self.state.trig_stabilizer_enabled = checked

    def extra_trig_stabilizer_toggled(self, checked):
        """Updates the state for the per-line trigger stabilizer."""
        self.state.extra_trig_stabilizer_enabled = checked

    def pulse_stabilizer_toggled(self, checked):
        """Updates the state for pulse stabilizer mode (uses edge midpoint instead of threshold)."""
        self.state.pulse_stabilizer_enabled[self.state.activeboard] = checked

    def fir_correction_toggled(self, checked):
        """Toggle FIR frequency response correction on/off."""
        self.state.fir_correction_enabled = checked
        if checked:
            # Check if calibration data is available for the current mode
            is_oversampling = self.state.dooversample[self.state.activeboard]
            is_interleaved = self.state.dointerleaved[self.state.activeboard]
            is_twochannel = self.state.dotwochannel[self.state.activeboard]

            if is_oversampling and is_interleaved:
                has_corrections = self.state.fir_coefficients_interleaved is not None
                mode_name = "Interleaved oversampling"
            elif is_oversampling:
                has_corrections = (self.state.fir_coefficients_oversample[0] is not None and
                                  self.state.fir_coefficients_oversample[1] is not None)
                mode_name = "Oversampling"
            elif is_twochannel:
                has_corrections = self.state.fir_coefficients_twochannel is not None
                mode_name = "Two-channel"
            else:
                has_corrections = self.state.fir_coefficients is not None
                mode_name = "Normal"

            if not has_corrections:
                QMessageBox.warning(self, "FIR Correction",
                                  f"No calibration data available for {mode_name} mode.\n\n"
                                  f"Please measure calibration in {mode_name} mode first using a 10 MHz square wave.")
                self.ui.actionApply_FIR_corrections.setChecked(False)
                self.state.fir_correction_enabled = False

    def polynomial_filtering_toggled(self, checked):
        """Toggle Savitzky-Golay polynomial filtering on/off."""
        self.state.polynomial_filtering_enabled = checked

    def measure_fir_calibration(self):
        """Measure FIR calibration using 10 MHz square wave input."""
        # Verify we're not paused
        if self.state.paused:
            QMessageBox.warning(self, "FIR Calibration",
                              "Please unpause (start acquisition) before measuring calibration.")
            return

        # Verify we're at maximum sample rate (downsample = 0)
        if self.state.downsample > 0:
            QMessageBox.warning(self, "FIR Calibration",
                              "FIR calibration must be performed at maximum sample rate.\n\n"
                              "Please set Downsample to 0 (no downsampling) before measuring calibration.\n\n"
                              "After calibration, the corrections will be applied at all sample rates, "
                              "though accuracy may be reduced at heavily downsampled rates.")
            return

        # Check current mode of active board
        oversample_mode = self.state.dooversample[self.state.activeboard]
        interleaved_mode = self.state.dointerleaved[self.state.activeboard]
        twochannel_mode = self.state.dotwochannel[self.state.activeboard]

        if oversample_mode and interleaved_mode:
            # Interleaved oversampling mode: calibrate the interleaved waveform at 2x sample rate
            # Determine board pair (even board N and odd board N+1)
            if self.state.activeboard % 2 == 0:
                board_N = self.state.activeboard
            else:
                board_N = self.state.activeboard - 1
            board_N1 = board_N + 1

            reply = QMessageBox.question(self, "FIR Calibration - Interleaved Mode",
                                  f"Interleaved oversampling detected!\n\n"
                                  f"The interleaved waveform at 6.4 GHz will be calibrated.\n\n"
                                  f"Connect 10 MHz square wave to input.\n"
                                  f"(Signal is duplicated to both boards by hardware)\n\n"
                                  f"Proceed with calibration?",
                                  QMessageBox.Yes | QMessageBox.Cancel,
                                  QMessageBox.Yes)
            if reply == QMessageBox.Cancel:
                return

        elif oversample_mode:
            # Oversampling only (not interleaved): calibrate boards separately
            # Determine board pair (even board N and odd board N+1)
            if self.state.activeboard % 2 == 0:
                board_N = self.state.activeboard
            else:
                board_N = self.state.activeboard - 1
            board_N1 = board_N + 1

            reply = QMessageBox.question(self, "FIR Calibration - Oversampling Mode",
                                  f"Oversampling detected!\n\n"
                                  f"Board {board_N} and Board {board_N1} will be calibrated separately.\n\n"
                                  f"Connect 10 MHz square wave to input.\n"
                                  f"(Signal is duplicated to both boards by hardware)\n\n"
                                  f"Proceed with calibration?",
                                  QMessageBox.Yes | QMessageBox.Cancel,
                                  QMessageBox.Yes)
            if reply == QMessageBox.Cancel:
                return

        elif twochannel_mode:
            # Two-channel mode: sample rate is halved (1.6 GHz per channel instead of 3.2 GHz)
            # Determine which channel is active (display as 1-based for user)
            active_channel_display = self.state.activexychannel + 1
            reply = QMessageBox.question(self, "FIR Calibration - Two-Channel Mode",
                                  f"Two-channel mode detected!\n\n"
                                  f"Sample rate is 1.6 GHz per channel (half of normal 3.2 GHz).\n\n"
                                  f"Connect 10 MHz square wave to active channel (CH{active_channel_display}).\n"
                                  f"Both channels share hardware, so calibration applies to both.\n\n"
                                  f"Proceed with calibration?",
                                  QMessageBox.Yes | QMessageBox.Cancel,
                                  QMessageBox.Yes)
            if reply == QMessageBox.Cancel:
                return

        else:
            # Normal mode
            reply = QMessageBox.question(self, "FIR Calibration - Normal Mode",
                                  f"Normal mode detected.\n\n"
                                  f"Connect 10 MHz square wave to input.\n\n"
                                  f"Proceed with calibration?",
                                  QMessageBox.Yes | QMessageBox.Cancel,
                                  QMessageBox.Yes)
            if reply == QMessageBox.Cancel:
                return

        # Create calibration object
        fir_cal = FrequencyCalibration()
        num_averages = fir_cal.num_averages

        # Temporarily increase depth for better frequency resolution during calibration
        # Use 640 samples: ensures 10 MHz harmonics land exactly on FFT bin centers
        # Normal mode (3.2 GHz): Δf = 3.2 GHz / 640 = 5 MHz → 10 MHz is bin 2, 30 MHz is bin 6, etc.
        # Interleaved (6.4 GHz): Δf = 6.4 GHz / 640 = 10 MHz → 10 MHz is bin 1, 30 MHz is bin 3, etc.
        old_depth = self.state.expect_samples
        calibration_depth = 640  # Optimized for 10 MHz harmonics landing on bin centers
        if old_depth != calibration_depth:
            self.state.expect_samples = calibration_depth
            self.allocate_xy_data()
            self.controller.send_trigger_info_all()
            print(f"FIR calibration: Temporarily set depth to {calibration_depth} (was {old_depth}) for bin alignment with 10 MHz harmonics")

        # Temporarily disable drawing for faster capture
        old_dodrawing = self.state.dodrawing
        self.state.dodrawing = False

        # Helper function to capture waveforms from a specific channel
        def capture_board_waveforms(board_idx, num_averages, channel_idx=None):
            captured = []
            # Default to channel 0 of the board if not specified
            if channel_idx is None:
                channel_idx = board_idx * self.state.num_chan_per_board

            for i in range(num_averages):

                # Print progress at 10% intervals
                if i % 100 == 0: print(f"Capturing waveforms: {i}/{num_averages}")

                # Get event data
                raw_data_map, rx_len = self.controller.get_event()
                if not raw_data_map:
                    continue

                # Process all boards
                for b_idx in range(self.state.num_board):
                    if b_idx in raw_data_map:
                        self.processor.process_board_data(
                            raw_data_map[b_idx],
                            b_idx,
                            self.xydata
                        )

                # Extract y-data from the specified channel
                if channel_idx < len(self.xydata) and self.xydata[channel_idx] is not None:
                    y_data = self.xydata[channel_idx][1].copy()
                    captured.append(y_data)

            return captured

        try:
            if oversample_mode and interleaved_mode:
                # Interleaved oversampling mode: capture the interleaved waveform at 2x sample rate
                captured_waveforms_interleaved = []

                for i in range(num_averages):

                    # Print progress at 10% intervals
                    if i % 100 == 0: print(f"Capturing interleaved waveforms: {i}/{num_averages}")

                    # Get event data
                    raw_data_map, rx_len = self.controller.get_event()
                    if not raw_data_map:
                        continue

                    # Process all boards
                    for b_idx in range(self.state.num_board):
                        if b_idx in raw_data_map:
                            self.processor.process_board_data(
                                raw_data_map[b_idx],
                                b_idx,
                                self.xydata
                            )

                    # Manually interleave the data (same logic as in plot_manager.py)
                    # The processor doesn't automatically create xydatainterleaved during event processing
                    channel_idx_N = board_N * self.state.num_chan_per_board
                    channel_idx_N1 = board_N1 * self.state.num_chan_per_board

                    if channel_idx_N < len(self.xydata) and self.xydata[channel_idx_N] is not None:
                        if channel_idx_N1 < len(self.xydata) and self.xydata[channel_idx_N1] is not None:
                            # Get data from both boards
                            primary_data = self.xydata[channel_idx_N][1].copy()
                            secondary_data = self.xydata[channel_idx_N1][1].copy()

                            # Create interleaved array
                            interleaved_length = len(primary_data) + len(secondary_data)
                            y_interleaved = np.zeros(interleaved_length)
                            y_interleaved[0::2] = primary_data
                            y_interleaved[1::2] = secondary_data

                            captured_waveforms_interleaved.append(y_interleaved)

                if len(captured_waveforms_interleaved) < 10:
                    QMessageBox.warning(self, "FIR Calibration",
                                      f"Only captured {len(captured_waveforms_interleaved)} interleaved waveforms. Need at least 10.")
                    return

            elif oversample_mode:
                # Oversampling only (not interleaved): capture both boards separately
                # (Hardware duplicates signal to both boards)
                captured_waveforms_N = []
                captured_waveforms_N1 = []

                for i in range(num_averages):

                    # Print progress at 10% intervals
                    if i % 100 == 0: print(f"Capturing oversample waveforms: {i}/{num_averages}")

                    # Get event data
                    raw_data_map, rx_len = self.controller.get_event()
                    if not raw_data_map:
                        continue

                    # Process all boards
                    for b_idx in range(self.state.num_board):
                        if b_idx in raw_data_map:
                            self.processor.process_board_data(
                                raw_data_map[b_idx],
                                b_idx,
                                self.xydata
                            )

                    # Extract y-data from both boards
                    channel_idx_N = board_N * self.state.num_chan_per_board
                    channel_idx_N1 = board_N1 * self.state.num_chan_per_board

                    if channel_idx_N < len(self.xydata) and self.xydata[channel_idx_N] is not None:
                        y_data_N = self.xydata[channel_idx_N][1].copy()
                        captured_waveforms_N.append(y_data_N)

                    if channel_idx_N1 < len(self.xydata) and self.xydata[channel_idx_N1] is not None:
                        y_data_N1 = self.xydata[channel_idx_N1][1].copy()
                        captured_waveforms_N1.append(y_data_N1)

                if len(captured_waveforms_N) < 10:
                    QMessageBox.warning(self, "FIR Calibration",
                                      f"Only captured {len(captured_waveforms_N)} waveforms from Board {board_N}. Need at least 10.")
                    return

                if len(captured_waveforms_N1) < 10:
                    QMessageBox.warning(self, "FIR Calibration",
                                      f"Only captured {len(captured_waveforms_N1)} waveforms from Board {board_N1}. Need at least 10.")
                    return

            elif twochannel_mode:
                # Two-channel mode: capture from active channel at halved sample rate (1.6 GHz)
                # Both channels share the same hardware path, so one calibration applies to both
                captured_waveforms_twochannel = capture_board_waveforms(
                    self.state.activeboard, num_averages, channel_idx=self.state.activexychannel)

                if len(captured_waveforms_twochannel) < 10:
                    QMessageBox.warning(self, "FIR Calibration",
                                      f"Only captured {len(captured_waveforms_twochannel)} waveforms. Need at least 10 for good calibration.")
                    return

            else:
                # Normal mode: capture from channel 0 (board 0, channel 0)
                captured_waveforms = capture_board_waveforms(0, num_averages)

                if len(captured_waveforms) < 10:
                    QMessageBox.warning(self, "FIR Calibration",
                                      f"Only captured {len(captured_waveforms)} waveforms. Need at least 10 for good calibration.")
                    return

            # Restore drawing and depth
            self.state.dodrawing = old_dodrawing
            if old_depth != calibration_depth:
                self.state.expect_samples = old_depth
                self.allocate_xy_data()
                self.controller.send_trigger_info_all()
                self.sync_depth_ui_from_state()
                print(f"FIR calibration: Restored depth to {old_depth}")

            # Compute sample rate in Hz
            sample_rate_hz = self.state.samplerate * 1e9  # Convert GHz to Hz

            if oversample_mode and interleaved_mode:
                # Run calibration for interleaved data at 2x sample rate
                sample_rate_hz_interleaved = sample_rate_hz * 2  # 6.4 GHz
                result = fir_cal.calibrate_from_data(captured_waveforms_interleaved, sample_rate_hz_interleaved, is_interleaved=True)

                if result['success']:
                    # Store interleaved calibration in state
                    self.state.fir_coefficients_interleaved = result['fir_coefficients']
                    self.state.fir_calibration_samplerate_interleaved = sample_rate_hz_interleaved
                    self.state.fir_freq_response_interleaved = result['freq_response']

                    # Show success message
                    message = (f"Interleaved FIR Calibration Complete!\n\n"
                             f"Calibrated at {sample_rate_hz_interleaved/1e9:.2f} GHz\n\n"
                             f"{result['message']}")
                    QMessageBox.information(self, "FIR Calibration Complete", message)

                    # Enable the apply checkbox if it's not already enabled
                    if not self.state.fir_correction_enabled:
                        self.ui.actionApply_FIR_corrections.setEnabled(True)  # Enable so it can be unchecked
                        self.ui.actionApply_FIR_corrections.setChecked(True)
                        self.state.fir_correction_enabled = True
                else:
                    QMessageBox.critical(self, "FIR Calibration Failed", result['message'])

            elif oversample_mode:
                # Run calibration for both boards (oversampling only, not interleaved)
                result_N = fir_cal.calibrate_from_data(captured_waveforms_N, sample_rate_hz)
                result_N1 = fir_cal.calibrate_from_data(captured_waveforms_N1, sample_rate_hz)

                if result_N['success'] and result_N1['success']:
                    # Store oversampling calibrations in state
                    self.state.fir_coefficients_oversample[0] = result_N['fir_coefficients']
                    self.state.fir_calibration_samplerate_oversample[0] = sample_rate_hz
                    self.state.fir_freq_response_oversample[0] = result_N['freq_response']

                    self.state.fir_coefficients_oversample[1] = result_N1['fir_coefficients']
                    self.state.fir_calibration_samplerate_oversample[1] = sample_rate_hz
                    self.state.fir_freq_response_oversample[1] = result_N1['freq_response']

                    # Show success message
                    message = (f"Oversampling FIR Calibration Complete!\n\n"
                             f"Board {board_N}: {result_N['message']}\n"
                             f"Board {board_N1}: {result_N1['message']}")
                    QMessageBox.information(self, "FIR Calibration Complete", message)

                    # Enable the apply checkbox if it's not already enabled
                    if not self.state.fir_correction_enabled:
                        self.ui.actionApply_FIR_corrections.setEnabled(True)  # Enable so it can be unchecked
                        self.ui.actionApply_FIR_corrections.setChecked(True)
                        self.state.fir_correction_enabled = True
                else:
                    error_msgs = []
                    if not result_N['success']:
                        error_msgs.append(f"Board {board_N}: {result_N['message']}")
                    if not result_N1['success']:
                        error_msgs.append(f"Board {board_N1}: {result_N1['message']}")
                    QMessageBox.critical(self, "FIR Calibration Failed", "\n".join(error_msgs))

            elif twochannel_mode:
                # Run two-channel calibration at halved sample rate (1.6 GHz)
                sample_rate_hz_twochannel = sample_rate_hz / 2  # 1.6 GHz
                result = fir_cal.calibrate_from_data(captured_waveforms_twochannel, sample_rate_hz_twochannel)

                if result['success']:
                    # Store two-channel calibration in state
                    self.state.fir_coefficients_twochannel = result['fir_coefficients']
                    self.state.fir_calibration_samplerate_twochannel = sample_rate_hz_twochannel
                    self.state.fir_freq_response_twochannel = result['freq_response']

                    # Show success message
                    message = (f"Two-Channel FIR Calibration Complete!\n\n"
                             f"Calibrated at {sample_rate_hz_twochannel/1e9:.2f} GHz per channel\n\n"
                             f"{result['message']}")
                    QMessageBox.information(self, "FIR Calibration Complete", message)

                    # Enable the apply checkbox if it's not already enabled
                    if not self.state.fir_correction_enabled:
                        self.ui.actionApply_FIR_corrections.setEnabled(True)  # Enable so it can be unchecked
                        self.ui.actionApply_FIR_corrections.setChecked(True)
                        self.state.fir_correction_enabled = True
                else:
                    QMessageBox.critical(self, "FIR Calibration Failed", result['message'])

            else:
                # Run normal calibration
                result = fir_cal.calibrate_from_data(captured_waveforms, sample_rate_hz)

                if result['success']:
                    # Store calibration in state
                    self.state.fir_coefficients = result['fir_coefficients']
                    self.state.fir_calibration_samplerate = sample_rate_hz
                    self.state.fir_freq_response = result['freq_response']

                    # Show success message
                    QMessageBox.information(self, "FIR Calibration Complete", result['message'])

                    # Enable the apply checkbox if it's not already enabled
                    if not self.state.fir_correction_enabled:
                        self.ui.actionApply_FIR_corrections.setEnabled(True)  # Enable so it can be unchecked
                        self.ui.actionApply_FIR_corrections.setChecked(True)
                        self.state.fir_correction_enabled = True
                else:
                    QMessageBox.critical(self, "FIR Calibration Failed", result['message'])

        except Exception as e:
            # Restore drawing and depth on error
            self.state.dodrawing = old_dodrawing
            if old_depth != calibration_depth:
                self.state.expect_samples = old_depth
                self.allocate_xy_data()
                self.controller.send_trigger_info_all()
                self.sync_depth_ui_from_state()
                print(f"FIR calibration error: Restored depth to {old_depth}")
            QMessageBox.critical(self, "FIR Calibration Error", f"Error during calibration: {str(e)}")

    def save_fir_filter(self):
        """Save FIR calibration to a separate file."""
        save_fir_filter(self, self.state)

    def load_fir_filter(self):
        """Load FIR calibration from a file."""
        load_fir_filter(self, self.state, self.ui)

    def update_plot_loop(self):
        """Main acquisition loop, with full status bar and FFT plot updates."""
        s = self.state
        if self.socket and self.socket.issending:
            time.sleep(0.001) # for sync with ngscopeclient thread
            return

        profile_event_loop = False
        if profile_event_loop:
            print("\nStarting profile for event")
            start_time = time.perf_counter()
        else: start_time = None

        raw_data_map, rx_len = self.update_plot_event()
        if not raw_data_map:
            s.isdrawing = False
            return

        if profile_event_loop:
            end_time1 = time.perf_counter()
            elapsed_time_seconds = end_time1 - start_time
            elapsed_time_microseconds = elapsed_time_seconds * 1_000_000
            print(f"Elapsed time for getting data: {elapsed_time_microseconds:.2f} microseconds")
        else: end_time1 = None

        s.nevents += 1
        s.lastsize = rx_len
        if s.nevents - s.oldnevents >= s.tinterval:
            now = time.time()
            elapsedtime = now - s.oldtime
            s.oldtime = now
            if elapsedtime > 0:
                s.lastrate = round(s.tinterval / elapsedtime, 2)
            s.oldnevents = s.nevents

        self.update_plot_process_event(raw_data_map)

        if profile_event_loop:
            end_time2 = time.perf_counter()
            elapsed_time_seconds = end_time2 - end_time1
            elapsed_time_microseconds = elapsed_time_seconds * 1_000_000
            print(f"Elapsed time for processing data: {elapsed_time_microseconds:.2f} microseconds")
        else: end_time2 = None

        # Use data for plot, FFT, math, etc.
        self.update_plot_data()

        if profile_event_loop:
            end_time3 = time.perf_counter()
            elapsed_time_seconds = end_time3 - end_time2
            elapsed_time_microseconds = elapsed_time_seconds * 1_000_000
            print(f"Elapsed time for updating plot data: {elapsed_time_microseconds:.2f} microseconds")

        now = time.time()
        dt = now - self.last_time + 1e-9
        self.last_time = now
        self.fps = 1.0 / dt if self.fps is None else self.fps * 0.9 + (1.0 / dt) * 0.1

        s.isdrawing = False # for sync with ngscopeclient thread

        # If 'getone' (Single) mode is active, call dostartstop() immediately
        # after successfully processing one event. This will pause the acquisition.
        if s.getone:
            # Update measurements for the newly acquired event before pausing
            self.measurements.update_measurements_display()
            self.dostartstop()

    def update_plot_event(self):
        s = self.state

        # If the flag is set, get and discard the next event to avoid glitches
        if s.skip_next_event:
            s.skip_next_event = False
            try:
                self.controller.get_event()  # Fetch and discard
            except ftd2xx.DeviceError:
                pass  # Ignore potential errors during this flush
            return None, 0
        s.isdrawing = True  # for sync with ngscopeclient thread
        try:
            raw_data_map, rx_len = self.controller.get_event()
            if not self.controller.got_exception:
                return raw_data_map, rx_len
            else:
                title = "Hardware Communication Exception"
                message = (f"Got an exception when fetching event data.\n\n"
                           "Please check the USB connection and restart the application.")
                self.handle_critical_error(title, message)
                # Stop this loop immediately since communication has failed.
                return None, 0
        except ftd2xx.DeviceError as e:
            # If a hardware communication error occurs, handle it gracefully.
            title = "Hardware Communication Error"
            message = (f"Lost communication with the device.\n\n"
                       f"Details: {e}\n\n"
                       "Please check the USB connection and restart the application.")
            self.handle_critical_error(title, message)
            # Stop this loop immediately since communication has failed.
            return None, 0

    def update_plot_process_event(self, raw_data_map):
        s = self.state

        # Creates the xydata, xydatainterleaved arrays or resizes if needed, filled next by the processor
        self.allocate_xy_data()

        for board_idx, raw_data in raw_data_map.items():
            expect_len = (self.state.expect_samples + self.state.expect_samples_extra) * 2 * 50
            if len(raw_data) < expect_len:
                print("Not enough data length in event, not processing.")
                return
            try:
                nbadA, nbadB, nbadC, nbadD, nbadS = self.processor.process_board_data(raw_data, board_idx, self.xydata)
            except RuntimeError as e:
                self.closeEvent(None)
                title = "Data Processing Failed"
                message = (f"Data processing failed for board {board_idx}: {e}\n\n"
                           "Please check the USB connection and restart the application.")
                QMessageBox.critical(self, title, message)
                sys.exit(-7)
            if s.plljustreset[board_idx] > -10:
                # If a reset is already in progress, continue it.
                self.controller.adjustclocks(board_idx, nbadA, nbadB, nbadC, nbadD, nbadS, self)
            elif s.pll_reset_grace_period > 0:
                # If in the grace period, ignore any bad clock signals.
                pass
            elif (nbadA + nbadB + nbadC + nbadD + nbadS) > 0:
                # If not in a reset and not in grace period, trigger a new reset on error.
                print(f"Bad clock/strobe detected on board {board_idx}. Triggering PLL reset.")
                self.controller.pllreset(board_idx)

        # Decrement the grace period counter once per event, outside the board loop
        if s.pll_reset_grace_period > 0:
            s.pll_reset_grace_period -= 1

        # Do mean rms calibration for oversampling boards if needed
        for board_idx in range(s.num_board):
            if s.dooversample[board_idx] and board_idx % 2 == 0:
                do_meanrms_calibration(self)

        # Check if autocalibration is collecting data
        if s.triggerautocalibration[s.activeboard]: autocalibration(self)
        if hasattr(self, 'autocalib_collector') and self.autocalib_collector is not None:
            if self.autocalib_collector.was_drawing is None:
                self.autocalib_collector.was_drawing = s.dodrawing  # remember if we were drawing before calibration
                s.dodrawing = False
                if s.extraphasefortad[s.activeboard + 1] and not s.triggerautocalibration[s.activeboard]:
                    print("Resetting PLL extra phase. Adjusting PLL a step back up on other board.")
                    self.controller.do_phase(s.activeboard + 1, plloutnum=0, updown=1, pllnum=0)
                    self.controller.do_phase(s.activeboard + 1, plloutnum=1, updown=1, pllnum=0)
                    self.controller.do_phase(s.activeboard + 1, plloutnum=2, updown=1, pllnum=0)
                    s.extraphasefortad[s.activeboard + 1] = 0
                s.triggerautocalibration[s.activeboard] = False
            done = self.autocalib_collector.collect_event_data()
            if done:
                # Done collecting, apply calibration
                self.autocalib_collector.apply_calibration()
                s.dodrawing = self.autocalib_collector.was_drawing
                self.autocalib_collector = None
                if self.ui.actionAuto_oversample_alignment.isChecked():
                    self.ui.interleavedCheck.setChecked(True)
            elif done is None:
                print("Autocalibration failed to find edges in the data.")
                s.dodrawing = self.autocalib_collector.was_drawing
                self.autocalib_collector = None

    def update_plot_data(self):
        s = self.state

        # --- Plotting Logic: Update normal time-domain plots ---
        self.plot_manager.update_plots(self.xydata, self.xydatainterleaved)

        # Calculate and display math channels if any are defined
        math_results = {}
        self.math_results_noresamp = {}  # Store as instance variable for reference taking
        if self.math_window and len(self.math_window.math_channels) > 0:
            # Calculate math channels using non-resampled data (correct for FFT and filters)
            self.math_results_noresamp = self.math_window.calculate_math_channels(self.plot_manager.stabilized_data_noresamp)

            # Resample math channel results for display based on source channel's doresamp
            from scipy.signal import resample
            math_results = {}
            for math_name, (x_data, y_data) in self.math_results_noresamp.items():
                # Find the math channel definition
                math_def = next((m for m in self.math_window.math_channels if m['name'] == math_name), None)
                if math_def:
                    ch1_idx = math_def['ch1']

                    # Determine doresamp factor based on source type
                    doresamp_factor = 1
                    if isinstance(ch1_idx, str):
                        # Source is a reference or another math channel
                        if ch1_idx.startswith("Ref"):
                            # Get doresamp from reference
                            ref_idx = int(ch1_idx[3:])
                            if ref_idx in self.reference_data:
                                doresamp_factor = self.reference_data[ref_idx].get('doresamp', 1)
                        else:
                            # Source is another math channel - get from its reference data
                            if ch1_idx in self.math_reference_data:
                                doresamp_factor = self.math_reference_data[ch1_idx].get('doresamp', 1)
                    else:
                        # Source is a regular channel
                        doresamp_factor = s.doresamp[ch1_idx]

                    # Apply resampling if needed
                    if doresamp_factor > 1:
                        y_resampled, x_resampled = resample(y_data, len(x_data) * doresamp_factor, t=x_data)
                        math_results[math_name] = (x_resampled, y_resampled)
                    else:
                        math_results[math_name] = (x_data, y_data)
                else:
                    math_results[math_name] = (x_data, y_data)

            self.plot_manager.update_math_channel_data(math_results)

        # --- Update XY window if visible (after math channels calculated) ---
        if s.xy_mode and self.xy_window is not None and self.xy_window.isVisible():
            self.xy_window.update_xy_plot(self.xydata, math_results)

        # --- Update Zoom window if visible ---
        if self.zoom_window is not None and self.zoom_window.isVisible():
            self.zoom_window.update_zoom_plot(self.plot_manager.stabilized_data, math_results)
            self.zoom_window.update_trigger_and_cursor_lines(self.plot_manager)
            self.zoom_window.update_peak_detect_lines(self.plot_manager)
            self.zoom_window.update_persist_lines(self.plot_manager)
            self.zoom_window.update_reference_waveforms(
                self.reference_data, self.reference_visible,
                self.math_reference_data, self.math_reference_visible
            )

        # Store event in history buffer (only if not displaying historical data)
        if not self.displaying_history:
            event_data = {
                'timestamp': datetime.now(),
                'xydata': self.xydata.copy(),
                'xydatainterleaved': self.xydatainterleaved.copy() if self.xydatainterleaved is not None else None
            }
            self.history_buffer.append(event_data)

        if self.recorder.is_recording:
            lines_vis = [line.isVisible() for line in self.plot_manager.lines]
            self.recorder.record_event(self.xydata, self.plot_manager.otherlines['vline'].value(), lines_vis)

        if self.fftui and self.fftui.isVisible():
            active_channel_name = f"CH{s.activexychannel + 1}"

            # Loop through all possible channels
            for ch_idx in range(s.num_board * s.num_chan_per_board):
                ch_name = f"CH{ch_idx + 1}"
                board_idx = ch_idx // s.num_chan_per_board

                # Update FFT if this channel is enabled
                if s.fft_enabled.get(ch_name, False):
                    is_active = (ch_name == active_channel_name)

                    # Use FIR-corrected data WITHOUT resampling (stabilized_data_noresamp)
                    # This has FIR corrections applied but avoids upsampled/resampled artifacts
                    if self.plot_manager.stabilized_data_noresamp[ch_idx] is not None:
                        x_data, y_data_for_analysis = self.plot_manager.stabilized_data_noresamp[ch_idx]
                    else:
                        # Channel data not available (e.g., secondary channel in interleaved mode)
                        continue

                    # Pass the correct board_idx to get the right sample rate
                    freq, mag = self.processor.calculate_fft(y_data_for_analysis, board_idx)

                    if freq is not None and len(freq) > 0:
                        max_freq_mhz = np.max(freq)
                        if max_freq_mhz < 0.001:
                            plot_x_data, xlabel = freq * 1e6, 'Frequency (Hz)'
                        elif max_freq_mhz < 1.0:
                            plot_x_data, xlabel = freq * 1e3, 'Frequency (kHz)'
                        else:
                            plot_x_data, xlabel = freq, 'Frequency (MHz)'

                        title = f'Haasoscope Pro FFT Plot'
                        pen = self.plot_manager.linepens[ch_idx]  # Get the correct pen
                        self.fftui.update_plot(ch_name, plot_x_data, mag, pen, title, xlabel, is_active)
                else:
                    self.fftui.clear_plot(ch_name)

            # Process math channels for FFT
            if self.math_window is not None:
                # Check if any regular channels have FFT enabled
                has_regular_channel_fft = any(
                    s.fft_enabled.get(f"CH{i + 1}", False)
                    for i in range(s.num_board * s.num_chan_per_board)
                )

                # Track if we've made a math channel active yet
                made_math_active = False

                for math_def in self.math_window.math_channels:
                    math_name = math_def['name']

                    # Update FFT if this math channel is enabled
                    if s.fft_enabled.get(math_name, False):
                        # Get math channel data from the plot manager
                        if math_name in self.plot_manager.math_channel_lines:
                            math_line = self.plot_manager.math_channel_lines[math_name]
                            x_data, y_data = math_line.getData()

                            if y_data is not None and len(y_data) > 0:
                                # For FFT, use the non-resampled math channel result (correct frequency range)
                                ch1_idx = math_def['ch1']
                                board_idx_for_fft = s.activeboard if isinstance(ch1_idx, str) else ch1_idx // s.num_chan_per_board

                                # Use non-resampled result for FFT
                                if hasattr(self, 'math_results_noresamp') and math_name in self.math_results_noresamp:
                                    _, y_data_for_fft = self.math_results_noresamp[math_name]
                                else:
                                    y_data_for_fft = y_data  # Fallback to displayed data

                                # Calculate FFT using original sample rate
                                freq, mag = self.processor.calculate_fft(y_data_for_fft, board_idx_for_fft)

                                if freq is not None and len(freq) > 0:
                                    max_freq_mhz = np.max(freq)
                                    if max_freq_mhz < 0.001:
                                        plot_x_data, xlabel = freq * 1e6, 'Frequency (Hz)'
                                    elif max_freq_mhz < 1.0:
                                        plot_x_data, xlabel = freq * 1e3, 'Frequency (kHz)'
                                    else:
                                        plot_x_data, xlabel = freq, 'Frequency (MHz)'

                                    title = f'Haasoscope Pro FFT Plot'
                                    # Create a pen with the math channel's color
                                    color = QColor(math_def['color'])
                                    pen = pg.mkPen(color=color, width=math_def.get('width', 1))

                                    # Make this math channel active if no regular channels have FFT enabled
                                    # and this is the first math channel we're processing
                                    is_active = False
                                    if not has_regular_channel_fft and not made_math_active:
                                        is_active = True
                                        made_math_active = True

                                    self.fftui.update_plot(math_name, plot_x_data, mag, pen, title, xlabel, is_active)
                    else:
                        self.fftui.clear_plot(math_name)

    def update_status_bar(self):
        """Updates the status bar text at a fixed rate (5 Hz)."""
        s = self.state
        if s.num_board < 1 or self.fps is None: return
        sradjust = 1e9
        if s.dointerleaved[s.activeboard]: sradjust = 2e9
        elif s.dotwochannel[s.activeboard]: sradjust = 0.5e9
        highres = self.ui.actionHigh_resolution.isChecked()
        effective_sr = s.samplerate * sradjust / (s.downsamplefactor if not highres else 1)

        # In testing mode, show only sample rate (skip dynamic fps, events, Hz, MB/s)
        if self.testing_mode:
            status_text = f"{format_freq(effective_sr, 'S/s')}"
        else:
            status_text = (f"{format_freq(effective_sr, 'S/s')}, {self.fps:.2f} fps, "
                           f"{s.nevents} events, {s.lastrate:.2f} Hz, "
                           f"{(s.lastrate * s.lastsize / 1e6):.2f} MB/s")

        if self.dummy_scope is not None: status_text += ", connected to a dummy scope at " + str(self.dummy_scope)
        if self.recorder.is_recording: status_text += ", Recording to "+str(self.recorder.file_handle.name)
        self.ui.statusBar.showMessage(status_text)

        # Update channel name legend while we're at it
        self.plot_manager.update_legend()

    def resizeEvent(self, event):
        """Handles window resize events to adjust the table view."""
        super().resizeEvent(event)  # Call the parent's resize event

        # Close histogram window when main window resizes
        if self.histogram_window.isVisible():
            self.measurements.hide_histogram()

        # Use a single shot timer to ensure the layout has settled before adjusting
        QtCore.QTimer.singleShot(1, self.measurements.adjust_table_view_geometry)

    def moveEvent(self, event):
        """Handles window move events."""
        super().moveEvent(event)

        # Close histogram window when main window moves
        if self.histogram_window.isVisible():
            self.measurements.hide_histogram()

    def allocate_xy_data(self):
        """Creates or re-sizes the numpy arrays for storing waveform data."""
        s = self.state
        num_ch = s.num_chan_per_board * s.num_board

        # ALWAYS allocate for the maximum number of samples (single-channel mode).
        # The DataProcessor will handle filling it correctly for each board's mode.
        num_samples = 4 * 10 * s.expect_samples
        shape = (num_ch, 2, num_samples)

        # Avoid re-allocating if the shape hasn't changed
        if not hasattr(self, 'xydata') or self.xydata.shape != shape:
            self.xydata = np.zeros(shape, dtype=float)
            ishape = (num_ch, 2, 2 * num_samples)  # For interleaved data
            self.xydatainterleaved = np.zeros(ishape, dtype=float)
            self.time_changed()  # Initialize x-axis values

    def time_changed(self):
        """Updates plot manager and recalculates x-axis arrays on timebase change."""
        self.plot_manager.time_changed()
        s = self.state

        # --- Calculate and display the time per division ---
        # Get the total time span shown on the screen
        time_span = s.max_x - s.min_x
        # Divide by 10 (for the 10 horizontal divisions on the grid)
        time_per_div = time_span / 10.0
        # Format the string with appropriate precision and the current units

        # Convert to nanoseconds first
        time_per_div_ns = time_per_div * s.nsunits

        # Choose units so the displayed value is >= 1, format to 5 total digits
        if time_per_div_ns >= 1e9:
            # Seconds
            value = time_per_div_ns / 1e9
            if value >= 100:
                display_text = f"{value:.1f} s"
            elif value >= 10:
                display_text = f"{value:.2f} s"
            else:
                display_text = f"{value:.3f} s"
        elif time_per_div_ns >= 1e6:
            # Milliseconds
            value = time_per_div_ns / 1e6
            if value >= 100:
                display_text = f"{value:.1f} ms"
            elif value >= 10:
                display_text = f"{value:.2f} ms"
            else:
                display_text = f"{value:.3f} ms"
        elif time_per_div_ns >= 1e3:
            # Microseconds
            value = time_per_div_ns / 1e3
            if value >= 100:
                display_text = f"{value:.1f} us"
            elif value >= 10:
                display_text = f"{value:.2f} us"
            else:
                display_text = f"{value:.3f} us"
        elif time_per_div_ns >= 1:
            # Nanoseconds
            value = time_per_div_ns
            if value >= 100:
                display_text = f"{value:.1f} ns"
            elif value >= 10:
                display_text = f"{value:.2f} ns"
            else:
                display_text = f"{value:.3f} ns"
        else:
            # Picoseconds
            value = time_per_div_ns * 1000
            if value >= 100:
                display_text = f"{value:.1f} ps"
            elif value >= 10:
                display_text = f"{value:.2f} ps"
            else:
                display_text = f"{value:.3f} ps"

        self.ui.timebaseBox.setText(display_text)
        # self.ui.timebaseBox.setText(f"2^{self.state.downsample}")

        # The time step per sample in the xydata array is now CONSTANT,
        # corresponding to the highest density mode (single-channel).
        x_step1 = 1 * s.downsamplefactor / s.nsunits / s.samplerate
        x_step2 = 0.5 * s.downsamplefactor / s.nsunits / s.samplerate

        # This logic populates the x-axis (time) for each channel's data array
        if hasattr(self, 'xydata'):
            time_axis = np.arange(self.xydata.shape[2]) * x_step1
            for c in range(s.num_chan_per_board * s.num_board):
                self.xydata[c][0] = time_axis

        if hasattr(self, 'xydatainterleaved'):
            interleaved_time_axis = np.arange(self.xydatainterleaved.shape[2]) * x_step2
            for c in range(s.num_chan_per_board * s.num_board):
                self.xydatainterleaved[c][0] = interleaved_time_axis

        # Reset accumulated trigger corrections since we've generated fresh time axes
        for board_idx in range(s.num_board):
            s.totdistcorr[board_idx] = 0

        # --- Update reference waveforms with new scaling and per-channel visibility ---
        for i in range(self.plot_manager.nlines):
            # Check if this specific channel has a reference and it's set to visible
            has_reference = i in self.reference_data
            is_visible = self.reference_visible.get(i, False)

            if has_reference and is_visible:
                # This channel has a reference and it should be visible
                data = self.reference_data[i]
                x_data = data['x_ns'] / s.nsunits
                y_data = data['y']

                # Get stored width (for backward compatibility, default to current if not stored)
                stored_width = data.get('width', None)

                # Resample reference to match the stored doresamp setting for display
                # Use stored doresamp if available (for backward compatibility)
                doresamp_to_use = data.get('doresamp', s.doresamp[i])
                if doresamp_to_use > 1:
                    from scipy.signal import resample
                    y_resampled, x_resampled = resample(y_data, len(x_data) * doresamp_to_use, t=x_data)
                    self.plot_manager.update_reference_plot(i, x_resampled, y_resampled, width=stored_width)
                else:
                    self.plot_manager.update_reference_plot(i, x_data, y_data, width=stored_width)
            else:
                # This channel either has no reference or its reference is hidden
                self.plot_manager.hide_reference_plot(i)

        # --- Update math reference waveforms ---
        if self.math_window is not None:
            self.plot_manager.update_math_reference_lines(self.math_window, self)

        # Update trigger spinbox tooltips with new timing
        self.update_trigger_spinbox_tooltip(self.ui.totBox, "Time over threshold required to trigger")
        self.update_trigger_spinbox_tooltip(self.ui.trigger_delay_box, "Time to wait before actually firing trigger")
        self.update_trigger_spinbox_tooltip(self.ui.trigger_holdoff_box, "Time needed failing threshold before passing threshold")

    def _show_update_notification(self, current, latest, release_url):
        """
        Show a notification dialog when a new software version is available.
        Called by the update_checker when it detects a newer release.
        """
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Update Available")
        msg.setText(f"A new version is available: v{latest}\n(You have v{current})")
        msg.setInformativeText("Would you like to download the new version?")

        # Create custom buttons
        yes_button = msg.addButton("Yes", QMessageBox.YesRole)
        ignore_button = msg.addButton(" Ignore this release ", QMessageBox.NoRole)
        remind_button = msg.addButton(" Remind me next time ", QMessageBox.RejectRole)
        msg.exec_()

        # Handle button clicks
        clicked_button = msg.clickedButton()
        if clicked_button == yes_button:
            import webbrowser
            webbrowser.open(release_url)
        elif clicked_button == ignore_button:
            self.update_checker.ignore_version(latest)
            print(f"Version {latest} will be ignored in future update checks")

    def handle_critical_error(self, title, message):
        """
        This slot is called when the hardware controller signals an unrecoverable error.
        It stops the acquisition and displays an error message to the user.
        """
        # 1. Stop the acquisition timer if it's running
        if not self.state.paused: self.dostartstop()

        # 2. Disable the run button to prevent the user from restarting
        self.ui.runButton.setEnabled(False)

        # 3. Prevent firmware methods
        self.ui.actionUpdate_firmware.setEnabled(False)
        self.ui.actionVerify_firmware.setEnabled(False)

        # 4. Cleanup as much as possible
        self.closeEvent(None)

        # 5. Show the critical error message box
        QMessageBox.critical(self, title, message)

        # 6. Exit
        sys.exit(-1)

    def closeEvent(self, event):
        if event is None: print("Stopping application...")
        self.update_timer.stop()
        self.measurement_timer.stop()
        self.fan_timer.stop()
        self.recorder.stop()
        self.close_socket()
        self.histogram_window.close()
        # Block signals to prevent history window from trying to resume acquisition
        self.history_window.blockSignals(True)
        self.history_window.close()
        if self.math_window: self.math_window.close()
        if self.fftui: self.fftui.close()
        if event is not None:
            if not self.controller.got_exception: self.controller.cleanup()
            event.accept()
            print("Cleanup complete. Exiting.")

    def keyPressEvent(self, event):
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        if event.key() == QtCore.Qt.Key_Up:
            if modifiers & QtCore.Qt.ShiftModifier:
                self.ui.gainBox.setValue(self.ui.gainBox.value() + 1)
            elif modifiers & QtCore.Qt.ControlModifier:
                # Ctrl+Up: Increase trigger threshold
                self.ui.threshold.setValue(self.ui.threshold.value() + 5)
            elif modifiers & QtCore.Qt.AltModifier:
                # Alt+Up: Increase trigger delta
                self.ui.thresholdDelta.setValue(self.ui.thresholdDelta.value() + 1)
            else:
                self.ui.offsetBox.stepUp()
        if event.key() == QtCore.Qt.Key_Down:
            if modifiers & QtCore.Qt.ShiftModifier:
                self.ui.gainBox.setValue(self.ui.gainBox.value() - 1)
            elif modifiers & QtCore.Qt.ControlModifier:
                # Ctrl+Down: Decrease trigger threshold
                self.ui.threshold.setValue(self.ui.threshold.value() - 5)
            elif modifiers & QtCore.Qt.AltModifier:
                # Alt+Down: Decrease trigger delta
                self.ui.thresholdDelta.setValue(self.ui.thresholdDelta.value() - 1)
            else:
                self.ui.offsetBox.stepDown()
        if event.key() == QtCore.Qt.Key_Left:
            if modifiers & QtCore.Qt.ControlModifier:
                # Ctrl+Left: Decrease trigger position
                self.ui.thresholdPos.setValue(self.ui.thresholdPos.value() - 100)
            else:
                self.time_slow()
        if event.key() == QtCore.Qt.Key_Right:
            if modifiers & QtCore.Qt.ControlModifier:
                # Ctrl+Right: Increase trigger position
                self.ui.thresholdPos.setValue(self.ui.thresholdPos.value() + 100)
            else:
                self.time_fast()
        if event.key() == QtCore.Qt.Key_R: self.dostartstop()

    def eventFilter(self, obj, event):
        """Event filter to make chanColor clickable."""
        if (obj == self.ui.chanColor or obj == self.ui.chanColor.viewport()) and \
           event.type() == QtCore.QEvent.MouseButtonPress:
            # Only handle left button clicks
            if hasattr(event, 'button') and event.button() == QtCore.Qt.LeftButton:
                # Trigger the change channel color dialog
                self.change_channel_color()
                return True
        return super().eventFilter(obj, event)

    def on_curve_clicked(self, channel_index):
        """Slot for when a waveform on the plot is clicked."""
        board = channel_index // self.state.num_chan_per_board
        channel = channel_index % self.state.num_chan_per_board
        self.ui.boardBox.setCurrentIndex(board)
        self.ui.chanBox.setCurrentIndex(channel)
        # select_channel is called automatically by the currentIndexChanged signal

    def on_math_curve_clicked(self, math_channel_name):
        """Slot for when a math channel waveform on the plot is clicked."""
        # Open the math channels window if not already open
        if self.math_window is None:
            self.math_window = MathChannelsWindow(self)
            self.math_window.math_channels_changed.connect(lambda: self.update_math_channels())
        self.math_window.show()
        self.math_window.raise_()
        self.math_window.activateWindow()

        # Select this math channel in the list
        self.math_window.select_math_channel_in_list(math_channel_name)

        # Select this math channel for measurements
        self.measurements.select_math_channel_for_measurement(math_channel_name)

    def toggle_pll_controls(self):
        """Shows or hides the manual PLL adjustment buttons."""
        is_enabled = self.ui.pllBox.isEnabled()
        self.ui.pllBox.setEnabled(not is_enabled)
        for i in range(5):
            getattr(self.ui, f"upposButton{i}").setEnabled(not is_enabled)
            getattr(self.ui, f"downposButton{i}").setEnabled(not is_enabled)

    def update_autocalibration_enabled(self):
        """Update the enabled state of the Do Autocalibration action.

        Should be enabled only when the active board is an even-numbered board
        in an oversampling pair.
        """
        s = self.state
        # Check if we have at least 2 boards
        if s.num_board < 2:
            self.ui.actionDo_autocalibration.setEnabled(False)
            return

        # Check if active board is even and in oversampling mode
        is_even_board = s.activeboard % 2 == 0
        is_oversampling = s.dooversample[s.activeboard]

        should_enable = is_even_board and is_oversampling
        self.ui.actionDo_autocalibration.setEnabled(should_enable)

    def toggle_oversampling_controls(self):
        """Shows or hides the oversampling delay and fine delay adjustment buttons."""
        is_enabled = self.ui.actionOversampling_controls.isChecked()
        self.ui.ToffBox.setEnabled(is_enabled)
        self.ui.tadBox.setEnabled(is_enabled)

    def force_split_toggled(self, checked):
        self.controller.force_split(self.state.activeboard, checked)

    def force_switch_clocks_triggered(self):
        self.controller.force_switch_clocks(self.state.activeboard)

    # Slots for all the PLL phase buttons
    def uppos(self):
        self.controller.do_phase(self.state.activeboard, 0, 1, self.ui.pllBox.value())

    def uppos1(self):
        self.controller.do_phase(self.state.activeboard, 1, 1, self.ui.pllBox.value())

    def uppos2(self):
        self.controller.do_phase(self.state.activeboard, 2, 1, self.ui.pllBox.value())

    def uppos3(self):
        self.controller.do_phase(self.state.activeboard, 3, 1, self.ui.pllBox.value())

    def uppos4(self):
        self.controller.do_phase(self.state.activeboard, 4, 1, self.ui.pllBox.value())

    def downpos(self):
        self.controller.do_phase(self.state.activeboard, 0, 0, self.ui.pllBox.value())

    def downpos1(self):
        self.controller.do_phase(self.state.activeboard, 1, 0, self.ui.pllBox.value())

    def downpos2(self):
        self.controller.do_phase(self.state.activeboard, 2, 0, self.ui.pllBox.value())

    def downpos3(self):
        self.controller.do_phase(self.state.activeboard, 3, 0, self.ui.pllBox.value())

    def downpos4(self):
        self.controller.do_phase(self.state.activeboard, 4, 0, self.ui.pllBox.value())

    # #########################################################################
    # ## Slot Implementations (Callbacks for UI events)
    # #########################################################################

    def dostartstop(self):
        if self.state.paused:
            self.update_timer.start(0)  # 0ms interval for fastest refresh
            self.measurement_timer.start(20)  # 20ms interval = 50 Hz for measurements
            self.status_timer.start(200)  # Start status timer at 5 Hz
            self.state.paused = False
            self.ui.runButton.setChecked(True)
            # If resuming from history display, clear the flag
            if self.displaying_history:
                self.displaying_history = False
                self.current_history_index = None
        else:
            self.update_timer.stop()
            self.measurement_timer.stop()
            #self.status_timer.stop() # Stop status timer
            self.state.paused = True
            self.ui.runButton.setChecked(False)

    def high_resolution_toggled(self, checked):
        """Toggles the hardware's high-resolution averaging mode."""
        # The downsample command also sends the high-resolution setting,
        # so we just need to re-send it to the hardware for all boards.
        highres = 1 if checked else 0
        self.controller.tell_downsample_all(self.state.downsample, highres)

    def select_channel(self):
        """Called when board or channel selector is changed."""
        s = self.state
        if s.num_board<1: return
        s.activeboard = self.ui.boardBox.currentIndex()
        s.selectedchannel = self.ui.chanBox.currentIndex()

        # This now correctly calls the method to update the checkbox
        self.update_fft_checkbox_state()
        self.update_fir_checkbox_state()

        # Update the "Two Channel" checkbox to reflect the state of the newly selected board
        # Block signals to prevent triggering twochan_changed when switching boards
        self.ui.twochanCheck.blockSignals(True)
        self.ui.twochanCheck.setChecked(self.state.dotwochannel[self.state.activeboard])
        self.ui.twochanCheck.blockSignals(False)

        # This handles channel selector limits and other mode-dependent UI
        self._update_channel_mode_ui()

        # Read the trigger state for the newly selected board
        is_ext = bool(s.doexttrig[s.activeboard])
        is_sma = bool(s.doextsmatrig[s.activeboard])

        # Update UI widgets to reflect the state of the newly selected channel
        self.ui.gainBox.setValue(s.gain[s.activexychannel])
        self.ui.offsetBox.setValue(s.offset[s.activexychannel])
        self.ui.skewBox.setValue(s.time_skew[s.activexychannel])

        # Update channel name
        self.ui.channameEdit.setPlaceholderText("Channel name")
        self.ui.channameEdit.setText(s.channel_names[s.activexychannel])

        self.ui.acdcCheck.setChecked(s.acdc[s.activexychannel])
        self.ui.ohmCheck.setChecked(s.mohm[s.activexychannel])
        self.ui.attCheck.setChecked(s.att[s.activexychannel])
        self.ui.tenxCheck.setChecked(s.tenx[s.activexychannel] == 10)
        self.ui.chanonCheck.setChecked(s.channel_enabled[s.activexychannel])
        self.ui.tadBox.setValue(s.tad[s.activeboard])

        # Update persistence UI controls to reflect active channel's settings
        self.sync_persistence_ui()

        # Update per-board trigger settings
        self.ui.trigger_delay_box.setValue(s.trigger_delay[s.activeboard])
        self.ui.trigger_holdoff_box.setValue(s.trigger_holdoff[s.activeboard])
        self.ui.thresholdDelta.setValue(s.triggerdelta[s.activeboard])
        self.ui.totBox.setValue(s.triggertimethresh[s.activeboard])

        # Update the consolidated trigger combo box
        # Index mapping: 0=Rising Ch0, 1=Falling Ch0, 2=Rising Ch1, 3=Falling Ch1, 4=Other boards, 5=External SMA
        if is_sma:
            trigger_index = 5
        elif is_ext:
            trigger_index = 4
        else:
            trigger_channel = s.triggerchan[s.activeboard]
            is_falling = s.fallingedge[s.activeboard]
            trigger_index = trigger_channel * 2 + int(is_falling)

        self.ui.risingfalling_comboBox.setCurrentIndex(trigger_index)

        # Update channel color preview box in the UI
        p = self.ui.chanColor.palette()
        p.setColor(QPalette.Base, self.plot_manager.linepens[s.activexychannel].color())
        self.ui.chanColor.setPalette(p)
        self.set_channel_frame()

        # Update the secondary Y-axis
        self.gain_changed()  # Recalculate V/div
        self.plot_manager.update_right_axis()

        # Update cursor display to reflect new active channel
        self.plot_manager.update_cursor_display()

        # Update peak detect for new active channel
        self.plot_manager.update_peak_channel()

        # Update hardware LEDs
        all_colors = [pen.color() for pen in self.plot_manager.linepens]
        self.controller.do_leds(all_colors)

        # Update XY menu item based on whether there are at least 2 channels total
        total_channels = self.state.num_board * self.state.num_chan_per_board
        self.ui.actionXY_Plot.setEnabled(total_channels >= 2)

        # Update Aux Out box to show the value for the currently selected board
        self.ui.Auxout_comboBox.blockSignals(True)
        self.ui.Auxout_comboBox.setCurrentIndex(self.state.auxoutval[self.state.activeboard])
        self.ui.Auxout_comboBox.blockSignals(False)

        # Update LPF box to show the value for the currently selected channel
        current_lpf_val = self.state.lpf[self.state.activexychannel]
        lpf_text = "Off" if current_lpf_val == 0 else str(current_lpf_val)+" MHz"
        lpf_index = self.ui.lpfBox.findText(lpf_text)
        self.ui.lpfBox.blockSignals(True)
        if lpf_index != -1: self.ui.lpfBox.setCurrentIndex(lpf_index)
        self.ui.lpfBox.blockSignals(False)

        # Update resamp box to show the value for the currently selected channel
        self.ui.resampBox.blockSignals(True)
        if self.state.downsample >= 0:
            # Not zoomed: ensure non-overridden channels are at default of 0
            if not self.state.resamp_overridden[self.state.activexychannel] and self.state.doresamp[self.state.activexychannel] != 0:
                self.state.doresamp[self.state.activexychannel] = 0
            self.ui.resampBox.setValue(self.state.doresamp[self.state.activexychannel])
        else:
            # Zoomed: ensure non-overridden channels are at default of 4
            if not self.state.resamp_overridden[self.state.activexychannel] and self.state.doresamp[self.state.activexychannel] != 4:
                self.state.doresamp[self.state.activexychannel] = 4
            self.ui.resampBox.setValue(self.state.doresamp[self.state.activexychannel])
        self.ui.resampBox.blockSignals(False)

        # Reset FFT analysis when channel changes
        if self.fftui:
            self.fftui.reset_analysis_state()

        # Update Show Reference menu checkbox to reflect active channel's reference visibility
        self.update_reference_checkbox_state()

        # Update Peak Detect menu checkbox to reflect active channel's peak detect state
        self.update_peak_detect_checkbox_state()

        # Update Pulse Stabilizer menu checkbox to reflect active board's state
        self.update_pulse_stabilizer_checkbox_state()

        # Update measurement table header to reflect new active channel (if not measuring a math channel)
        if self.measurements.selected_math_channel is None:
            self.measurements.update_measurement_header()

        # Update trigger spinbox tooltips
        self.update_trigger_spinbox_tooltip(self.ui.totBox, "Time over threshold required to trigger")
        self.update_trigger_spinbox_tooltip(self.ui.trigger_delay_box, "Time to wait before actually firing trigger")
        self.update_trigger_spinbox_tooltip(self.ui.trigger_holdoff_box, "Time needed failing threshold before passing threshold")

        # Update autocalibration enabled state based on new board selection
        self.update_autocalibration_enabled()

    def trigger_pos_changed(self, value):
        """
        Handles the trigger position slider.
        If zoomed in, slider position maps to full data range (0 to 10000 = left to right edge).
        Otherwise, it adjusts the absolute trigger position.
        """
        s = self.state

        if s.downsamplezoom > 1:  # Panning mode when zoomed in
            # Calculate the full data width and the current view width
            full_width = 4 * 10 * s.expect_samples * (s.downsamplefactor / s.nsunits / s.samplerate)
            view_width = 0.95 * full_width / s.downsamplezoom # allow us to see a little beyond

            # Map slider position (0 to 9900) to the full data range
            # Slider controls the LEFT edge of the zoomed window
            # Invert so moving right shifts view right
            slider_fraction = 1.0 - (value / 9900.0)  # Inverted: 1.0 to 0.0
            max_pan_distance = full_width - view_width  # Maximum left edge position

            # Calculate new min_x and max_x based on slider position
            s.min_x = slider_fraction * max_pan_distance
            s.max_x = s.min_x + view_width

            # Apply the new panned range to the plot
            self.plot_manager.plot.setRange(xRange=(s.min_x, s.max_x), padding=0.01)

            # Reset cursor positions if they are outside the visible range
            if self.plot_manager.cursor_manager:
                self.plot_manager.cursor_manager.adjust_cursor_positions()
                # Update trigger info display since view center has changed
                self.plot_manager.cursor_manager.update_trigger_threshold_text()

        else:  # Normal trigger adjust mode
            s.triggerpos = int(s.expect_samples * value / 10000.)
            self.controller.send_trigger_info_all()
            self.plot_manager.draw_trigger_lines()
            # Update trigger info display after trigger position changes
            if self.plot_manager.cursor_manager:
                self.plot_manager.cursor_manager.update_trigger_threshold_text()

    def on_vline_dragged(self, value):
        """
        Handles dragging the vertical trigger line.
        If zoomed in, it pans the view and updates the slider to reflect position in full range.
        """
        s = self.state

        if s.downsamplezoom > 1:  # Panning mode when zoomed in
            # Manually clamp the line's proposed position to the visible x-axis range
            value = max(s.min_x, min(value, s.max_x))

            # Calculate how far the line was dragged
            drag_delta = value - self.plot_manager.current_vline_pos

            # Shift the view range by that amount
            s.min_x -= drag_delta
            s.max_x -= drag_delta
            self.plot_manager.plot.setRange(xRange=(s.min_x, s.max_x), padding=0.01)

            # Snap the trigger line back to its original (central) position
            self.plot_manager.draw_trigger_lines()

            # Update the slider to reflect the new pan position in the full data range
            full_width = 4 * 10 * s.expect_samples * (s.downsamplefactor / s.nsunits / s.samplerate)
            view_width = s.max_x - s.min_x
            max_pan_distance = full_width - view_width

            if max_pan_distance > 0:
                # Calculate slider position based on left edge position
                slider_fraction = s.min_x / max_pan_distance
                # Invert to match the inverted logic in trigger_pos_changed
                slider_value = (1.0 - slider_fraction) * 9900.0

                # Update the slider without triggering its own signal
                self.ui.thresholdPos.blockSignals(True)
                self.ui.thresholdPos.setValue(int(slider_value))
                self.ui.thresholdPos.blockSignals(False)

            # Update trigger info display since view has panned
            if self.plot_manager.cursor_manager:
                self.plot_manager.cursor_manager.update_trigger_threshold_text()

        else:  # Normal trigger adjust mode
            t = (value / (4 * 10 * (s.downsamplefactor / s.nsunits / s.samplerate)) - 1.0) * 10000. / s.expect_samples
            self.ui.thresholdPos.blockSignals(True)
            self.ui.thresholdPos.setValue(math.ceil(t))
            self.ui.thresholdPos.blockSignals(False)
            self.trigger_pos_changed(self.ui.thresholdPos.value())

    def trigger_pos_reset(self):
        s = self.state

        # Reset trigger position to the middle of the data range
        s.triggerpos = int(s.expect_samples / 2)
        self.plot_manager.draw_trigger_lines()

        if s.downsamplezoom > 1:  # Zoomed mode - center view on trigger position
            # Use the same approach as time_fast/time_slow:
            # Call time_changed() to recalculate view, then sync slider
            self.time_changed()
            self.ui.thresholdPos.blockSignals(True)
            self.on_vline_dragged(self.plot_manager.otherlines['vline'].value())
            self.ui.thresholdPos.blockSignals(False)
        else:
            # Normal mode - just update the slider
            self.ui.thresholdPos.setValue(5000)

    def on_hline_dragged(self, value):
        t = value / (self.state.yscale * 256) + 127
        self.ui.threshold.setValue(int(t))

    def resamp_changed(self, value):
        """Handle resamp value changes from the UI."""
        s = self.state
        s.doresamp[s.activexychannel] = value
        # Mark that this channel's resamp has been manually overridden
        s.resamp_overridden[s.activexychannel] = True
        if self.state.downsample < 0:
            s.saved_doresamp[s.activexychannel] = value

    def line_width_changed(self, value):
        """Handle line width changes from the UI."""
        self.state.line_width = value
        self.plot_manager.set_line_width(value)

        # Update math channel widths to follow source channel widths
        if self.math_window is not None:
            self.plot_manager.update_math_channel_lines(self.math_window, self.reference_data)

    def trigger_level_changed(self, value):
        self.state.triggerlevel = value
        self.controller.send_trigger_info_all()
        self.plot_manager.draw_trigger_lines()

    def time_fast(self):
        if self.state.downsample < -10:
            #print("Maximum zoom level reached.")
            self.ui.timefastButton.setEnabled(False)

        old_downsample = self.state.downsample
        old_downsamplezoom = self.state.downsamplezoom
        self.state.downsample -= 1
        new_downsample = self.state.downsample
        highres = 1 if self.ui.actionHigh_resolution.isChecked() else 0
        self.controller.tell_downsample_all(self.state.downsample, highres)

        # When transitioning from downsample=0 to downsample=-1, set resamp intelligently
        if old_downsample == 0 and self.state.downsample == -1:
            s = self.state
            # If resamp has been manually overridden, keep the current value
            # Otherwise, use default of 4 for zoomed mode
            if not s.resamp_overridden[s.activexychannel]:
                s.doresamp[s.activexychannel] = 4

            # If in two-channel mode, also set doresamp for channel 1 of the active board
            if s.dotwochannel[s.activeboard]:
                ch1_index = s.activeboard * s.num_chan_per_board + 1
                if not s.resamp_overridden[ch1_index]:
                    s.doresamp[ch1_index] = 4

            # If overridden, keep current value (no change needed)

            self.ui.resampBox.blockSignals(True)
            self.ui.resampBox.setValue(s.doresamp[s.activexychannel])
            self.ui.resampBox.blockSignals(False)

        is_zoomed = self.state.downsample < 0
        if is_zoomed:
            self.state.downsamplezoom = pow(2, -self.state.downsample)
        else:
            self.state.downsamplezoom = 1
        new_downsamplezoom = self.state.downsamplezoom

        # Update the plot range and text box
        self.time_changed()

        # Adjust zoom ROI width based on downsample change type
        if self.zoom_window and self.zoom_window.isVisible():
            if old_downsample >= 0 and new_downsample >= 0:
                # Both in normal acquisition modes - use standard adjustment
                self.plot_manager.adjust_zoom_roi_for_downsample()
            elif old_downsamplezoom != new_downsamplezoom:
                # Zoom factor changed - scale ROI width by the zoom ratio
                zoom_ratio = new_downsamplezoom / old_downsamplezoom
                self.plot_manager.scale_zoom_roi_width(1.0 / zoom_ratio)

        # Clear peak detect data when timebase changes (for active channel)
        active_channel = self.state.activexychannel
        if active_channel in self.plot_manager.peak_detect_enabled and self.plot_manager.peak_detect_enabled[active_channel]:
            self.plot_manager.clear_peak_data()

        # If we are zoomed in, reset the pan slider to its center position.
        if is_zoomed:
            # Block signals to prevent this from triggering a pan action
            self.ui.thresholdPos.blockSignals(True)
            #self.ui.thresholdPos.setValue(5000)
            self.on_vline_dragged(self.plot_manager.otherlines['vline'].value())
            self.ui.thresholdPos.blockSignals(False)

        if self.fftui and not is_zoomed:
            self.fftui.reset_for_timescale_change()
            self.fftui.reset_analysis_state()

    def time_slow(self):
        self.ui.timefastButton.setEnabled(True)
        old_downsample = self.state.downsample
        old_downsamplezoom = self.state.downsamplezoom
        self.state.downsample += 1
        new_downsample = self.state.downsample
        highres = 1 if self.ui.actionHigh_resolution.isChecked() else 0
        self.controller.tell_downsample_all(self.state.downsample, highres)

        # When transitioning from downsample=-1 to downsample=0, set resamp intelligently for ALL channels
        if old_downsample == -1 and self.state.downsample == 0:
            s = self.state
            # For channels not manually overridden, set to default of 0 for non-zoomed mode
            # For overridden channels, keep their current value
            for ch in range(len(s.doresamp)):
                if not s.resamp_overridden[ch]:
                    s.doresamp[ch] = 0
                # If overridden, keep current value (no change)

            self.ui.resampBox.blockSignals(True)
            self.ui.resampBox.setValue(s.doresamp[s.activexychannel])
            self.ui.resampBox.blockSignals(False)

        is_zoomed = self.state.downsample < 0

        if is_zoomed:
            self.state.downsamplezoom = pow(2, -self.state.downsample)
        else:
            self.state.downsamplezoom = 1
        new_downsamplezoom = self.state.downsamplezoom

        # Update the plot range and text box
        self.time_changed()

        # Adjust zoom ROI width based on downsample change type
        if self.zoom_window and self.zoom_window.isVisible():
            if old_downsample >= 0 and new_downsample >= 0:
                # Both in normal acquisition modes - use standard adjustment
                self.plot_manager.adjust_zoom_roi_for_downsample()
            elif old_downsamplezoom != new_downsamplezoom:
                # Zoom factor changed - scale ROI width by the zoom ratio
                zoom_ratio = new_downsamplezoom / old_downsamplezoom
                self.plot_manager.scale_zoom_roi_width(1.0 / zoom_ratio)

        # Clear peak detect data when timebase changes (for active channel)
        active_channel = self.state.activexychannel
        if active_channel in self.plot_manager.peak_detect_enabled and self.plot_manager.peak_detect_enabled[active_channel]:
            self.plot_manager.clear_peak_data()

        # If we are zoomed in, reset the pan slider to its center position.
        if is_zoomed:
            # Block signals to prevent this from triggering a pan action
            self.ui.thresholdPos.blockSignals(True)
            #self.ui.thresholdPos.setValue(5000)
            self.on_vline_dragged(self.plot_manager.otherlines['vline'].value())
            self.ui.thresholdPos.blockSignals(False)

        if self.fftui and not is_zoomed:
            self.fftui.reset_for_timescale_change()
            self.fftui.reset_analysis_state()

    def depth_changed(self):
        self.state.expect_samples = self.ui.depthBox.value()
        self.allocate_xy_data()
        self.trigger_pos_reset()  # Reset trigger position to center after depth change
        self.controller.send_trigger_info_all()  # Update hardware with new trigger position
        self.plot_manager.reset_zoom_roi_position()  # Reset zoom ROI to default position

    def change_channel_color(self):
        options = QColorDialog.ColorDialogOptions()
        if sys.platform.startswith('linux'):
            options |= QColorDialog.DontUseNativeDialog
        color = QColorDialog.getColor(self.plot_manager.linepens[self.state.activexychannel].color(), self, options=options)
        if color.isValid():
            channel_idx = self.state.activexychannel
            # Update the pen color
            self.plot_manager.linepens[channel_idx].setColor(color)
            # Apply the updated pen to the plot line
            if channel_idx < len(self.plot_manager.lines):
                self.plot_manager.lines[channel_idx].setPen(self.plot_manager.linepens[channel_idx])
            # Update reference line color if a reference exists for this channel
            if channel_idx in self.reference_data:
                self.plot_manager.update_reference_line_color(channel_idx)
            # Update peak detect line color if peak detect is enabled for this channel
            if channel_idx in self.plot_manager.peak_max_line:
                base_pen = self.plot_manager.linepens[channel_idx]
                peak_color = base_pen.color()
                width = base_pen.width()
                peak_pen = pg.mkPen(color=peak_color, width=width, style=QtCore.Qt.DotLine)
                self.plot_manager.peak_max_line[channel_idx].setPen(peak_pen)
                self.plot_manager.peak_min_line[channel_idx].setPen(peak_pen)
                # Update zoom window peak detect line color if zoom window is open
                if self.zoom_window and self.zoom_window.isVisible():
                    self.zoom_window.update_peak_detect_lines(self.plot_manager)
            self.select_channel()  # Re-call to update color box and LEDs

    def about_dialog(self):
        QMessageBox.about(self, "Haasoscope Pro Qt",
                          f"A PyQt5 application for the Haasoscope Pro\n\nVersion {self.state.softwareversion:.2f}")

    def take_screenshot(self):
        pixmap = self.grab()
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"HaasoscopePro_{timestamp}.png"
        pixmap.save(filename)
        print(f"Screenshot saved as {filename}")

    def toggle_recording(self):
        if not self.recorder.is_recording:
            if self.recorder.start(): self.ui.actionRecord.setText("Stop recording")
        else:
            self.recorder.stop()
            self.ui.actionRecord.setText("Record to file")

    def save_setup(self):
        """Save current scope setup to a JSON file."""
        save_setup(self)

    def load_setup(self):
        """Load scope setup from a JSON file and restore the state."""
        load_setup(self)

    def update_firmware(self):
        from PyQt5.QtWidgets import QProgressDialog
        from PyQt5.QtCore import Qt

        board = self.state.activeboard
        reply = QMessageBox.question(self, 'Confirmation', f'Update firmware on board {board} with firmware {self.state.firmwareversion[board]}\nto the one in this software?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.No: return
        if not self.state.paused: self.dostartstop()  # Pause

        # Create progress dialog
        progress = QProgressDialog("Starting firmware update...", None, 0, 100, self)
        progress.setWindowTitle("Firmware Update")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)  # No cancel button
        progress.show()

        def progress_callback(label, value, maximum):
            progress.setLabelText(label)
            progress.setValue(value)
            QtWidgets.QApplication.processEvents()  # Allow UI to update

        success, message = self.controller.update_firmware(board, progress_callback=progress_callback)

        progress.close()
        QMessageBox.information(self, "Firmware Update", message)
        if success: self.ui.runButton.setEnabled(False)

    def verify_firmware(self):
        from PyQt5.QtWidgets import QProgressDialog
        from PyQt5.QtCore import Qt

        board = self.state.activeboard
        reply = QMessageBox.question(self, 'Confirmation', f'Verify firmware on board {board} with firmware {self.state.firmwareversion[board]}\nmatches the one in this software?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.No: return
        if not self.state.paused: self.dostartstop()  # Pause

        # Create progress dialog
        progress = QProgressDialog("Starting firmware verification...", None, 0, 100, self)
        progress.setWindowTitle("Firmware Verification")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)  # No cancel button
        progress.show()

        def progress_callback(label, value, maximum):
            progress.setLabelText(label)
            progress.setValue(value)
            QtWidgets.QApplication.processEvents()  # Allow UI to update

        success, message = self.controller.update_firmware(board, verify_only=True, progress_callback=progress_callback)

        progress.close()
        QMessageBox.information(self, "Firmware Verify", message)

    def set_channel_frame(self):
        s = self.state
        is_trigger_channel = not (s.doexttrig[s.activeboard] or s.doextsmatrig[s.activeboard] or s.triggerchan[
            s.activeboard] != s.activexychannel % 2)
        self.ui.chanColor.setFrameStyle(QFrame.Box if is_trigger_channel else QFrame.NoFrame)

    def chanon_changed(self, checked):
        """Toggles the visibility of the currently selected channel's trace."""
        # Update the average line's pen and visibility, which depends on this checkbox
        # This will also update the main line visibility correctly via update_channel_visibility()
        self.set_average_line_pen()

    def sync_persistence_ui(self):
        """Sync persistence UI controls with the active channel's settings."""
        s = self.state
        active_channel = s.activexychannel
        if s.num_board<1: return

        # Block signals to prevent triggering handlers while syncing
        self.ui.persistTbox.blockSignals(True)
        self.ui.persistlinesCheck.blockSignals(True)
        self.ui.persistAvgCheck.blockSignals(True)
        self.ui.persistheatCheck.blockSignals(True)

        # Convert persist_time back to the spinbox value (reverse of the formula)
        persist_time_ms = s.persist_time[active_channel]
        if persist_time_ms > 0:
            # Reverse formula: value = log2(persist_time_ms / 50)
            import math
            value = int(math.log2(persist_time_ms / 50))
        else:
            value = 0
        self.ui.persistTbox.setValue(value)

        # Update checkboxes
        self.ui.persistlinesCheck.setChecked(s.persist_lines_enabled[active_channel])
        self.ui.persistAvgCheck.setChecked(s.persist_avg_enabled[active_channel])
        self.ui.persistheatCheck.setChecked(s.persist_heatmap_enabled[active_channel])

        # Unblock signals
        self.ui.persistTbox.blockSignals(False)
        self.ui.persistlinesCheck.blockSignals(False)
        self.ui.persistAvgCheck.blockSignals(False)
        self.ui.persistheatCheck.blockSignals(False)

    def set_persistence(self, value):
        """Handle persistence time changes from the UI."""
        s = self.state
        active_channel = s.activexychannel

        # Store to state
        persist_time_ms = 50 * pow(2, value) if value > 0 else 0
        s.persist_time[active_channel] = persist_time_ms

        # Update plot manager
        self.plot_manager.set_persistence(value, active_channel)
        self.set_average_line_pen()

        # Update zoom window persist lines (including when turned off)
        if self.zoom_window and self.zoom_window.isVisible():
            self.zoom_window.update_persist_lines(self.plot_manager)

    def update_channel_visibility(self, channel_index):
        """Update visibility for a specific channel based on its state."""
        s = self.state

        # Get channel settings
        is_chan_on = s.channel_enabled[channel_index]
        show_persist_lines = s.persist_lines_enabled[channel_index]
        show_persist_avg = s.persist_avg_enabled[channel_index]
        show_persist_heatmap = s.persist_heatmap_enabled[channel_index]
        persist_time = s.persist_time[channel_index]

        # Get the line objects
        main_line = self.plot_manager.lines[channel_index]
        average_line = self.plot_manager.average_lines.get(channel_index)
        heatmap_item = self.plot_manager.heatmap_manager.persist_heatmap_items.get(channel_index)

        # If channel is not enabled, hide everything
        if not is_chan_on:
            main_line.setVisible(False)
            if average_line:
                average_line.setVisible(False)
            if channel_index in self.plot_manager.persist_lines_per_channel:
                for item_data in self.plot_manager.persist_lines_per_channel[channel_index]:
                    item = item_data[0]
                    item.setVisible(False)
            if heatmap_item:
                heatmap_item.setVisible(False)
            return

        # Channel is enabled - apply visibility rules

        # Average line visibility
        if average_line:
            average_line.setVisible(show_persist_avg)

        # Persist heatmap visibility (mutually exclusive with persist lines)
        if heatmap_item:
            heatmap_item.setVisible(show_persist_heatmap and persist_time > 0)

        # Persist lines visibility (hide if heatmap is enabled)
        if channel_index in self.plot_manager.persist_lines_per_channel:
            for item_data in self.plot_manager.persist_lines_per_channel[channel_index]:
                item = item_data[0]
                item.setVisible(show_persist_lines and not show_persist_heatmap)

        # Main trace visibility: hide ONLY if (average is on OR heatmap is on) AND persist lines are off AND persist time > 0
        if (show_persist_avg or show_persist_heatmap) and not show_persist_lines and persist_time > 0:
            main_line.setVisible(False)
        else:
            main_line.setVisible(True)

    def set_average_line_pen(self):
        """
        Updates the appearance and visibility of the main trace, the average trace,
        and the faint persistence traces based on UI settings.
        """
        s = self.state
        active_channel = s.activexychannel

        # Store UI checkbox states to the active channel's state
        s.persist_lines_enabled[active_channel] = self.ui.persistlinesCheck.isChecked()
        s.persist_avg_enabled[active_channel] = self.ui.persistAvgCheck.isChecked()
        s.persist_heatmap_enabled[active_channel] = self.ui.persistheatCheck.isChecked()
        s.channel_enabled[active_channel] = self.ui.chanonCheck.isChecked()

        # Update the pen style/color of the average line
        self.plot_manager.set_average_line_pen()

        # If heatmap mode was just enabled, regenerate the heatmap from current persist lines
        if s.persist_heatmap_enabled[active_channel] and s.persist_time[active_channel] > 0:
            if active_channel in self.plot_manager.persist_lines_per_channel:
                persist_lines = self.plot_manager.persist_lines_per_channel[active_channel]
                self.plot_manager.heatmap_manager.regenerate(active_channel, persist_lines)

        # Update visibility for the active channel
        self.update_channel_visibility(active_channel)

        # Update zoom window persist lines visibility
        if self.zoom_window and self.zoom_window.isVisible():
            self.zoom_window.update_persist_lines(self.plot_manager)

    # #########################################################################
    # ## Slot Implementations (Callbacks for UI events)
    # #########################################################################

    def toggle_xy_view_slot(self, checked):
        """Slot for the 'XY Plot' menu action."""
        s = self.state

        if checked:
            # Entering XY mode - create and show XY window
            if self.xy_window is None:
                self.xy_window = XYWindow(self, self.state, self.plot_manager)
                # Connect signal to handle window closing
                self.xy_window.window_closed.connect(self.on_xy_window_closed)
                # Position to the left of main window with bottom edges aligned
                self.xy_window.position_relative_to_main(self)

            self.xy_window.show()
            self.xy_window.raise_()
            self.xy_window.activateWindow()
            s.xy_mode = True
        else:
            # Exiting XY mode - hide XY window
            if self.xy_window is not None:
                self.xy_window.hide()
            s.xy_mode = False

    def on_xy_window_closed(self):
        """Slot called when the XY window is closed by the user."""
        # Uncheck the menu item
        self.ui.actionXY_Plot.setChecked(False)
        # Update state
        self.state.xy_mode = False

    def toggle_markers_slot(self, checked):
        """Slot for the 'Markers' menu action - updates both main and zoom windows."""
        # Update main plot markers
        self.plot_manager.set_markers(checked)

        # Update zoom window markers if it exists and is visible
        if self.zoom_window is not None and self.zoom_window.isVisible():
            self.zoom_window.set_markers(checked)

    def toggle_zoom_window_slot(self, checked):
        """Slot for the 'Zoom Window' menu action."""
        if checked:
            # Create and show zoom window
            if self.zoom_window is None:
                self.zoom_window = ZoomWindow(self, self.state, self.plot_manager)
                # Connect signal to handle window closing
                self.zoom_window.window_closed.connect(self.on_zoom_window_closed)
                # Position to the right of main window with tops aligned
                self.zoom_window.position_relative_to_main(self)

            self.zoom_window.show()
            self.zoom_window.raise_()
            self.zoom_window.activateWindow()

            # Show the zoom ROI on the main plot
            self.plot_manager.show_zoom_roi()

            # Sync marker state to zoom window
            if self.ui.actionMarkers.isChecked():
                self.zoom_window.set_markers(True)
        else:
            # Hide zoom window and ROI
            if self.zoom_window is not None:
                self.zoom_window.hide()
            self.plot_manager.hide_zoom_roi()

    def on_zoom_window_closed(self):
        """Slot called when the zoom window is closed by the user."""
        # Uncheck the menu item
        self.ui.actionZoom_window.setChecked(False)
        # Hide the ROI
        self.plot_manager.hide_zoom_roi()

    def on_zoom_region_changed(self, x_range, y_range):
        """Slot called when the zoom ROI is moved or resized."""
        if self.zoom_window and self.zoom_window.isVisible():
            # Update the zoom window's view range
            self.zoom_window.set_zoom_region(x_range, y_range)

    def open_math_channels(self):
        """Slot for the 'Math Channels' menu action."""
        if self.math_window is None:
            self.math_window = MathChannelsWindow(self)
            # Connect the signal to update plots when math channels change
            self.math_window.math_channels_changed.connect(lambda: self.update_math_channels())
        self.math_window.show()
        self.math_window.raise_()
        self.math_window.activateWindow()

    def update_math_channels(self):
        """Update math channel plot lines and calculate current data."""
        if self.math_window is None:
            return

        # Update the plot lines (create/remove as needed)
        self.plot_manager.update_math_channel_lines(self.math_window)

        # Update math reference lines
        self.plot_manager.update_math_reference_lines(self.math_window, self)

        # Refresh XY window channel list if visible
        if self.xy_window is not None and self.xy_window.isVisible():
            self.xy_window.refresh_channel_list()

        # Calculate and display current data if we have data
        if hasattr(self, 'xydata') and len(self.math_window.math_channels) > 0:
            # Use stabilized data (after trigger stabilizers are applied)
            math_results = self.math_window.calculate_math_channels(self.plot_manager.stabilized_data)
            self.plot_manager.update_math_channel_data(math_results)

    def open_dummy_server_config(self):
        """Open or bring to front the dummy server configuration dialog."""
        if self.dummy_server_config_dialog is None:
            self.dummy_server_config_dialog = DummyServerConfigDialog(self, self.usbs)
            self.dummy_server_config_dialog.position_relative_to_main(self)
            self.dummy_server_config_dialog.show()
        else:
            # Dialog exists - just bring it to front and reposition
            self.dummy_server_config_dialog.position_relative_to_main(self)
            self.dummy_server_config_dialog.raise_()
            self.dummy_server_config_dialog.show()

    def open_history_window(self):
        """Slot for the 'History window' menu action."""
        # Track whether we're currently running
        self.was_running_before_history = not self.state.paused

        # Update the history window with current buffer contents
        self.history_window.update_event_list(list(self.history_buffer))

        # Position the window to the left of the main window
        self.history_window.position_relative_to_main(self)

        self.history_window.show()
        self.history_window.raise_()
        self.history_window.activateWindow()

    def on_history_event_selected(self, event_index):
        """Slot called when user selects a historical event from the list."""
        # Pause data acquisition
        if self.update_timer.isActive():
            self.update_timer.stop()
            self.measurement_timer.stop()
            self.displaying_history = True
            self.current_history_index = event_index
            self.state.paused = True
            self.ui.runButton.setChecked(False)

        # Get the selected event data from the buffer
        if 0 <= event_index < len(self.history_buffer):
            event = self.history_buffer[event_index]

            # Replace current data with historical data
            self.xydata = event['xydata']
            self.xydatainterleaved = event['xydatainterleaved']

            # Update the plot with the historical data
            self.plot_manager.update_plots(self.xydata, self.xydatainterleaved)

            # Update math channels if any
            math_results = {}
            if self.math_window and len(self.math_window.math_channels) > 0:
                math_results = self.math_window.calculate_math_channels(self.plot_manager.stabilized_data)
                self.plot_manager.update_math_channel_data(math_results)

            # Update XY window if visible (after math channels calculated)
            if self.state.xy_mode and self.xy_window is not None and self.xy_window.isVisible():
                self.xy_window.update_xy_plot(self.xydata, math_results)

            # Update Zoom window if visible
            if self.zoom_window is not None and self.zoom_window.isVisible():
                self.zoom_window.update_zoom_plot(self.plot_manager.stabilized_data, math_results)
                self.zoom_window.update_trigger_and_cursor_lines(self.plot_manager)
                self.zoom_window.update_reference_waveforms(
                    self.reference_data, self.reference_visible,
                    self.math_reference_data, self.math_reference_visible
                )

    def resume_live_acquisition(self):
        """Resume live data acquisition after viewing history."""
        if self.displaying_history:
            self.displaying_history = False
            self.current_history_index = None
            self.update_timer.start(0)

    def on_history_window_closed(self):
        """Slot called when the history window is closed."""
        # If we were running when the history window was opened, resume running
        if self.was_running_before_history and self.displaying_history:
            self.displaying_history = False
            self.current_history_index = None
            self.state.paused = False
            self.ui.runButton.setChecked(True)
            self.update_timer.start(0)
            self.measurement_timer.start(20)

    def on_history_loaded(self, event_buffer):
        """Slot called when history is loaded from a file."""
        # Replace the current history buffer with the loaded events
        self.history_buffer.clear()
        for event in event_buffer:
            self.history_buffer.append(event)

    def take_reference_waveform(self):
        """
        Slot for 'Take Reference'. Captures the active waveform's data,
        converts its time axis to absolute nanoseconds, and stores it.
        Uses non-resampled data to ensure correct FFT and math operations.
        """
        s = self.state
        active_channel = s.activexychannel

        # Get non-resampled data for the reference (important for math channels and FFT)
        if self.plot_manager.stabilized_data_noresamp[active_channel] is not None:
            x_data, y_data = self.plot_manager.stabilized_data_noresamp[active_channel]

            # Convert the x-axis data to nanoseconds for storage
            x_data_in_ns = x_data * s.nsunits
            y_data = np.copy(y_data)  # Make a copy

            # Get current line width for this channel
            line_width = self.plot_manager.linepens[active_channel].width()

            # Store reference with doresamp and width info for later use
            self.reference_data[active_channel] = {
                'x_ns': x_data_in_ns,
                'y': y_data,
                'doresamp': s.doresamp[active_channel],
                'width': line_width
            }

            # Set the reference visibility to True for this channel
            self.reference_visible[active_channel] = True

            # Update the checkbox to reflect the new visibility state
            self.update_reference_checkbox_state()

            # Update the Clear all menu state
            self.update_clear_all_reference_state()

            # Trigger a redraw to show the new reference immediately
            self.time_changed()

    def toggle_reference_waveform_visibility(self):
        """Slot for 'Show Reference'. Toggles visibility for the active channel's reference."""
        s = self.state
        active_channel = s.activexychannel

        # Toggle the visibility state for the active channel
        is_checked = self.ui.actionShow_Reference.isChecked()
        self.reference_visible[active_channel] = is_checked

        # Trigger a redraw to apply the visibility change
        self.time_changed()

    def clear_all_references(self):
        """Slot for 'Clear all'. Hides all reference waveforms for all channels."""
        # Set all reference visibility flags to False
        for channel_idx in range(self.plot_manager.nlines):
            self.reference_visible[channel_idx] = False

        # Update the checkbox for the active channel
        self.update_reference_checkbox_state()

        # Update the Clear all menu state
        self.update_clear_all_reference_state()

        # Trigger a redraw to hide all references
        self.time_changed()

    def update_clear_all_reference_state(self):
        """Enable/disable the 'Clear all' action based on whether any references exist."""
        has_references = bool(self.reference_data) or bool(self.math_reference_data)
        self.ui.actionClear_all.setEnabled(has_references)

    def save_reference_lines_slot(self):
        """Slot for saving reference waveforms to a file."""
        save_reference_lines(self, self.reference_data, self.reference_visible,
                           self.math_reference_data, self.math_reference_visible)

    def load_reference_lines_slot(self):
        """Slot for loading reference waveforms from a file."""
        success = load_reference_lines(self, self.reference_data, self.reference_visible,
                                      self.math_reference_data, self.math_reference_visible)
        if success:
            # Update the checkbox for the active channel
            self.update_reference_checkbox_state()
            # Update the Clear all menu state
            self.update_clear_all_reference_state()
            # Update math window button states if it's open
            if self.math_window is not None:
                self.math_window.update_button_states()
            # Trigger a redraw to show the loaded references
            self.time_changed()

    def fft_clicked(self):
        """Toggles the FFT window state for the active channel."""
        active_channel_name = f"CH{self.state.activexychannel + 1}"
        is_checked = self.ui.fftCheck.isChecked()
        self.state.fft_enabled[active_channel_name] = is_checked

        if self.fftui is None:
            self.fftui = FFTWindow(self)
            # Connect the window_closed signal to our handler
            self.fftui.window_closed.connect(self.on_fft_window_closed)
        should_show = any(self.state.fft_enabled.values())
        if should_show: self.fftui.show()
        else: self.fftui.hide()
    
    def on_fft_window_closed(self):
        """Called when FFT window is closed by user."""
        # Disable FFT for all channels and uncheck the checkbox
        self.state.fft_enabled.clear()
        self.ui.fftCheck.setChecked(False)

        # Also disable FFT for all math channels
        if self.math_window is not None:
            for math_def in self.math_window.math_channels:
                math_def['fft_enabled'] = False
            # Update the UI if the math window is visible
            if self.math_window.isVisible():
                self.math_window.update_button_states()

        should_show = any(self.state.fft_enabled.values())
        if should_show: self.fftui.show()
        else: self.fftui.hide()

    def update_fft_checkbox_state(self):
        """Updates the 'FFT' checkbox to reflect the state of the active channel."""
        active_channel_name = f"CH{self.state.activexychannel + 1}"
        if active_channel_name not in self.state.fft_enabled:
            self.state.fft_enabled[active_channel_name] = False

        self.ui.fftCheck.blockSignals(True)
        self.ui.fftCheck.setChecked(self.state.fft_enabled[active_channel_name])
        self.ui.fftCheck.blockSignals(False)

    def update_fir_checkbox_state(self):
        """Updates the 'Apply FIR corrections' checkbox to reflect if corrections are available for current mode."""
        s = self.state

        # Check if corrections are available for the current mode
        is_oversampling = s.dooversample[s.activeboard]
        is_interleaved = s.dointerleaved[s.activeboard]
        is_twochannel = s.dotwochannel[s.activeboard]

        if is_oversampling and is_interleaved:
            # Interleaved oversampling mode: check if interleaved corrections are available
            has_corrections = s.fir_coefficients_interleaved is not None
        elif is_oversampling:
            # Oversampling only (not interleaved): check if oversampling corrections are available
            has_corrections = (s.fir_coefficients_oversample[0] is not None and
                              s.fir_coefficients_oversample[1] is not None)
        elif is_twochannel:
            # Two-channel mode: check if two-channel corrections are available
            has_corrections = s.fir_coefficients_twochannel is not None
        else:
            # Normal mode: check if normal corrections are available
            has_corrections = s.fir_coefficients is not None

        # Enable/disable menu item based on whether corrections are available
        self.ui.actionApply_FIR_corrections.setEnabled(has_corrections)

        # Checkbox should be checked if corrections are available AND enabled
        should_be_checked = has_corrections and s.fir_correction_enabled

        # If corrections aren't available, uncheck and disable
        if not has_corrections:
            should_be_checked = False
            s.fir_correction_enabled = False

        self.ui.actionApply_FIR_corrections.blockSignals(True)
        self.ui.actionApply_FIR_corrections.setChecked(should_be_checked)
        self.ui.actionApply_FIR_corrections.blockSignals(False)

    def update_reference_checkbox_state(self):
        """Updates the 'Show Reference' checkbox to reflect the active channel's reference visibility."""
        s = self.state
        active_channel = s.activexychannel

        # Check if this channel has a reference and if it's visible
        is_visible = self.reference_visible.get(active_channel, False)

        self.ui.actionShow_Reference.blockSignals(True)
        self.ui.actionShow_Reference.setChecked(is_visible)
        self.ui.actionShow_Reference.blockSignals(False)

    def update_peak_detect_checkbox_state(self):
        """Updates the 'Peak waveform' checkbox to reflect the active channel's peak detect state."""
        active_channel = self.state.activexychannel

        # Check if this channel has peak detect enabled
        is_enabled = self.plot_manager.peak_detect_enabled.get(active_channel, False)

        self.ui.actionPeak_detect.blockSignals(True)
        self.ui.actionPeak_detect.setChecked(is_enabled)
        self.ui.actionPeak_detect.blockSignals(False)

    def update_pulse_stabilizer_checkbox_state(self):
        """Updates the 'Pulse stabilizer' checkbox to reflect the active board's state."""
        active_board = self.state.activeboard

        self.ui.actionPulse_stabilizer.blockSignals(True)
        self.ui.actionPulse_stabilizer.setChecked(self.state.pulse_stabilizer_enabled[active_board])
        self.ui.actionPulse_stabilizer.blockSignals(False)

    def twochan_changed(self):
        """Switches between single and dual channel mode FOR THE ACTIVE BOARD."""
        s = self.state
        is_two_channel = self.ui.twochanCheck.isChecked()
        active_board = s.activeboard

        # If switching from two-channel to single-channel, disable FFT on the second channel
        if s.dotwochannel[active_board] and not is_two_channel:
            second_chan_index = active_board * s.num_chan_per_board + 1
            second_chan_name = f"CH{second_chan_index + 1}"
            s.fft_enabled[second_chan_name] = False
            if self.fftui:
                self.fftui.clear_plot(second_chan_name)

            # If no other channels have FFT enabled, hide the window
            if not any(s.fft_enabled.values()):
                self.ui.fftCheck.setChecked(False) # Uncheck the main box
                if self.fftui:
                    self.fftui.hide()

            # If trigger is on Ch 1, switch to Ch 0 with same edge direction
            current_trigger_index = self.ui.risingfalling_comboBox.currentIndex()
            if current_trigger_index == 2:  # Rising (Ch 1) -> Rising (Ch 0)
                self.ui.risingfalling_comboBox.setCurrentIndex(0)
            elif current_trigger_index == 3:  # Falling (Ch 1) -> Falling (Ch 0)
                self.ui.risingfalling_comboBox.setCurrentIndex(1)

        # The next event after a mode switch can be glitchy, so we'll skip it.
        s.skip_next_event = True

        # Store the old state before updating
        old_two_channel_state = s.dotwochannel[active_board]

        # 1. Update the state for the active board ONLY
        s.dotwochannel[active_board] = is_two_channel

        # When switching TO two-channel mode, enable ch1 (switching FROM two-channel mode, ch1 stays as user set it)
        if not old_two_channel_state and is_two_channel:
            ch1_index = active_board * s.num_chan_per_board + 1
            s.channel_enabled[ch1_index] = True

        # Handle math channel display updates after state change
        if self.math_window:
            ch1_index = active_board * s.num_chan_per_board + 1
            needs_ui_update = False

            # Check all math channels to see if they use Ch 1 of this board
            for math_def in self.math_window.math_channels:
                ch1 = math_def['ch1']
                ch2 = math_def.get('ch2')

                # Check if either input uses this channel
                uses_ch1 = (ch1 == ch1_index) or (ch2 == ch1_index)

                if uses_ch1:
                    # If switching to two-channel mode, only re-enable if it was displayed before
                    if not old_two_channel_state and is_two_channel:
                        # Only re-enable display if it was previously auto-disabled (not manually unchecked)
                        # We track this with 'auto_disabled' flag
                        if math_def.get('auto_disabled', False):
                            math_def['displayed'] = True
                            math_def['auto_disabled'] = False
                        needs_ui_update = True
                    # If switching to single-channel mode, disable display and mark as auto-disabled
                    elif old_two_channel_state and not is_two_channel:
                        # Only mark as auto-disabled if it was currently displayed
                        if math_def.get('displayed', True):
                            math_def['auto_disabled'] = True
                        math_def['displayed'] = False
                        needs_ui_update = True

            # Update the math window UI if changes were made
            if needs_ui_update:
                if self.math_window.isVisible():
                    self.math_window.update_button_states()
                self.math_window.math_channels_changed.emit()

        # 2. Reconfigure the hardware for the active board. This can reset settings.
        setupboard(self.controller.usbs[active_board], s.dopattern, is_two_channel, s.dooverrange, s.basevoltage == 200)
        self.controller.tell_downsample(self.controller.usbs[active_board], s.downsample, active_board)

        # 3. Re-apply all stored settings for the active board back to the hardware
        self._sync_board_settings_to_hardware(active_board)

        # 4. When enabling two-channel mode while zoomed, ensure channel 1 has correct doresamp
        if is_two_channel and s.downsample < 0:
            ch1_index = active_board * s.num_chan_per_board + 1
            if not s.resamp_overridden[ch1_index] and s.doresamp[ch1_index] != 4:
                s.doresamp[ch1_index] = 4

        # 5. Set a grace period to prevent false PLL resets during the switch
        s.pll_reset_grace_period = 5

        # 6. Update the rest of the application
        self.allocate_xy_data()
        self.time_changed()
        self._update_channel_mode_ui()
        self.select_channel()

        # 6. Update math window channel lists (availability of Ch 1 changed)
        if self.math_window:
            self.math_window.update_channel_list()

        # 7. Update XY window channel lists (availability of Ch 1 changed)
        if self.xy_window is not None and self.xy_window.isVisible():
            self.xy_window.refresh_channel_list()

        # 8. Clear and recreate zoom window channel lines (x-axis structure changes in two-channel mode)
        if self.zoom_window is not None and self.zoom_window.isVisible():
            self.zoom_window.clear_channel_lines()

    def gain_changed(self):
        """Handles changes to the gain slider."""
        s = self.state
        s.gain[s.activexychannel] = self.ui.gainBox.value()

        self.controller.set_channel_gain(s.activeboard, s.selectedchannel, s.gain[s.activexychannel])
        if s.dooversample[s.activeboard] and s.activeboard % 2 == 0:
            self.controller.set_channel_gain(s.activeboard + 1, s.selectedchannel, s.gain[s.activexychannel])
            s.gain[s.activexychannel + s.num_chan_per_board] = s.gain[s.activexychannel]

        # Calculate the base Volts per Division
        db = s.gain[s.activexychannel]
        v_per_div = (s.basevoltage / 1000.) * s.tenx[s.activexychannel] / pow(10, db / 20.)
        if s.dooversample[s.activeboard]: v_per_div *= 2.0
        if not s.mohm[s.activexychannel]: v_per_div /= 2.0

        oldvperd = s.VperD[s.activexychannel]
        s.VperD[s.activexychannel] = v_per_div
        if s.dooversample[s.activeboard] and s.activeboard % 2 == 0:
            s.VperD[s.activexychannel + s.num_chan_per_board] = v_per_div

        if v_per_div != 0:
            self.ui.offsetBox.setValue(int(self.ui.offsetBox.value() * oldvperd / v_per_div))

        # --- NEW CUSTOM ROUNDING AND FORMATTING LOGIC ---
        mv_per_div = v_per_div * 1000.0

        if mv_per_div > 50:
            # If over 50 mV, round to the nearest whole number
            final_val = round(mv_per_div)
            display_text = f"{final_val:.0f} mV/div"
        else:
            # Otherwise, round to the nearest 0.5
            final_val = round(mv_per_div * 2) / 2.0
            display_text = f"{final_val:.1f} mV/div"

        self.ui.VperD.setText(display_text)
        # --- END OF NEW LOGIC ---

        if self.ui.gainBox.value() > 24:
            self.ui.gainBox.setSingleStep(2)
        else:
            self.ui.gainBox.setSingleStep(6)

        self.plot_manager.update_right_axis()
        self.plot_manager.update_cursor_display()

    def offset_changed(self):
        """Handles changes to the offset slider."""
        s = self.state
        s.offset[s.activexychannel] = self.ui.offsetBox.value()

        # UI layer calculates the scaling factor based on current state
        scaling = 1000 * s.VperD[s.activexychannel] / 160.0
        if s.acdc[s.activexychannel]:
            scaling *= 245.0 / 160.0
        final_scaling = scaling / s.tenx[s.activexychannel]

        # Call the controller method with the required 'scaling' argument
        self.controller.set_channel_offset(s.activeboard, s.selectedchannel, s.offset[s.activexychannel], final_scaling)

        # Also update the coupled board in oversampling mode
        if s.dooversample[s.activeboard] and s.activeboard % 2 == 0:
            self.controller.set_channel_offset(s.activeboard + 1, s.selectedchannel, s.offset[s.activexychannel],
                                               final_scaling)
            s.offset[s.activexychannel + s.num_chan_per_board] = s.offset[s.activexychannel]

        # UI update logic remains here
        v_offset = (scaling / (1000 * s.VperD[s.activexychannel] / 160.0)) * (
                    1000 * s.VperD[s.activexychannel] / 160.0) * 1.5 * s.offset[s.activexychannel]
        if s.acdc[s.activexychannel]: v_offset *= (160.0 / 245.0)
        self.ui.Voff.setText(f"{int(v_offset)} mV")

    def skew_changed(self):
        """Handles changes to the time skew offset."""
        s = self.state
        s.time_skew[s.activexychannel] = self.ui.skewBox.value()

    def channel_name_changed(self):
        """Handles changes to the channel name."""
        s = self.state
        s.channel_names[s.activexychannel] = self.ui.channameEdit.text()
        # Update the legend to reflect the new name
        self.plot_manager.update_legend()

    def acdc_changed(self, checked):
        s = self.state
        s.acdc[s.activexychannel] = bool(checked)
        self.controller.set_acdc(s.activeboard, s.selectedchannel, s.acdc[s.activexychannel])
        if s.dooversample[s.activeboard] and s.activeboard % 2 == 0:
            s.acdc[s.activexychannel + s.num_chan_per_board] = bool(checked)
            self.controller.set_acdc(s.activeboard + 1, s.selectedchannel, s.acdc[s.activexychannel])
        self.offset_changed()  # Recalculate offset text due to different scaling in AC mode

    def mohm_changed(self, checked):
        s = self.state
        s.mohm[s.activexychannel] = bool(checked)
        self.controller.set_mohm(s.activeboard, s.selectedchannel, s.mohm[s.activexychannel])
        self.gain_changed()  # Recalculate V/div

    def att_changed(self, checked):
        s = self.state
        s.att[s.activexychannel] = bool(checked)
        self.controller.set_att(s.activeboard, s.selectedchannel, s.att[s.activexychannel])
        # Also set it for the other oversampling board
        if s.dooversample[s.activeboard] and s.activeboard % 2 == 0:
            s.att[s.activexychannel+s.num_chan_per_board] = bool(checked)
            self.controller.set_att(s.activeboard+1, s.selectedchannel, s.att[s.activexychannel])

    def tenx_changed(self, checked):
        s = self.state
        s.tenx[s.activexychannel] = 10 if checked else 1
        self.gain_changed()  # Recalculate V/div

    def oversamp_changed(self, checked):
        s = self.state
        board = s.activeboard

        # When enabling oversampling, validate and configure board N+1
        if bool(checked):
            # Ensure board N+1 is in single-channel mode
            if s.dotwochannel[board + 1]:
                s.dotwochannel[board + 1] = False
                self.controller.set_twochannel(board + 1, False)
                print(f"Auto-configured board {board+1} to single-channel mode for oversampling")

            # Ensure board N+1 is on external trigger (this was already done, but moved here for clarity)
            if not s.doexttrig[board + 1]:
                s.doexttrig[board + 1] = True
                self.controller.set_exttrig(board + 1, True)
                print(f"Auto-configured board {board+1} to external trigger mode for oversampling")

            # Ensure board N+1 is on external clock source
            from board import clockused, switchclock
            if clockused(self.controller.usbs[board + 1], board + 1, quiet=True) == 0:
                # Board is on internal clock, switch to external
                if switchclock(self.controller.usbs[board + 1], board + 1, external=True):
                    print(f"Auto-configured board {board+1} to external clock source for oversampling")
                else:
                    print(f"WARNING: Failed to switch board {board+1} to external clock source")

        s.dooversample[board] = bool(checked)
        s.dooversample[board + 1] = bool(checked)
        s.skip_next_event = True  # Skip next event after oversampling change

        # Reset persistence settings for both boards in the oversampling pair (ch0 only)
        ch0_board1 = board * s.num_chan_per_board
        ch0_board2 = (board + 1) * s.num_chan_per_board

        for ch_idx in [ch0_board1, ch0_board2]:
            s.persist_time[ch_idx] = 0
            s.persist_lines_enabled[ch_idx] = True
            s.persist_avg_enabled[ch_idx] = True
            # Clear any existing persistence data
            self.plot_manager.clear_persist(ch_idx)
            # Update visibility (might have been hidden if persist avg was on and lines were off)
            self.update_channel_visibility(ch_idx)

        # If we're resetting the active channel, update UI to reflect defaults
        if s.activexychannel in [ch0_board1, ch0_board2]:
            self.sync_persistence_ui()

        self.controller.set_oversampling(board, bool(checked))
        if bool(checked):
            self.ui.interleavedCheck.setEnabled(True)
            self.ui.twochanCheck.setEnabled(False)
            if self.ui.actionAuto_oversample_alignment.isChecked():
                autocalibration(self)
        else:
            self.ui.interleavedCheck.setEnabled(False)
            self.ui.interleavedCheck.setChecked(False)
            self.ui.twochanCheck.setEnabled(True)
            # When disabling oversampling, re-enable the odd board's ch0
            s.channel_enabled[ch0_board2] = True
            self.update_channel_visibility(ch0_board2)
            # Reset toff to default value of 100
            s.toff = 100
            self.ui.ToffBox.blockSignals(True)
            self.ui.ToffBox.setValue(100)
            self.ui.ToffBox.blockSignals(False)
            # Note: board+1 stays in external trigger mode for multi-board synchronization

        # Update autocalibration enabled state based on oversampling change
        self.update_autocalibration_enabled()

        self.gain_changed()
        self.offset_changed()
        all_colors = [pen.color() for pen in self.plot_manager.linepens]
        self.controller.do_leds(all_colors)

        # Update XY window channel lists (channel availability changed)
        if self.xy_window is not None and self.xy_window.isVisible():
            self.xy_window.refresh_channel_list()

        # Update FIR checkbox state (oversampling mode changed)
        self.update_fir_checkbox_state()

    def interleave_changed(self, checked):
        s = self.state
        board = s.activeboard
        s.dointerleaved[board] = bool(checked)
        s.dointerleaved[board + 1] = bool(checked)

        # Update visibility for the secondary board's channels
        # When interleaved, secondary board channels should be disabled
        c_secondary_ch0 = (board + 1) * s.num_chan_per_board
        c_secondary_ch1 = c_secondary_ch0 + 1
        if checked:
            s.channel_enabled[c_secondary_ch0] = False
            s.channel_enabled[c_secondary_ch1] = False
        else:
            # When disabling interleaving, re-enable the secondary board's channels
            # BUT: if we're still in oversampling mode (without interleaving),
            # we should only enable ch0 (single-channel mode)
            s.channel_enabled[c_secondary_ch0] = True
            if s.dooversample[board]:
                # Still in oversampling mode: keep ch1 disabled (single-channel)
                s.channel_enabled[c_secondary_ch1] = False
            else:
                # Not in oversampling mode: enable ch1
                s.channel_enabled[c_secondary_ch1] = True
        self.update_channel_visibility(c_secondary_ch0)
        self.update_channel_visibility(c_secondary_ch1)

        self.time_changed()
        all_colors = [pen.color() for pen in self.plot_manager.linepens]
        self.controller.do_leds(all_colors)

        # Update XY window channel lists (channel availability changed)
        if self.xy_window is not None and self.xy_window.isVisible():
            self.xy_window.refresh_channel_list()

        # Update FIR checkbox state (interleaving mode changed)
        self.update_fir_checkbox_state()

    def dopllreset(self):
        while self.state.downsamplezoom>1: self.time_slow()
        self.controller.pllreset(self.state.activeboard)

    def tad_changed(self, value):
        self.state.tad[self.state.activeboard] = value
        self.controller.set_tad(self.state.activeboard, value)

    def trigger_delta_changed(self, value):
        """Handle changes to trigger delta spinbox."""
        board = self.state.activeboard
        self.state.triggerdelta[board] = value
        self.controller.send_trigger_info(board)

    def rising_falling_changed(self, index):
        s = self.state
        active_board = s.activeboard
        if s.num_board<1: return

        # Index mapping:
        # 0: Rising (Ch 0), 1: Falling (Ch 0), 2: Rising (Ch 1), 3: Falling (Ch 1)
        # 4: Other boards, 5: External SMA

        # Determine if this is an external trigger mode
        is_other_boards = (index == 4)
        is_external_sma = (index == 5)

        # Update external trigger states
        old_doexttrig = s.doexttrig[active_board]
        s.doexttrig[active_board] = is_other_boards
        s.doextsmatrig[active_board] = is_external_sma

        # For channel-based triggers (indices 0-3)
        if index < 4:
            # Determine channel: 0-1 are Ch0, 2-3 are Ch1
            trigger_channel = 0 if index < 2 else 1
            # Determine edge: even indices are rising, odd are falling
            is_falling = (index % 2 == 1)

            s.triggerchan[active_board] = trigger_channel
            s.fallingedge[active_board] = is_falling
            s.triggertype[active_board] = 2 if is_falling else 1

            # Send trigger info to hardware
            self.controller.send_trigger_info(active_board)

            # Swap Risetime/Falltime measurements if edge direction changed
            if self.measurements:
                old_time_name = "Risetime" if is_falling else "Falltime"
                new_time_name = "Falltime" if is_falling else "Risetime"
                old_error_name = "Risetime error" if is_falling else "Falltime error"
                new_error_name = "Falltime error" if is_falling else "Risetime error"

                measurements_to_swap = []
                for measurement_key in list(self.measurements.active_measurements.keys()):
                    measurement_name, channel_key = measurement_key

                    if channel_key == "Global":
                        continue

                    if channel_key.startswith("B") and " Ch" in channel_key:
                        board_num = int(channel_key.split("B")[1].split(" ")[0])

                        if board_num == active_board:
                            if measurement_name in [old_time_name, old_error_name]:
                                measurements_to_swap.append(measurement_key)

                for old_key in measurements_to_swap:
                    measurement_name, channel_key = old_key

                    if measurement_name == old_time_name:
                        new_measurement_name = new_time_name
                    else:
                        new_measurement_name = new_error_name

                    del self.measurements.active_measurements[old_key]
                    new_key = (new_measurement_name, channel_key)
                    self.measurements.active_measurements[new_key] = True

                if measurements_to_swap:
                    self.measurements.update_measurements_display()
                    self.measurements.update_menu_checkboxes()

        # Handle external trigger mode changes
        if is_other_boards and not old_doexttrig:
            self.controller.set_exttrig(active_board, True)
        elif old_doexttrig and not is_other_boards:
            self.controller.set_exttrig(active_board, False)

        # Update channel frame
        self.set_channel_frame()

    def tot_changed(self, value):
        """Handle changes to time over threshold spinbox."""
        board = self.state.activeboard
        self.state.triggertimethresh[board] = value
        self.controller.send_trigger_info(board)
        self.update_trigger_spinbox_tooltip(self.ui.totBox, "Time over threshold required to trigger")

    def trigger_delay_changed(self, value):
        """Handle changes to trigger delay spinbox."""
        board = self.state.activeboard
        self.state.trigger_delay[board] = value
        self.controller.send_trigger_delay(board)
        self.update_trigger_spinbox_tooltip(self.ui.trigger_delay_box, "Time to wait before actually firing trigger")

        # Update trigger info text if it's enabled (includes trigger time)
        if self.plot_manager.cursor_manager:
            self.plot_manager.cursor_manager.update_trigger_threshold_text()

    def trigger_holdoff_changed(self, value):
        """Handle changes to trigger holdoff spinbox."""
        board = self.state.activeboard
        self.state.trigger_holdoff[board] = value
        self.controller.send_trigger_delay(board)
        self.update_trigger_spinbox_tooltip(self.ui.trigger_holdoff_box, "Time needed failing threshold before passing threshold")

    def update_trigger_spinbox_tooltip(self, spinbox, base_text):
        """Update tooltip for trigger-related spinboxes to show time duration.

        Args:
            spinbox: The QSpinBox widget to update
            base_text: The base tooltip text
        """
        if self.state.num_board < 1:
            return

        value = spinbox.value()
        if value == 0:
            spinbox.setToolTip(base_text)
            return

        # Calculate time in nanoseconds: value * downsamplefactor * 40 / samplerate
        time_ns = value * self.state.downsamplefactor * 40.0 / self.state.samplerate

        # Format with appropriate units
        from data_processor import format_period
        time_val, unit = format_period(time_ns, "s", False)

        # Update tooltip
        tooltip = f"{time_val:.2f} {unit}: {base_text}"
        spinbox.setToolTip(tooltip)

    def lpf_changed(self):
        thetext = self.ui.lpfBox.currentText()
        self.state.lpf[self.state.activexychannel] = 0 if thetext == "Off" else int(thetext.split()[0]) # remove MHz

    def single_clicked(self):
        self.state.getone = not self.state.getone
        self.ui.singleButton.setChecked(self.state.getone)

    def rolling_clicked(self):
        """Toggles rolling mode and updates the button's text and checked state."""
        # Toggle the state
        self.state.isrolling = not self.state.isrolling

        # Send the command to the hardware
        self.controller.set_rolling(self.state.isrolling)

        # Explicitly update the button's appearance
        if self.state.isrolling:
            self.ui.rollingButton.setText("Auto")
            self.ui.rollingButton.setChecked(True)
        else:
            self.ui.rollingButton.setText("Normal")
            self.ui.rollingButton.setChecked(False)

    def drawing_toggled(self, checked):
        self.state.dodrawing = checked

    def auxout_changed(self, index):
        board = self.state.activeboard
        self.state.auxoutval[board] = index
        self.controller.set_auxout(board, index)
