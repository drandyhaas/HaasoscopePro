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
from history_window import HistoryWindow
from measurements_manager import MeasurementsManager
from calibration import autocalibration, do_meanrms_calibration
from settings_manager import save_setup, load_setup
from math_channels_window import MathChannelsWindow
from reference_manager import save_reference_lines, load_reference_lines
from dummy_server_config_dialog import DummyServerConfigDialog

# Import remaining dependencies
from FFTWindow import FFTWindow
from SCPIsocket import DataSocket
from board import setupboard
from utils import get_pwd
import ftd2xx

pwd = get_pwd()
print(f"Current dir is {pwd}")


WindowTemplate, TemplateBaseClass = loadUiType(pwd + "/HaasoscopePro.ui")
class MainWindow(TemplateBaseClass):
    def __init__(self, usbs):
        super().__init__()

        # Store usbs for later use
        self.usbs = usbs

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
        self.dummy_server_config_dialog = None
        # Initialize boardBox ComboBox with board numbers
        self.ui.boardBox.blockSignals(True)
        self.ui.boardBox.setMaxVisibleItems(self.state.num_board)
        self.ui.boardBox.clear()
        for i in range(self.state.num_board):
            self.ui.boardBox.addItem(str(i))
        self.ui.boardBox.blockSignals(False)
        self.setup_successful = False
        self.reference_data = {}  # Stores {channel_index: {'x_ns': array, 'y': array}}
        self.math_reference_data = {}  # Stores {math_channel_name: {'x_ns': array, 'y': array}}

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
        self.ui.tableView.setColumnWidth(0, 215)  # Measurement name column, wider for X button + name
        self.ui.tableView.setColumnWidth(1, 50)  # Measurement value column
        self.ui.tableView.setColumnWidth(2, 50)  # Measurement avg column
        self.ui.tableView.setColumnWidth(3, 50)  # Measurement rms column

        # Show main window
        self.show()

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

        # Processing and Display controls
        self.ui.actionDrawing.triggered.connect(self.drawing_toggled)
        self.ui.actionGrid.triggered.connect(lambda checked: self.plot_manager.set_grid(checked))
        self.ui.actionMarkers.triggered.connect(lambda checked: self.plot_manager.set_markers(checked))
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
        self.ui.actionConfigure_dummy_scope.triggered.connect(self.open_dummy_server_config)
        if self._is_connected_to_dummy_server():
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
        self.ui.actionMath_channels.triggered.connect(self.open_math_channels)
        self.ui.actionHistory_window.triggered.connect(self.open_history_window)

        # Plot manager signals
        self.plot_manager.curve_clicked_signal.connect(self.on_curve_clicked)

        # Connect the controller's error signal to our handler slot
        self.controller.signals.critical_error_occurred.connect(self.handle_critical_error)

    def _update_channel_mode_ui(self):
        """
        A centralized function to synchronize all UI elements related to the
        channel mode (Single, Two Channel, Oversampling).
        """
        # If in XY mode, do not alter the visibility of any time-domain plots.
        if self.state.xy_mode:
            return

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
            if s.dotwochannel[board_idx]:
                # In two-channel mode, ch1 should be enabled
                s.channel_enabled[ch1_idx] = True
            else:
                # In single-channel mode, ch1 should be disabled
                s.channel_enabled[ch1_idx] = False
                self.plot_manager.lines[ch1_idx].clear()

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

        # --- Plotting Logic: Switch between Time Domain and XY Mode ---
        if s.xy_mode:
            # For XY mode, we need to ensure the data lengths match.
            # We'll use the data from the first two channels of the active board.
            board = s.activeboard
            # Ensure channel 1 is enabled for two-channel mode to get data
            if s.dotwochannel[board]:
                ch0_index = board * s.num_chan_per_board
                ch1_index = ch0_index + 1
                # In two-channel mode, only the first half of the buffer is valid data
                num_valid_samples = self.xydata.shape[2] // 2
                y_data_ch0 = self.xydata[ch0_index][1][:num_valid_samples]
                x_data_ch1 = self.xydata[ch1_index][1][:num_valid_samples]
                self.plot_manager.update_xy_plot(x_data=x_data_ch1, y_data=y_data_ch0)
        else:
            self.plot_manager.update_plots(self.xydata, self.xydatainterleaved)

        # Calculate and display math channels if any are defined
        if self.math_window and len(self.math_window.math_channels) > 0:
            # Use stabilized data (after trigger stabilizers are applied)
            math_results = self.math_window.calculate_math_channels(self.plot_manager.stabilized_data)
            self.plot_manager.update_math_channel_data(math_results)

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

                    y_full = self.xydata[ch_idx][1]
                    midpoint = len(y_full) // 2
                    if s.dotwochannel[board_idx]:
                        y_data_for_analysis = y_full[:midpoint]
                    elif s.dointerleaved[board_idx]:
                        y_data_for_analysis = self.xydatainterleaved[ch_idx][1]
                    else:
                        y_data_for_analysis = y_full

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
                                # Calculate FFT using the active board's sample rate
                                freq, mag = self.processor.calculate_fft(y_data, s.activeboard)

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
        status_text = (f"{format_freq(effective_sr, 'S/s')}, {self.fps:.2f} fps, "
                       f"{s.nevents} events, {s.lastrate:.2f} Hz, "
                       f"{(s.lastrate * s.lastsize / 1e6):.2f} MB/s")
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

        if time_per_div * s.nsunits < 1:
            display_text = f"{1000*time_per_div:.1f} ps"
        elif time_per_div < 10:
            display_text = f"{time_per_div:.2f} {s.units}"
        else:
            display_text = f"{time_per_div:.1f} {s.units}"
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

        # --- Update reference waveforms with new scaling and per-channel visibility ---
        for i in range(self.plot_manager.nlines):
            # Check if this specific channel has a reference and it's set to visible
            has_reference = i in self.reference_data
            is_visible = self.reference_visible.get(i, False)

            if has_reference and is_visible:
                # This channel has a reference and it should be visible
                data = self.reference_data[i]
                x_display = data['x_ns'] / s.nsunits
                self.plot_manager.update_reference_plot(i, x_display, data['y'])
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
            else:
                self.ui.offsetBox.stepUp()
        if event.key() == QtCore.Qt.Key_Down:
            if modifiers & QtCore.Qt.ShiftModifier:
                self.ui.gainBox.setValue(self.ui.gainBox.value() - 1)
            else:
                self.ui.offsetBox.stepDown()
        if event.key() == QtCore.Qt.Key_Left: self.time_slow()
        if event.key() == QtCore.Qt.Key_Right: self.time_fast()

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

        # Update XY menu item based on whether the active board is in two-channel mode
        self.ui.actionXY_Plot.setEnabled(self.state.dotwochannel[self.state.activeboard])

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

        # If we are in XY mode but switched to a board that is not in two-channel mode, exit XY mode
        if self.state.xy_mode and not self.state.dotwochannel[self.state.activeboard]:
            self.ui.actionXY_Plot.setChecked(False)
            self.plot_manager.toggle_xy_view(False, self.state.activeboard)

        # If in XY mode, update the pen color to match the new active board's CH1
        if self.state.xy_mode:
            ch0_index = self.state.activeboard * self.state.num_chan_per_board + 0
            new_pen = self.plot_manager.linepens[ch0_index]
            self.plot_manager.set_xy_pen(new_pen)

        # Reset FFT analysis when channel changes
        if self.fftui:
            self.fftui.reset_analysis_state()

        # Update Show Reference menu checkbox to reflect active channel's reference visibility
        self.update_reference_checkbox_state()

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

        else:  # Normal trigger adjust mode
            s.triggerpos = int(s.expect_samples * value / 10000.)
            self.controller.send_trigger_info_all()
            self.plot_manager.draw_trigger_lines()

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
        self.state.doresamp = value
        if True: #self.state.downsample < 0:
            self.state.saved_doresamp = value

    def line_width_changed(self, value):
        """Handle line width changes from the UI."""
        self.state.line_width = value
        self.plot_manager.set_line_width(value)

    def trigger_level_changed(self, value):
        self.state.triggerlevel = value
        self.controller.send_trigger_info_all()
        self.plot_manager.draw_trigger_lines()

    def time_fast(self):
        if self.state.downsample < -10:
            #print("Maximum zoom level reached.")
            self.ui.timefastButton.setEnabled(False)

        old_downsample = self.state.downsample
        self.state.downsample -= 1
        highres = 1 if self.ui.actionHigh_resolution.isChecked() else 0
        self.controller.tell_downsample_all(self.state.downsample, highres)

        # When transitioning from downsample=0 to downsample=-1, restore saved resamp value
        if old_downsample == 0 and self.state.downsample == -1:
            self.state.doresamp = self.state.saved_doresamp
            self.ui.resampBox.blockSignals(True)
            self.ui.resampBox.setValue(self.state.doresamp)
            self.ui.resampBox.blockSignals(False)

        is_zoomed = self.state.downsample < 0
        if is_zoomed:
            self.state.downsamplezoom = pow(2, -self.state.downsample)
        else:
            self.state.downsamplezoom = 1

        # Update the plot range and text box
        self.time_changed()

        # Clear peak detect data when timebase changes
        if self.plot_manager.peak_detect_enabled:
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
        self.state.downsample += 1
        highres = 1 if self.ui.actionHigh_resolution.isChecked() else 0
        self.controller.tell_downsample_all(self.state.downsample, highres)

        # When transitioning from downsample=-1 to downsample=0, save and turn off resamp
        if old_downsample == -1 and self.state.downsample == 0:
            self.state.saved_doresamp = self.state.doresamp
            self.state.doresamp = 0
            self.ui.resampBox.blockSignals(True)
            self.ui.resampBox.setValue(0)
            self.ui.resampBox.blockSignals(False)

        is_zoomed = self.state.downsample < 0

        if is_zoomed:
            self.state.downsamplezoom = pow(2, -self.state.downsample)
        else:
            self.state.downsamplezoom = 1

        # Update the plot range and text box
        self.time_changed()

        # Clear peak detect data when timebase changes
        if self.plot_manager.peak_detect_enabled:
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
        self.trigger_pos_changed(self.ui.thresholdPos.value())
        self.time_changed()

    def change_channel_color(self):
        options = QColorDialog.ColorDialogOptions()
        if sys.platform.startswith('linux'):
            options |= QColorDialog.DontUseNativeDialog
        color = QColorDialog.getColor(self.plot_manager.linepens[self.state.activexychannel].color(), self, options=options)
        if color.isValid():
            self.plot_manager.linepens[self.state.activexychannel].setColor(color)
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

        # Unblock signals
        self.ui.persistTbox.blockSignals(False)
        self.ui.persistlinesCheck.blockSignals(False)
        self.ui.persistAvgCheck.blockSignals(False)

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

    def update_channel_visibility(self, channel_index):
        """Update visibility for a specific channel based on its state."""
        s = self.state

        # Get channel settings
        is_chan_on = s.channel_enabled[channel_index]
        show_persist_lines = s.persist_lines_enabled[channel_index]
        show_persist_avg = s.persist_avg_enabled[channel_index]
        persist_time = s.persist_time[channel_index]

        # Get the line objects
        main_line = self.plot_manager.lines[channel_index]
        average_line = self.plot_manager.average_lines.get(channel_index)

        # If channel is not enabled, hide everything
        if not is_chan_on:
            main_line.setVisible(False)
            if average_line:
                average_line.setVisible(False)
            if channel_index in self.plot_manager.persist_lines_per_channel:
                for item, _, _ in self.plot_manager.persist_lines_per_channel[channel_index]:
                    item.setVisible(False)
            return

        # Channel is enabled - apply visibility rules

        # Average line visibility
        if average_line:
            average_line.setVisible(show_persist_avg)

        # Persist lines visibility
        if channel_index in self.plot_manager.persist_lines_per_channel:
            for item, _, _ in self.plot_manager.persist_lines_per_channel[channel_index]:
                item.setVisible(show_persist_lines)

        # Main trace visibility: hide ONLY if average is on AND persist lines are off AND persist time > 0
        if show_persist_avg and not show_persist_lines and persist_time > 0:
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
        s.channel_enabled[active_channel] = self.ui.chanonCheck.isChecked()

        # Update the pen style/color of the average line
        self.plot_manager.set_average_line_pen()

        # Update visibility for the active channel
        self.update_channel_visibility(active_channel)

    # #########################################################################
    # ## Slot Implementations (Callbacks for UI events)
    # #########################################################################

    def toggle_xy_view_slot(self, checked):
        """Slot for the 'XY Plot' menu action."""
        board = self.state.activeboard
        if checked:
            ch0_index = board * self.state.num_chan_per_board
            pen = self.plot_manager.linepens[ch0_index]
            self.plot_manager.set_xy_pen(pen)
        self.plot_manager.toggle_xy_view(checked, board)

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

        # Calculate and display current data if we have data
        if hasattr(self, 'xydata') and len(self.math_window.math_channels) > 0:
            # Use stabilized data (after trigger stabilizers are applied)
            math_results = self.math_window.calculate_math_channels(self.plot_manager.stabilized_data)
            self.plot_manager.update_math_channel_data(math_results)

    def _is_connected_to_dummy_server(self):
        """Check if any USB device is connected to a dummy server (socket)."""
        for usb in self.usbs:
            if hasattr(usb, 'socket_addr'):  # UsbSocketAdapter has socket_addr
                #print(f"  -> Connected to dummy server at: {usb.socket_addr}")
                return True
        return False

    def open_dummy_server_config(self):
        """Open or bring to front the dummy server configuration dialog."""
        if self.dummy_server_config_dialog is None:
            self.dummy_server_config_dialog = DummyServerConfigDialog(self, self.usbs)
            self.dummy_server_config_dialog.show()
        else:
            # Dialog exists - just bring it to front
            self.dummy_server_config_dialog.raise_()
            self.dummy_server_config_dialog.activateWindow()

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
            if self.state.xy_mode:
                board = self.state.activeboard
                if self.state.dotwochannel[board]:
                    ch0_index = board * self.state.num_chan_per_board
                    ch1_index = ch0_index + 1
                    num_valid_samples = self.xydata.shape[2] // 2
                    y_data_ch0 = self.xydata[ch0_index][1][:num_valid_samples]
                    x_data_ch1 = self.xydata[ch1_index][1][:num_valid_samples]
                    self.plot_manager.update_xy_plot(x_data=x_data_ch1, y_data=y_data_ch0)
            else:
                self.plot_manager.update_plots(self.xydata, self.xydatainterleaved)

            # Update math channels if any
            if self.math_window and len(self.math_window.math_channels) > 0:
                math_results = self.math_window.calculate_math_channels(self.plot_manager.stabilized_data)
                self.plot_manager.update_math_channel_data(math_results)

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
        """
        s = self.state
        active_channel = s.activexychannel
        line = self.plot_manager.lines[active_channel]

        if line.xData is not None and line.yData is not None:
            # Convert the current x-axis data (which is in units of s.units)
            # back to a canonical form (nanoseconds) for storage.
            x_data_in_ns = line.xData * s.nsunits
            y_data = np.copy(line.yData)  # Make a copy

            self.reference_data[active_channel] = {'x_ns': x_data_in_ns, 'y': y_data}

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

    def update_reference_checkbox_state(self):
        """Updates the 'Show Reference' checkbox to reflect the active channel's reference visibility."""
        s = self.state
        active_channel = s.activexychannel

        # Check if this channel has a reference and if it's visible
        is_visible = self.reference_visible.get(active_channel, False)

        self.ui.actionShow_Reference.blockSignals(True)
        self.ui.actionShow_Reference.setChecked(is_visible)
        self.ui.actionShow_Reference.blockSignals(False)

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

        # If we are in XY mode and two-channel is turned off, exit XY mode
        if s.xy_mode and not is_two_channel:
            self.ui.actionXY_Plot.setChecked(False)
            self.plot_manager.toggle_xy_view(False, s.activeboard)
        
        # The next event after a mode switch can be glitchy, so we'll skip it.
        s.skip_next_event = True

        # Store the old state before updating
        old_two_channel_state = s.dotwochannel[active_board]

        # 1. Update the state for the active board ONLY
        s.dotwochannel[active_board] = is_two_channel

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

        # 4. Set a grace period to prevent false PLL resets during the switch
        s.pll_reset_grace_period = 5

        # 5. Update the rest of the application
        self.allocate_xy_data()
        self.time_changed()
        self._update_channel_mode_ui()
        self.select_channel()

        # 6. Update math window channel lists (availability of Ch 1 changed)
        if self.math_window:
            self.math_window.update_channel_list()

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

        # Update autocalibration enabled state based on oversampling change
        self.update_autocalibration_enabled()

        self.gain_changed()
        self.offset_changed()
        all_colors = [pen.color() for pen in self.plot_manager.linepens]
        self.controller.do_leds(all_colors)

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
        self.update_channel_visibility(c_secondary_ch0)
        self.update_channel_visibility(c_secondary_ch1)

        self.time_changed()
        all_colors = [pen.color() for pen in self.plot_manager.linepens]
        self.controller.do_leds(all_colors)

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
