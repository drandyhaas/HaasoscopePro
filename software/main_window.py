# main_window.py

import sys, time, math, warnings
import numpy as np
import threading
from scipy.signal import resample
from pyqtgraph.Qt import QtCore, QtWidgets, loadUiType
from PyQt5.QtWidgets import QMessageBox, QColorDialog, QFrame, QAction
from PyQt5.QtGui import QPalette, QIcon

# Import all the refactored components
from scope_state import ScopeState
from hardware_controller import HardwareController
from data_processor import DataProcessor, format_freq
from plot_manager import PlotManager
from data_recorder import DataRecorder

# Import remaining dependencies
from FFTWindow import FFTWindow
from SCPIsocket import DataSocket
from board import setupboard, gettemps
from utils import get_pwd
import ftd2xx

pwd = get_pwd()
print(f"Current dir is {pwd}")
WindowTemplate, TemplateBaseClass = loadUiType(pwd + "/HaasoscopePro.ui")
class MainWindow(TemplateBaseClass):
    def __init__(self, usbs):
        super().__init__()

        # 1. Initialize core components
        self.state = ScopeState(num_boards=len(usbs), num_chan_per_board=2)
        self.controller = HardwareController(usbs, self.state)
        self.processor = DataProcessor(self.state)
        self.recorder = DataRecorder(self.state)

        self.reference_data = {} # Stores {channel_index: {'x_ns': array, 'y': array}}

        # 2. Setup UI from template
        self.ui = WindowTemplate()
        self.ui.setupUi(self)
        self._create_menus() # Create the new Reference menu

        # 3. Initialize UI/Plot manager
        self.plot_manager = PlotManager(self.ui, self.state)
        self.plot_manager.setup_plots()

        # 4. Connect all signals from UI widgets to slots in this class
        self._connect_signals()

        # 5. Initialize network socket and other components
        self.socket = None
        self.socket_thread = None
        self.fftui = None
        self.ui.boardBox.setMaximum(self.state.num_board - 1)
        self.setup_successful = False

        # 6. Setup timers for data acquisition and measurement updates
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plot_loop)
        self.timer2 = QtCore.QTimer()
        self.timer2.timeout.connect(self.update_measurements_display)

        # 7. Run the main initialization and hardware setup sequence
        if self.state.num_board > 0:
            if self.controller.setup_all_boards():
                self.controller.send_trigger_info_all()
                self.ui.ToffBox.setValue(self.state.toff)
                self.allocate_xy_data()
                self.controller.set_rolling(self.state.isrolling)
                self.select_channel()  # Updates UI and LEDs
                self.time_changed()
                self.open_socket()

                if self.state.num_board < 2:
                    self.ui.ToffBox.setEnabled(False)
                    self.ui.tadBox.setEnabled(False)

                self.dostartstop()  # Start acquisition
                self.setup_successful = True
            else:
                self.ui.runButton.setEnabled(False)

        else:  # Handle the case where no boards were found
            print("WARNING: No Haasoscope Pro boards found. Running in offline mode.")
            self.ui.runButton.setEnabled(False)
            self.ui.statusBar.showMessage("No hardware detected. Connect a device and restart.")
            self.setup_successful = False
            # Use a QTimer to show the message after the main window is fully loaded
            QtCore.QTimer.singleShot(100, self.show_no_hardware_error)

        self.last_time = time.time()
        self.fps = None

        # DEFER UI sync until after the constructor is finished and the event loop starts
        QtCore.QTimer.singleShot(10, self._sync_initial_ui_state)

        self.show()

    def _create_menus(self):
        """Create and add the new 'Reference' menu to the menu bar."""
        self.reference_menu = self.ui.menubar.addMenu('Reference')

        self.ui.actionTake_Reference = QAction('Take Reference from Active Channel', self)
        self.reference_menu.addAction(self.ui.actionTake_Reference)

        self.ui.actionShow_Reference = QAction('Show Reference(s)', self, checkable=True)
        self.ui.actionShow_Reference.setChecked(True)
        self.reference_menu.addAction(self.ui.actionShow_Reference)

    def _sync_initial_ui_state(self):
        """A one-time function to sync the UI's visual state after the window has loaded."""
        # This function is called just after the main event loop starts.
        self.ui.rollingButton.setChecked(bool(self.state.isrolling))
        self.ui.rollingButton.setText(" Auto " if self.state.isrolling else " Normal ")
        self.ui.runButton.setText(" Run ")
        self.ui.actionPan_and_zoom.setChecked(False)
        self.plot_manager.set_pan_and_zoom(False)

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

    def show_no_hardware_error(self):
        """Displays a non-blocking warning message to the user."""
        QMessageBox.warning(self, "Hardware Not Found",
                            "No Haasoscope Pro boards were detected.\n\n"
                            "The application is running in a disconnected state. "
                            "Please connect a device and restart the program to continue.")

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
        self.ui.thresholdDelta.valueChanged.connect(self.trigger_delta_changed)
        self.ui.thresholdPos.valueChanged.connect(self.trigger_pos_changed)
        self.ui.trigchan_comboBox.currentIndexChanged.connect(self.trigger_chan_changed)
        self.ui.risingfalling_comboBox.currentIndexChanged.connect(self.rising_falling_changed)
        self.ui.totBox.valueChanged.connect(self.tot_changed)
        self.ui.exttrigCheck.stateChanged.connect(self.exttrig_changed)
        self.ui.extsmatrigCheck.stateChanged.connect(self.extsmatrig_changed)

        # Channel controls
        self.ui.boardBox.valueChanged.connect(self.select_channel)
        self.ui.chanBox.valueChanged.connect(self.select_channel)
        self.ui.chanonCheck.stateChanged.connect(self.chanon_changed)
        self.ui.gainBox.valueChanged.connect(self.gain_changed)
        self.ui.offsetBox.valueChanged.connect(self.offset_changed)
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
        self.ui.markerCheck.stateChanged.connect(lambda checked: self.plot_manager.set_markers(checked))
        self.ui.actionPan_and_zoom.triggered.connect(lambda checked: self.plot_manager.set_pan_and_zoom(checked))
        self.ui.rightaxisCheck.clicked.connect(lambda checked: self.plot_manager.right_axis.setVisible(checked))
        self.ui.linewidthBox.valueChanged.connect(self.plot_manager.set_line_width)
        self.ui.lpfBox.currentIndexChanged.connect(self.lpf_changed)
        self.ui.resampBox.valueChanged.connect(lambda val: setattr(self.state, 'doresamp', val))
        self.ui.fwfBox.valueChanged.connect(lambda val: setattr(self.state, 'fitwidthfraction', val / 100.))
        self.ui.fftCheck.stateChanged.connect(self.fft_clicked)
        self.ui.persistTbox.valueChanged.connect(self.plot_manager.set_persistence)
        self.ui.persistavgCheck.clicked.connect(self.set_average_line_pen)
        self.ui.persistlinesCheck.clicked.connect(self.set_average_line_pen)
        self.ui.actionLine_color.triggered.connect(self.change_channel_color)
        self.ui.actionHigh_resolution.triggered.connect(self.high_resolution_toggled)

        # Advanced/Hardware controls
        self.ui.pllresetButton.clicked.connect(lambda: self.controller.pllreset(self.state.activeboard))
        self.ui.tadBox.valueChanged.connect(self.tad_changed)
        self.ui.ToffBox.valueChanged.connect(lambda val: setattr(self.state, 'toff', val))
        self.ui.Auxout_comboBox.currentIndexChanged.connect(self.auxout_changed)
        self.ui.actionToggle_PLL_controls.triggered.connect(self.toggle_pll_controls)
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

        # Menu actions
        self.ui.actionAbout.triggered.connect(self.about_dialog)
        self.ui.actionTake_screenshot.triggered.connect(self.take_screenshot)
        self.ui.actionRecord.triggered.connect(self.toggle_recording)
        self.ui.actionVerify_firmware.triggered.connect(self.verify_firmware)
        self.ui.actionUpdate_firmware.triggered.connect(self.update_firmware)
        self.ui.actionDo_autocalibration.triggered.connect(self.autocalibration)
        self.ui.actionOversampling_mean_and_RMS.triggered.connect(self.do_meanrms_calibration)
        self.ui.actionToggle_trig_stabilizer.triggered.connect(self.trig_stabilizer_toggled)
        self.ui.actionToggle_extra_trig_stabilizer.triggered.connect(self.extra_trig_stabilizer_toggled)

        # Plot manager signals
        self.plot_manager.vline_dragged_signal.connect(self.on_vline_dragged)
        self.plot_manager.hline_dragged_signal.connect(self.on_hline_dragged)
        self.plot_manager.curve_clicked_signal.connect(self.on_curve_clicked)

        # Reference menu actions
        self.ui.actionTake_Reference.triggered.connect(self.take_reference_waveform)
        self.ui.actionShow_Reference.triggered.connect(self.toggle_reference_waveform_visibility)

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
        self.ui.oversampCheck.setChecked(is_pair_oversampling)

        # 2. Determine the ENABLED state of the oversampling box.
        #    The user should only be able to CHANGE the oversampling setting
        #    when the primary (even) board of a pair is selected.
        can_change_oversampling = (s.num_board > 1 and s.activeboard % 2 == 0 and not s.dotwochannel[s.activeboard])
        self.ui.oversampCheck.setEnabled(can_change_oversampling)

        # Get the model item for "Channel 1" (which is at index 1)
        chan1_item = self.ui.trigchan_comboBox.model().item(1)
        if chan1_item:
            # Only enable the "Channel 1" option if two-channel mode is active
            chan1_item.setEnabled(s.dotwochannel[s.activeboard])

        # If not in two-channel mode, ensure "Channel 0" is selected
        if not s.dotwochannel[s.activeboard] and self.ui.trigchan_comboBox.currentIndex() == 1:
            self.ui.trigchan_comboBox.setCurrentIndex(0)

        # Existing logic for chanBox
        if s.dotwochannel[s.activeboard]:
            self.ui.chanBox.setMaximum(s.num_chan_per_board - 1)
        else:
            if self.ui.chanBox.value() != 0:
                self.ui.chanBox.setValue(0)
            self.ui.chanBox.setMaximum(0)

        # Loop through all boards to set plot line visibility
        for board_idx in range(s.num_board):
            # The index of the second channel on this board
            ch1_idx = board_idx * s.num_chan_per_board + 1

            # Determine if the second channel should be visible
            is_ch1_visible = s.dotwochannel[board_idx]

            self.plot_manager.lines[ch1_idx].setVisible(is_ch1_visible)

            # If hiding the channel, also clear its data to remove the stale trace
            if not is_ch1_visible:
                self.plot_manager.lines[ch1_idx].clear()

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

    def _sync_depth_ui_from_state(self):
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
        if self.socket and self.socket.issending:
            time.sleep(0.001)
            return

        self.state.isdrawing = True
        try:
            raw_data_map, rx_len = self.controller.get_event()
        except ftd2xx.DeviceError as e:
            # If a hardware communication error occurs, handle it gracefully.
            title = "Hardware Communication Error"
            message = (f"Lost communication with the device.\n\n"
                       f"Details: {e}\n\n"
                       "Please check the USB connection and restart the application.")
            self.handle_critical_error(title, message)
            # Stop this loop immediately since communication has failed.
            return
        if not raw_data_map:
            self.state.isdrawing = False
            return

        s = self.state
        s.nevents += 1
        s.lastsize = rx_len

        if s.nevents - s.oldnevents >= s.tinterval:
            now = time.time()
            elapsedtime = now - s.oldtime
            s.oldtime = now
            if elapsedtime > 0:
                s.lastrate = round(s.tinterval / elapsedtime, 2)
            s.oldnevents = s.nevents

        self.allocate_xy_data()

        for board_idx, raw_data in raw_data_map.items():
            nbadA, nbadB, nbadC, nbadD, nbadS = self.processor.process_board_data(raw_data, board_idx, self.xydata)
            if s.plljustreset[board_idx] > -10:
                # If a reset is already in progress, continue it.
                self.controller.adjustclocks(board_idx, nbadA, nbadB, nbadC, nbadD, nbadS)
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

        self.plot_manager.update_plots(self.xydata, self.xydatainterleaved)

        if self.recorder.is_recording:
            lines_vis = [line.isVisible() for line in self.plot_manager.lines]
            self.recorder.record_event(self.xydata, self.plot_manager.otherlines['vline'].value(), lines_vis)

        # --- START: Multi-channel FFT processing ---
        if self.fftui and self.fftui.isVisible():
            active_channel_name = f"CH{self.state.activexychannel + 1}"

            # Loop through all possible channels
            for ch_idx in range(self.state.num_board * self.state.num_chan_per_board):
                ch_name = f"CH{ch_idx + 1}"
                board_idx = ch_idx // self.state.num_chan_per_board

                # Update FFT if this channel is enabled
                if self.state.fft_enabled.get(ch_name, False):
                    is_active = (ch_name == active_channel_name)

                    y_full = self.xydata[ch_idx][1]
                    midpoint = len(y_full) // 2
                    if s.dotwochannel[board_idx]: y_data_for_analysis = y_full[:midpoint]
                    elif s.dointerleaved[board_idx]:
                        y_data_for_analysis = self.xydatainterleaved[ch_idx][1]
                    else: y_data_for_analysis = y_full

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
        # --- END: Multi-channel FFT processing ---

        now = time.time()
        dt = now - self.last_time + 1e-9
        self.last_time = now
        self.fps = 1.0 / dt if self.fps is None else self.fps * 0.9 + (1.0 / dt) * 0.1

        sradjust = 1e9
        if s.dointerleaved[s.activeboard]:
            sradjust = 2e9
        elif s.dotwochannel[s.activeboard]:
            sradjust = 0.5e9
        effective_sr = s.samplerate * sradjust / (s.downsamplefactor if not s.highresval else 1)

        status_text = (f"{format_freq(effective_sr, 'S/s')}, {self.fps:.2f} fps, "
                       f"{s.nevents} events, {s.lastrate:.2f} Hz, "
                       f"{(s.lastrate * s.lastsize / 1e6):.2f} MB/s")
        self.ui.statusBar.showMessage(status_text)
        self.state.isdrawing = False

        # Sync the Depth box UI with the state, in case it was changed by a PLL reset
        self._sync_depth_ui_from_state()

        # If 'getone' (Single) mode is active, call dostartstop() immediately
        # after successfully processing one event. This will pause the acquisition.
        if self.state.getone:
            self.dostartstop()

    def update_measurements_display(self):
        """Slow timer callback to update text-based measurements."""
        the_str = ""
        if self.recorder.is_recording:
            the_str += f"Recording to file {self.recorder.file_handle.name}\n"

        if self.state.dodrawing:

            if self.ui.actionTrigger_thresh.isChecked():
                # Get the threshold value directly from the plot manager's line object
                hline_val = self.plot_manager.otherlines['hline'].value()
                the_str += f"Trigger threshold: {hline_val:.3f} div\n"

            if self.ui.actionN_persist_lines.isChecked():
                # Get the number of lines from the plot manager's persistence deque
                num_persist = len(self.plot_manager.persist_lines)
                the_str += f"N persist lines: {num_persist}\n"

            if self.ui.actionTemperatures.isChecked():
                if self.state.num_board > 0:
                    # Get the usb device for the currently active board from the controller
                    active_usb = self.controller.usbs[self.state.activeboard]
                    # The gettemps function is expected to return a pre-formatted string
                    the_str += gettemps(active_usb) + "\n"

            source_str, fit_results = "", None
            if self.ui.persistavgCheck.isChecked() and self.plot_manager.average_line.isVisible():
                target_x = self.plot_manager.average_line.xData
                target_y = self.plot_manager.average_line.yData
                source_str = "from average"
            elif hasattr(self, 'xydata'):
                x_full = self.xydata[self.state.activexychannel][0]
                y_full = self.xydata[self.state.activexychannel][1]
                midpoint = len(y_full) // 2
                if self.state.dotwochannel[self.state.activeboard]:
                    x_data_for_analysis = x_full[:midpoint]
                    y_data_for_analysis = y_full[:midpoint]
                else:
                    x_data_for_analysis = x_full
                    y_data_for_analysis = y_full

                the_str += f"\nMeasurements {source_str} for board {self.state.activeboard} ch {self.state.selectedchannel}:\n"
                vline_val = self.plot_manager.otherlines['vline'].value()
                measurements, fit_results = self.processor.calculate_measurements(
                    x_data_for_analysis, y_data_for_analysis, vline_val, do_risetime_calc=self.ui.actionRisetime.isChecked()
                )

                # Update the text browser
                if self.ui.actionMean.isChecked(): the_str += f"Mean: {measurements.get('Mean', 'N/A')}\n"
                if self.ui.actionRMS.isChecked(): the_str += f"RMS: {measurements.get('RMS', 'N/A')}\n"
                if self.ui.actionVpp.isChecked(): the_str += f"Vpp: {measurements.get('Vpp', 'N/A')}\n"
                if self.ui.actionFreq.isChecked(): the_str += f"Freq: {measurements.get('Freq', 'N/A')}\n"
                if self.ui.actionRisetime.isChecked(): the_str += f"Risetime: {measurements.get('Risetime', 'N/A')}\n"

            self.ui.textBrowser.setText(the_str)

            # Tell the plot manager to update the fit lines with the latest results
            self.plot_manager.update_risetime_fit_lines(fit_results)

    def allocate_xy_data(self):
        """Creates or re-sizes the numpy arrays for storing waveform data."""
        s = self.state
        num_ch = s.num_chan_per_board * s.num_board

        # ALWAYS allocate for the maximum number of samples (single-channel mode).
        # The DataProcessor will handle filling it correctly for each board's mode.
        num_samples = 4 * 10 * s.expect_samples
        shape = (num_ch, 2, num_samples)

        ishape = (num_ch, 2, 2 * num_samples)  # For interleaved data

        # Avoid re-allocating if the shape hasn't changed
        if not hasattr(self, 'xydata') or self.xydata.shape != shape:
            self.xydata = np.zeros(shape, dtype=float)
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
        if time_per_div < 10:
            display_text = f"{time_per_div:.2f} {s.units}/div"
        else:
            display_text = f"{time_per_div:.1f} {s.units}/div"
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

        # --- Update reference waveforms with new scaling and visibility ---
        show_refs_is_checked = self.ui.actionShow_Reference.isChecked()
        for i in range(self.plot_manager.nlines):
            if i in self.reference_data and show_refs_is_checked:
                # This channel has a reference and it should be visible
                data = self.reference_data[i]
                x_display = data['x_ns'] / s.nsunits
                self.plot_manager.update_reference_plot(i, x_display, data['y'])
            else:
                # This channel either has no reference or refs are turned off
                self.plot_manager.hide_reference_plot(i)

    def handle_critical_error(self, title, message):
        """
        This slot is called when the hardware controller signals an unrecoverable error.
        It stops the acquisition and displays an error message to the user.
        """
        # 1. Stop the acquisition timer if it's running
        if not self.state.paused:
            self.dostartstop()

        # 2. Disable the run button to prevent the user from restarting
        self.ui.runButton.setEnabled(False)

        # 3. Show the critical error message box
        QMessageBox.critical(self, title, message)

    def closeEvent(self, event):
        print("Closing application...")
        self.timer.stop()
        self.timer2.stop()
        self.recorder.stop()
        self.close_socket()
        self.controller.cleanup()
        if self.fftui: self.fftui.close()
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
        self.ui.boardBox.setValue(board)
        self.ui.chanBox.setValue(channel)
        # select_channel is called automatically by the valueChanged signal

    def toggle_pll_controls(self):
        """Shows or hides the manual PLL adjustment buttons."""
        is_enabled = self.ui.pllBox.isEnabled()
        self.ui.pllBox.setEnabled(not is_enabled)
        for i in range(5):
            getattr(self.ui, f"upposButton{i}").setEnabled(not is_enabled)
            getattr(self.ui, f"downposButton{i}").setEnabled(not is_enabled)

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
            self.timer.start(0)  # 0ms interval for fastest refresh
            self.timer2.start(1000)  # 1s interval for measurements
            self.state.paused = False
            self.ui.runButton.setChecked(True)
        else:
            self.timer.stop()
            self.timer2.stop()
            self.state.paused = True
            self.ui.runButton.setChecked(False)

    def high_resolution_toggled(self, checked):
        """Toggles the hardware's high-resolution averaging mode."""
        self.state.highresval = 1 if checked else 0

        # The downsample command also sends the high-resolution setting,
        # so we just need to re-send it to the hardware for all boards.
        self.controller.tell_downsample_all(self.state.downsample)

    def select_channel(self):
        """Called when board or channel selector is changed."""
        s = self.state
        if s.num_board<1: return
        s.activeboard = self.ui.boardBox.value()
        s.selectedchannel = self.ui.chanBox.value()

        # This now correctly calls the method to update the checkbox
        self.update_fft_checkbox_state()

        # Update the "Two Channel" checkbox to reflect the state of the newly selected board
        self.ui.twochanCheck.setChecked(self.state.dotwochannel[self.state.activeboard])

        # This handles channel selector limits and other mode-dependent UI
        self._update_channel_mode_ui()

        # Read the trigger state for the newly selected board
        is_ext = bool(s.doexttrig[s.activeboard])
        is_sma = bool(s.doextsmatrig[s.activeboard])

        # Update the checked state of the boxes
        self.ui.exttrigCheck.setChecked(is_ext)
        self.ui.extsmatrigCheck.setChecked(is_sma)

        # Ensure a box is disabled if the other trigger mode is active
        self.ui.exttrigCheck.setEnabled(not is_sma)
        self.ui.extsmatrigCheck.setEnabled(not is_ext)

        # Update UI widgets to reflect the state of the newly selected channel
        self.ui.gainBox.setValue(s.gain[s.activexychannel])
        self.ui.offsetBox.setValue(s.offset[s.activexychannel])
        self.ui.acdcCheck.setChecked(s.acdc[s.activexychannel])
        self.ui.ohmCheck.setChecked(s.mohm[s.activexychannel])
        self.ui.attCheck.setChecked(s.att[s.activexychannel])
        self.ui.tenxCheck.setChecked(s.tenx[s.activexychannel] == 10)
        self.ui.chanonCheck.setChecked(self.plot_manager.lines[s.activexychannel].isVisible())
        self.ui.tadBox.setValue(s.tad[s.activeboard])

        # Update rising/falling trigger
        is_falling = s.fallingedge[s.activeboard]
        self.ui.risingfalling_comboBox.setCurrentIndex(int(is_falling))

        # Update channel color preview box in the UI
        p = self.ui.chanColor.palette()
        p.setColor(QPalette.Base, self.plot_manager.linepens[s.activexychannel].color())
        self.ui.chanColor.setPalette(p)
        self.set_channel_frame()

        # Update the secondary Y-axis
        self.plot_manager.update_right_axis()

        # Update hardware LEDs
        all_colors = [pen.color() for pen in self.plot_manager.linepens]
        self.controller.do_leds(all_colors)

        # NEW: Reset FFT analysis when channel changes
        if self.fftui:
            self.fftui.reset_analysis_state()

    def trigger_pos_changed(self, value):
        """
        Handles the trigger position slider.
        If zoomed in, it pans the view with corrected sensitivity.
        Otherwise, it adjusts the absolute trigger position.
        """
        s = self.state

        if s.downsamplezoom > 1:  # Panning mode when zoomed in
            # --- NEW SENSITIVITY-CORRECTED PANNING LOGIC ---

            # Calculate the full data width and the current view width
            full_width = 4 * 10 * s.expect_samples * (s.downsamplefactor / s.nsunits / s.samplerate)
            view_width = full_width / s.downsamplezoom

            # The true center is the actual trigger time
            trigger_time_center = self.plot_manager.current_vline_pos

            # The slider's deviation from its midpoint (5000) determines the pan distance.
            # A full deflection pans by half a screen width, making it much less sensitive.
            pan_fraction = (value - 5000.0) / 5000.0  # Range is -1.0 to 1.0
            pan_offset = pan_fraction * (view_width / 2.0)

            # The new center of the view is the trigger time plus the pan offset
            new_view_center = trigger_time_center - pan_offset

            # Calculate the new min/max for the view
            s.min_x = new_view_center - (view_width / 2.0)
            s.max_x = new_view_center + (view_width / 2.0)

            # Clamp the view to the boundaries of the data [0, full_width]
            if s.min_x < 0:
                s.min_x = 0
                s.max_x = view_width
            if s.max_x > full_width:
                s.max_x = full_width
                s.min_x = full_width - view_width

            # Apply the new panned range to the plot
            self.plot_manager.plot.setRange(xRange=(s.min_x, s.max_x), padding=0.01)

        else:  # Normal trigger adjust mode
            s.triggerpos = int(s.expect_samples * value / 10000.)
            self.controller.send_trigger_info_all()
            self.plot_manager.draw_trigger_lines()

    def on_vline_dragged(self, value):
        """
        Handles dragging the vertical trigger line.
        If zoomed in, it pans the view and now syncs its position with the slider.
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

            # NEW: Update the slider to reflect the new pan position
            trigger_time_center = self.plot_manager.current_vline_pos
            view_center = s.min_x + (s.max_x - s.min_x) / 2.0
            pan_offset = view_center - trigger_time_center
            view_width = s.max_x - s.min_x

            if view_width > 0:
                # Reverse the calculation to find the slider value
                pan_fraction = pan_offset / (view_width / 2.0)
                slider_value = 5000 - (pan_fraction * 5000)

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

    def on_hline_dragged(self, value):
        t = value / (self.state.yscale * 256) + 127
        self.ui.threshold.setValue(int(t))

    def trigger_level_changed(self, value):
        self.state.triggerlevel = value
        self.controller.send_trigger_info_all()
        self.plot_manager.draw_trigger_lines()

    def time_fast(self):
        if self.state.downsample < -10:
            #print("Maximum zoom level reached.")
            self.ui.timefastButton.setEnabled(False)

        self.state.downsample -= 1
        self.controller.tell_downsample_all(self.state.downsample)

        is_zoomed = self.state.downsample < 0
        if is_zoomed:
            self.state.downsamplezoom = pow(2, -self.state.downsample)
        else:
            self.state.downsamplezoom = 1

        # Update the plot range and text box
        self.time_changed()

        # If we are zoomed in, reset the pan slider to its center position.
        if is_zoomed:
            # Block signals to prevent this from triggering a pan action
            self.ui.thresholdPos.blockSignals(True)
            self.ui.thresholdPos.setValue(5000)
            self.ui.thresholdPos.blockSignals(False)
        
        if self.fftui and not is_zoomed:
            self.fftui.reset_for_timescale_change()
            self.fftui.reset_analysis_state()

    def time_slow(self):
        self.ui.timefastButton.setEnabled(True)
        self.state.downsample += 1
        self.controller.tell_downsample_all(self.state.downsample)

        is_zoomed = self.state.downsample < 0

        if is_zoomed:
            self.state.downsamplezoom = pow(2, -self.state.downsample)
        else:
            self.state.downsamplezoom = 1

        # Update the plot range and text box
        self.time_changed()

        # If we are zoomed in, reset the pan slider to its center position.
        if is_zoomed:
            # Block signals to prevent this from triggering a pan action
            self.ui.thresholdPos.blockSignals(True)
            self.ui.thresholdPos.setValue(5000)
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
        color = QColorDialog.getColor(self.plot_manager.linepens[self.state.activexychannel].color(), self)
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

    def update_firmware(self):
        board = self.state.activeboard
        reply = QMessageBox.question(self, 'Confirmation', f'Update firmware on board {board} to mine?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.No: return
        if not self.state.paused: self.dostartstop()  # Pause
        success, message = self.controller.update_firmware(board)
        QMessageBox.information(self, "Firmware Update", message)
        if success: self.ui.runButton.setEnabled(False)

    def verify_firmware(self):
        board = self.state.activeboard
        reply = QMessageBox.question(self, 'Confirmation', f'Verify firmware on board {board} matches mine?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.No: return
        if not self.state.paused: self.dostartstop()  # Pause
        success, message = self.controller.update_firmware(board, verify_only=True)
        QMessageBox.information(self, "Firmware Verify", message)

    def set_channel_frame(self):
        s = self.state
        is_trigger_channel = not (s.doexttrig[s.activeboard] or s.doextsmatrig[s.activeboard] or s.triggerchan[
            s.activeboard] != s.activexychannel % 2)
        self.ui.chanColor.setFrameStyle(QFrame.Box if is_trigger_channel else QFrame.NoFrame)

    def chanon_changed(self, checked):
        """Toggles the visibility of the currently selected channel's trace."""
        # Set the visibility of the main line plot item
        self.plot_manager.lines[self.state.activexychannel].setVisible(bool(checked))

        # Update the average line's pen and visibility, which depends on this checkbox
        self.set_average_line_pen()

    def set_average_line_pen(self):
        """
        Updates the appearance and visibility of the main trace, the average trace,
        and the faint persistence traces based on UI settings.
        """
        # First, tell the plot manager to update the pen style/color of the average line
        self.plot_manager.set_average_line_pen()

        # Get the state of the relevant UI checkboxes
        is_chan_on = self.ui.chanonCheck.isChecked()
        show_persist_lines = self.ui.persistlinesCheck.isChecked()
        show_persist_avg = self.ui.persistavgCheck.isChecked()

        # Get the line objects from the plot manager
        active_line = self.plot_manager.lines[self.state.activexychannel]
        average_line = self.plot_manager.average_line

        # If the main "Channel On" box is unchecked, everything for this channel is hidden.
        if not is_chan_on:
            active_line.setVisible(False)
            average_line.setVisible(False)
            for item, _, _ in self.plot_manager.persist_lines:
                item.setVisible(False)
            return

        # --- VISIBILITY LOGIC WHEN CHANNEL IS ON ---

        # 1. The average line's visibility is directly tied to its checkbox.
        average_line.setVisible(show_persist_avg)

        # 2. The faint persist lines' visibility is tied to their checkbox.
        for item, _, _ in self.plot_manager.persist_lines:
            item.setVisible(show_persist_lines)

        # 3. THIS IS YOUR NEW RULE:
        #    Hide the main trace ONLY if the average is on AND the faint lines are off.
        if show_persist_avg and not show_persist_lines:
            active_line.setVisible(False)
        else:
            active_line.setVisible(True)

    # #########################################################################
    # ## Slot Implementations (Callbacks for UI events)
    # #########################################################################

    def take_reference_waveform(self, checked):
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

            # Trigger a redraw to show the new reference immediately
            self.time_changed()

    def toggle_reference_waveform_visibility(self):
        """Slot for 'Show Reference'. Triggers a redraw to apply visibility."""
        self.time_changed() # Re-running time_changed will handle the visibility flag


    def fft_clicked(self):
        """Toggles the FFT window state for the active channel."""
        active_channel_name = f"CH{self.state.activexychannel + 1}"
        is_checked = self.ui.fftCheck.isChecked()
        self.state.fft_enabled[active_channel_name] = is_checked

        if self.fftui is None:
            self.fftui = FFTWindow()

        should_show = any(self.state.fft_enabled.values())
        if should_show:
            self.fftui.show()
        else:
            self.fftui.hide()

    def update_fft_checkbox_state(self):
        """Updates the 'FFT' checkbox to reflect the state of the active channel."""
        active_channel_name = f"CH{self.state.activexychannel + 1}"
        if active_channel_name not in self.state.fft_enabled:
            self.state.fft_enabled[active_channel_name] = False

        self.ui.fftCheck.blockSignals(True)
        self.ui.fftCheck.setChecked(self.state.fft_enabled[active_channel_name])
        self.ui.fftCheck.blockSignals(False)

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

        # 1. Update the state for the active board ONLY
        s.dotwochannel[active_board] = is_two_channel

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
        self.controller.set_oversampling(board, bool(checked))
        if bool(checked):
            self.ui.interleavedCheck.setEnabled(True)
            self.ui.twochanCheck.setEnabled(False)
        else:
            self.ui.interleavedCheck.setEnabled(False)
            self.ui.interleavedCheck.setChecked(False)
            self.ui.twochanCheck.setEnabled(True)
        self.gain_changed()
        self.offset_changed()
        all_colors = [pen.color() for pen in self.plot_manager.linepens]
        self.controller.do_leds(all_colors)

    def interleave_changed(self, checked):
        s = self.state
        board = s.activeboard
        s.dointerleaved[board] = bool(checked)
        s.dointerleaved[board + 1] = bool(checked)

        # Hide the traces from the secondary board
        c_secondary = (board + 1) * s.num_chan_per_board
        self.plot_manager.lines[c_secondary].setVisible(not bool(checked))

        self.time_changed()
        all_colors = [pen.color() for pen in self.plot_manager.linepens]
        self.controller.do_leds(all_colors)

    def tad_changed(self, value):
        self.state.tad[self.state.activeboard] = value
        self.controller.set_tad(self.state.activeboard, value)

    def trigger_delta_changed(self, value):
        self.state.triggerdelta = value
        self.controller.send_trigger_info_all()

    def trigger_chan_changed(self, index):
        self.state.triggerchan[self.state.activeboard] = index
        self.controller.send_trigger_info(self.state.activeboard)
        self.set_channel_frame()

    def rising_falling_changed(self, index):
        self.state.fallingedge[self.state.activeboard] = (index == 1)
        # Assuming trigger types 1=rising, 2=falling
        self.state.triggertype[self.state.activeboard] = 2 if (index == 1) else 1

    def tot_changed(self, value):
        self.state.triggertimethresh = value
        self.controller.send_trigger_info_all()

    def exttrig_changed(self, checked):
        board = self.state.activeboard
        self.state.doexttrig[board] = bool(checked)
        self.controller.set_exttrig(board, bool(checked))
        self.ui.extsmatrigCheck.setEnabled(not bool(checked))
        self.set_channel_frame()

    def extsmatrig_changed(self, checked):
        """
        Handles the 'External SMA Trigger' checkbox.
        This only updates the internal state; no immediate hardware command is sent.
        """
        board = self.state.activeboard
        self.state.doextsmatrig[board] = bool(checked)

        # Update the UI to prevent conflicting trigger sources from being selected
        self.ui.exttrigCheck.setEnabled(not bool(checked))
        self.set_channel_frame()

    def lpf_changed(self):
        thetext = self.ui.lpfBox.currentText()
        self.state.lpf = 0 if thetext == "Off" else int(thetext)

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

    # #########################################################################
    # ## Calibration functions
    # #########################################################################

    def autocalibration(self, resamp=2, dofiner=False, oldtoff=0, finewidth=16):
        """
        Performs an automated calibration to align the timing of two boards.
        It finds the coarse offset (Toff) and then the fine-grained offset (TAD).
        """
        # If called from the GUI, the first argument is 'False'. Reset to defaults.
        if not resamp:
            resamp = 2
            dofiner = False
            oldtoff = 0

        print(f"Autocalibration running with: resamp={resamp}, dofiner={dofiner}, finewidth={finewidth}")
        s = self.state
        if s.activeboard % 2 == 1:
            print("Error: Please select the even-numbered board of a pair (e.g., 0, 2) to calibrate.")
            return

        # Gently reset the fine-grained delay (TAD) to 0 before starting
        if s.tad[s.activeboard] != 0:
            print("Resetting TAD to 0 before calibration...")
            for t in range(abs(s.tad[s.activeboard]) // 5 + 1):
                current_tad = self.ui.tadBox.value()
                if current_tad == 0: break
                new_tad = current_tad - 5 if current_tad > 0 else current_tad + 5
                self.ui.tadBox.setValue(new_tad)  # This will trigger tad_changed
                time.sleep(.1)

        # Get data from the primary board and the board-under-test
        c1 = s.activeboard * s.num_chan_per_board
        c2 = (s.activeboard + 1) * s.num_chan_per_board
        c1data = self.xydata[c1]
        c2data = self.xydata[c2]

        # Resample data for higher timing resolution
        c1datanewy, c1datanewx = resample(c1data[1], len(c1data[0]) * resamp, t=c1data[0])
        c2datanewy, c2datanewx = resample(c2data[1], len(c2data[0]) * resamp, t=c2data[0])

        # Define the search range for the time shift
        minrange = -s.toff * resamp
        if dofiner: minrange = (s.toff - oldtoff - finewidth) * resamp
        maxrange = 10 * s.expect_samples * resamp
        if dofiner: maxrange = (s.toff - oldtoff + finewidth) * resamp

        c2datanewy = np.roll(c2datanewy, int(minrange))

        minrms = 1e9
        minshift = 0
        fitwidth = (s.max_x - s.min_x) * s.fitwidthfraction
        vline = self.plot_manager.otherlines['vline'].value()

        # Iterate through all possible shifts and find the one with the minimum RMS difference
        print(f"Searching for best shift in range {minrange} to {maxrange}...")
        for nshift in range(int(minrange), int(maxrange)):
            yc1 = c1datanewy[(c1datanewx > vline - fitwidth) & (c1datanewx < vline + fitwidth)]
            yc2 = c2datanewy[(c2datanewx > vline - fitwidth) & (c2datanewx < vline + fitwidth)]
            if len(yc1) != len(yc2): continue  # Skip if windowing results in unequal lengths

            therms = np.std(yc1 - yc2)
            if therms < minrms:
                minrms = therms
                minshift = nshift
            c2datanewy = np.roll(c2datanewy, 1)

        print(f"Minimum RMS difference found for total shift = {minshift}")

        if dofiner:
            # Fine-tuning phase: adjust Toff slightly and set the final TAD value
            s.toff = minshift // resamp + oldtoff - 1
            self.ui.ToffBox.setValue(s.toff)

            # Convert the subsample shift into a hardware TAD value
            tadshift = round((138.4 * 2 / resamp) * (minshift % resamp), 1)
            tadshiftround = round(tadshift + 138.4)
            print(f"Optimal TAD value calculated to be ~{tadshiftround}")

            if tadshiftround < 250:
                print("Setting final TAD value...")
                for t in range(abs(s.tad[s.activeboard] - tadshiftround) // 5 + 1):
                    current_tad = self.ui.tadBox.value()
                    if abs(current_tad - tadshiftround) < 5: break
                    new_tad = current_tad + 5 if current_tad < tadshiftround else current_tad - 5
                    self.ui.tadBox.setValue(new_tad)
                    time.sleep(.1)
                print("Autocalibration finished.")
            else:
                print("Required TAD shift is too large. Adjusting clock phase and retrying.")
                self.controller.do_phase(s.activeboard + 1, plloutnum=0, updown=1, pllnum=0)
                self.controller.do_phase(s.activeboard + 1, plloutnum=1, updown=1, pllnum=0)
                self.controller.do_phase(s.activeboard + 1, plloutnum=2, updown=1, pllnum=0)
                s.triggerautocalibration[s.activeboard + 1] = True  # Request another calibration after new data
        else:
            # Coarse phase: find the rough Toff value, then do DC/RMS correction, then start the fine-tuning phase
            oldtoff = s.toff
            s.toff = minshift // resamp + s.toff
            print(f"Coarse Toff set to {s.toff}. Performing mean/RMS calibration...")
            self.do_meanrms_calibration()
            print("Starting fine-tuning phase...")
            self.autocalibration(resamp=64, dofiner=True, oldtoff=oldtoff)

    def do_meanrms_calibration(self):
        """Calculates and applies DC offset and amplitude (RMS) corrections between two boards."""
        s = self.state
        if s.activeboard % 2 == 1:
            print("Error: Please select the even-numbered board of a pair (e.g., 0, 2) to calibrate.")
            return

        # c1 is the primary board (e.g. board 0), c2 is the secondary (e.g. board 1)
        c1_idx = s.activeboard * s.num_chan_per_board
        c2_idx = (s.activeboard + 1) * s.num_chan_per_board

        fitwidth = (s.max_x - s.min_x) * 0.99
        vline = self.plot_manager.otherlines['vline'].value()

        # Get y-data for both channels within the fit window
        yc1 = self.xydata[c1_idx][1][
            (self.xydata[c1_idx][0] > vline - fitwidth) & (self.xydata[c1_idx][0] < vline + fitwidth)]
        yc2 = self.xydata[c2_idx][1][
            (self.xydata[c2_idx][0] > vline - fitwidth) & (self.xydata[c2_idx][0] < vline + fitwidth)]

        if len(yc1) == 0 or len(yc2) == 0:
            print("Mean/RMS calibration failed: no data in window.")
            return

        # Calculate mean and standard deviation for each channel
        mean_primary = np.mean(yc1)
        std_primary = np.std(yc1)
        mean_secondary = np.mean(yc2)
        std_secondary = np.std(yc2)

        # The correction to ADD to the secondary data is (primary - secondary)
        s.extrigboardmeancorrection[s.activeboard] += (mean_primary - mean_secondary)

        # The correction to MULTIPLY the secondary data by is (primary / secondary)
        if std_secondary > 0:
            s.extrigboardstdcorrection[s.activeboard] *= (std_primary / std_secondary)

        print(f"Updated corrections to be applied to board {s.activeboard + 1}: "
              f"Mean+={s.extrigboardmeancorrection[s.activeboard]:.4f}, "
              f"Std*={s.extrigboardstdcorrection[s.activeboard]:.4f}")