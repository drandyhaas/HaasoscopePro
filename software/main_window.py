# main_window.py

import sys, time, math, warnings
import numpy as np
import threading
from collections import deque
from scipy.signal import resample
from pyqtgraph.Qt import QtCore, QtWidgets, loadUiType
import pyqtgraph as pg
from PyQt5.QtWidgets import QMessageBox, QColorDialog, QFrame, QAction
from PyQt5.QtGui import QPalette, QIcon, QStandardItemModel, QStandardItem, QCursor

# Import all the refactored components
from scope_state import ScopeState
from hardware_controller import HardwareController
from data_processor import DataProcessor, format_freq
from plot_manager import PlotManager
from data_recorder import DataRecorder
from histogram_window import HistogramWindow
from calibration import autocalibration, do_meanrms_calibration

# Import remaining dependencies
from FFTWindow import FFTWindow
from SCPIsocket import DataSocket
from board import setupboard, gettemps
from utils import get_pwd
import ftd2xx

pwd = get_pwd()
print(f"Current dir is {pwd}")


class HistogramWindow(QtWidgets.QWidget):
    """Popup window showing a histogram of measurement values."""
    
    def __init__(self, parent=None, plot_manager=None):
        super().__init__(parent)
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.plot_manager = plot_manager
        
        # Setup layout
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Create plot widget
        self.plot_widget = pg.PlotWidget()
        
        # Match styling to main plot
        from PyQt5.QtGui import QColor
        self.plot_widget.setBackground(QColor('black'))
        self.plot_widget.showGrid(x=True, y=True, alpha=0.8)
        
        # Set font and styling to match main plot
        font = QtWidgets.QApplication.font()
        font.setPixelSize(11)

        for axis in ['bottom', 'left']:
            axis_item = self.plot_widget.getAxis(axis)
            axis_item.setStyle(tickFont=font)
            self.plot_widget.getAxis(axis).setPen('grey')
            self.plot_widget.getAxis(axis).setTextPen('grey')

        # Set title font
        self.plot_widget.getPlotItem().titleLabel.item.setFont(font)

        # Disable mouse interactions
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)

        self.plot_widget.setLabel('left', 'Count')
        self.plot_widget.setLabel('bottom', 'Value')

        layout.addWidget(self.plot_widget)
        self.setLayout(layout)

        self.bar_graph = None

    def update_histogram(self, measurement_name, values, brush_color=None):
        """Update the histogram with new data."""
        if len(values) == 0:
            return

        # Calculate histogram
        y, x = np.histogram(list(values), bins=20)

        # Use provided color or default to blue
        if brush_color is None:
            brush_color = 'b'

        # Create bar graph if it doesn't exist
        if self.bar_graph is None:
            self.bar_graph = pg.BarGraphItem(x=x[:-1], height=y, width=(x[1]-x[0])*0.8, brush=brush_color)
            self.plot_widget.addItem(self.bar_graph)
        else:
            self.bar_graph.setOpts(x=x[:-1], height=y, width=(x[1]-x[0])*0.8, brush=brush_color)

        # Update title and axis
        self.plot_widget.setTitle(f'{measurement_name} Distribution (n={len(values)})', color='grey')

    def position_relative_to_table(self, table_widget, main_plot_widget):
        """Position the window to the left of the measurement table, with bottom aligned to main plot."""
        # Get table geometry in global coordinates
        table_global_pos = table_widget.mapToGlobal(table_widget.pos())
        table_rect = table_widget.geometry()

        # Get main plot bottom position
        plot_global_pos = main_plot_widget.mapToGlobal(main_plot_widget.pos())
        plot_rect = main_plot_widget.geometry()
        plot_bottom = plot_global_pos.y() + plot_rect.height()

        # Position to the left of table, with same width and bottom aligned to plot
        heightcorr = 0
        if table_rect.height()>300: heightcorr = table_rect.height() - 300
        self.setGeometry(table_global_pos.x() - table_rect.width() - 2,
                        plot_bottom - table_rect.height() - 8 + heightcorr,
                        table_rect.width(),
                        table_rect.height() - heightcorr)


WindowTemplate, TemplateBaseClass = loadUiType(pwd + "/HaasoscopePro.ui")
class MainWindow(TemplateBaseClass):
    def __init__(self, usbs):
        super().__init__()

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

        # 5. Initialize network socket and other components
        self.socket = None
        self.socket_thread = None
        self.fftui = None
        self.ui.boardBox.setMaximum(self.state.num_board - 1)

        # Initialize the table model and item tracking
        self.measurement_model = QStandardItemModel()
        self.ui.tableView.setModel(self.measurement_model)
        self.measurement_model.setHorizontalHeaderLabels(["Measurement", "Value", "Avg (100)", "RMS (100)"])
        self.measurement_items = {} # To store references to QStandardItem objects
        self.setup_successful = False
        self.measurement_history = {} # To store the last 100 values: {name: deque}
        self.last_temp_update_time = 0
        self.cached_temps = (0, 0)  # (adc_temp, board_temp)
        self.reference_data = {}  # Stores {channel_index: {'x_ns': array, 'y': array}}

        # Histogram window for measurements
        self.histogram_window = HistogramWindow(self, self.plot_manager)
        self.histogram_timer = QtCore.QTimer()

        # 6. Setup timers for data acquisition and measurement updates
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plot_loop)
        self.timer2 = QtCore.QTimer()
        self.timer2.timeout.connect(self.update_measurements_display)
        self.status_timer = QtCore.QTimer()
        self.status_timer.timeout.connect(self.update_status_bar)

        # Setup selection tracking for measurement table
        self.ui.tableView.selectionModel().selectionChanged.connect(self.on_measurement_selection_changed)

        self.histogram_timer.timeout.connect(self.update_histogram_display)
        self.current_histogram_measurement = None

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
                # This block runs if setup_all_boards fails for any reason.
                self.ui.actionUpdate_firmware.setEnabled(False)
                self.ui.actionVerify_firmware.setEnabled(False)
                self.ui.runButton.setEnabled(False)

            # Firmware Version Check (only if setup passed)
            if self.setup_successful:
                req_firmware_ver = 28
                if self.state.firmwareversion < req_firmware_ver:
                    if not self.state.paused: self.dostartstop()
                    self.ui.runButton.setEnabled(False)
                    QMessageBox.warning(self, "Firmware Update Required",
                                        f"The firmware on a board is outdated.\n"
                                        f"Firmware {self.state.firmwareversion} found but v{req_firmware_ver}+ required\n\n"
                                        "Please update to the latest firmware.\n"
                                        "Data acquisition has been disabled.")

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

        # Perform an initial adjustment of the table geometry
        self._adjust_table_view_geometry()

        # Set column widths for the measurement table
        self.ui.tableView.setColumnWidth(0, 135)  # Measurement name column
        self.ui.tableView.setColumnWidth(1, 80)  # Measurement value column
        self.ui.tableView.setColumnWidth(2, 80)  # Measurement avg column
        self.ui.tableView.setColumnWidth(3, 80)  # Measurement rms column
        self.show()

    def on_measurement_selection_changed(self, selected, deselected):
        """Handle measurement table selection changes."""
        # Get selected indexes
        indexes = self.ui.tableView.selectionModel().selectedIndexes()

        if indexes:
            # Get the first selected row (column 0 = measurement name)
            row = indexes[0].row()
            name_item = self.measurement_model.item(row, 0)

            if name_item:
                measurement_name = name_item.text().split(' (')[0]  # Remove unit suffix

                if measurement_name in self.measurement_history:
                    self.current_histogram_measurement = measurement_name
                    self.histogram_window.position_relative_to_table(self.ui.tableView, self.ui.plot)
                    self.histogram_window.show()
                    
                    # Get color from active channel
                    brush_color = self.plot_manager.linepens[self.state.activexychannel].color()
                    self.histogram_window.update_histogram(measurement_name, 
                                                          self.measurement_history[measurement_name],
                                                          brush_color)
                    if not self.histogram_timer.isActive():
                        self.histogram_timer.start(100)  # Update at 10 Hz
        else:
            # No selection - hide histogram
                self.hide_histogram()

    def _sync_initial_ui_state(self):
        """A one-time function to sync the UI's visual state after the window has loaded."""
        # This function is called just after the main event loop starts.
        self.ui.rollingButton.setChecked(bool(self.state.isrolling))
        self.ui.rollingButton.setText(" Auto " if self.state.isrolling else " Normal ")
        self.ui.runButton.setText(" Run ")
        self.ui.actionPan_and_zoom.setChecked(False)
        self.plot_manager.set_pan_and_zoom(False)

    def update_histogram_display(self):
        """Update the histogram window with current data."""
        if self.current_histogram_measurement and self.histogram_window.isVisible():
            if self.current_histogram_measurement in self.measurement_history:
                # Get color from active channel
                brush_color = self.plot_manager.linepens[self.state.activexychannel].color()
                self.histogram_window.update_histogram(
                    self.current_histogram_measurement,
                    self.measurement_history[self.current_histogram_measurement],
                    brush_color
                )
    
    def hide_histogram(self):
        """Hide the histogram window and stop updates."""
        self.histogram_window.hide()
        self.histogram_timer.stop()
        self.current_histogram_measurement = None

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
        self.ui.actionMarkers.triggered.connect(lambda checked: self.plot_manager.set_markers(checked))
        self.ui.actionPan_and_zoom.triggered.connect(lambda checked: self.plot_manager.set_pan_and_zoom(checked))
        self.ui.actionVoltage_axis.triggered.connect(lambda checked: self.plot_manager.right_axis.setVisible(checked))
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
        self.ui.actionDo_autocalibration.triggered.connect(lambda: autocalibration(self))
        self.ui.actionOversampling_mean_and_RMS.triggered.connect(lambda: do_meanrms_calibration(self))
        self.ui.actionToggle_trig_stabilizer.triggered.connect(self.trig_stabilizer_toggled)
        self.ui.actionToggle_extra_trig_stabilizer.triggered.connect(self.extra_trig_stabilizer_toggled)

        # Plot manager signals
        self.plot_manager.vline_dragged_signal.connect(self.on_vline_dragged)
        self.plot_manager.hline_dragged_signal.connect(self.on_hline_dragged)
        self.plot_manager.curve_clicked_signal.connect(self.on_curve_clicked)

        # Reference menu actions
        self.ui.actionTake_Reference.triggered.connect(self.take_reference_waveform)
        self.ui.actionShow_Reference.triggered.connect(self.toggle_reference_waveform_visibility)

        # View menu actions
        self.ui.actionXY_Plot.triggered.connect(self.toggle_xy_view_slot)

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

        # If the flag is set, get and discard the next event to avoid glitches
        if self.state.skip_next_event:
            self.state.skip_next_event = False
            try:
                self.controller.get_event() # Fetch and discard
            except ftd2xx.DeviceError:
                pass # Ignore potential errors during this flush
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
            self.ui.actionUpdate_firmware.setEnabled(False)
            self.ui.actionVerify_firmware.setEnabled(False)
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

        for board_idx in range(s.num_board):
            if s.dooversample[board_idx] and board_idx%2==0:
                do_meanrms_calibration(self)
                break

        # --- Plotting Logic: Switch between Time Domain and XY Mode ---
        if self.state.xy_mode:
            # For XY mode, we need to ensure the data lengths match.
            # We'll use the data from the first two channels of the active board.
            board = self.state.activeboard
            # Ensure channel 1 is enabled for two-channel mode to get data
            if self.state.dotwochannel[board]:
                ch0_index = board * self.state.num_chan_per_board
                ch1_index = ch0_index + 1
                # In two-channel mode, only the first half of the buffer is valid data
                num_valid_samples = self.xydata.shape[2] // 2
                y_data_ch0 = self.xydata[ch0_index][1][:num_valid_samples]
                x_data_ch1 = self.xydata[ch1_index][1][:num_valid_samples]
                self.plot_manager.update_xy_plot(x_data=x_data_ch1, y_data=y_data_ch0)
        else:
            self.plot_manager.update_plots(self.xydata, self.xydatainterleaved)

        if self.recorder.is_recording:
            lines_vis = [line.isVisible() for line in self.plot_manager.lines]
            self.recorder.record_event(self.xydata, self.plot_manager.otherlines['vline'].value(), lines_vis)

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

        now = time.time()
        dt = now - self.last_time + 1e-9
        self.last_time = now
        self.fps = 1.0 / dt if self.fps is None else self.fps * 0.9 + (1.0 / dt) * 0.1

        self.state.isdrawing = False

        # Sync the Depth box UI with the state, in case it was changed by a PLL reset
        self._sync_depth_ui_from_state()

        # If 'getone' (Single) mode is active, call dostartstop() immediately
        # after successfully processing one event. This will pause the acquisition.
        if self.state.getone:
            self.dostartstop()

    def update_status_bar(self):
        """Updates the status bar text at a fixed rate (5 Hz)."""
        s = self.state
        if s.num_board < 1 or self.fps is None: return
        sradjust = 1e9
        if s.dointerleaved[s.activeboard]: sradjust = 2e9
        elif s.dotwochannel[s.activeboard]: sradjust = 0.5e9
        effective_sr = s.samplerate * sradjust / (s.downsamplefactor if not s.highresval else 1)
        status_text = (f"{format_freq(effective_sr, 'S/s')}, {self.fps:.2f} fps, "
                       f"{s.nevents} events, {s.lastrate:.2f} Hz, "
                       f"{(s.lastrate * s.lastsize / 1e6):.2f} MB/s")
        if self.recorder.is_recording: status_text += ", Recording to "+str(self.recorder.file_handle.name)
        self.ui.statusBar.showMessage(status_text)

    def update_measurements_display(self):
        """Slow timer callback to update measurements in the table view without clearing it."""
        active_measurements = set()

        def _set_measurement(name, value, unit=""):
            """Helper to add or update a measurement row in the table."""
            active_measurements.add(name)
            value = round(value, 2)
            if unit != "":
                unit = " (" + unit + ")"

            # Initialize history deque if this is a new measurement
            if name not in self.measurement_history:
                self.measurement_history[name] = deque(maxlen=100)

            # Add current value to history
            self.measurement_history[name].append(value)

            # Calculate average and RMS
            history = self.measurement_history[name]
            avg_value = round(np.mean(history), 2)
            rms_value = round(np.std(history), 2)

            if name in self.measurement_items:
                # Update existing item's value, average, and RMS
                self.measurement_items[name][1].setText(str(value))
                self.measurement_items[name][0].setText(name + unit)
                self.measurement_items[name][2].setText(str(avg_value))
                self.measurement_items[name][3].setText(str(rms_value))
            else:
                # Add new row and store items
                name_item = QStandardItem(name + unit)
                value_item = QStandardItem(str(value))
                avg_item = QStandardItem(str(avg_value))
                rms_item = QStandardItem(str(rms_value))
                self.measurement_model.appendRow([name_item, value_item, avg_item, rms_item])
                self.measurement_items[name] = (name_item, value_item, avg_item, rms_item)

        if self.state.dodrawing:
            if self.ui.actionTrigger_thresh.isChecked():
                hline_val = self.plot_manager.otherlines['hline'].value()
                _set_measurement("Trig threshold", hline_val, "div")

            if self.ui.actionN_persist_lines.isChecked():
                num_persist = len(self.plot_manager.persist_lines)
                _set_measurement("Persist lines", num_persist)

            if self.ui.actionTemperatures.isChecked():
                # Only read temperatures once per second (slow USB operation)
                current_time = time.time()
                if current_time - self.last_temp_update_time >= 1.0:
                    if self.state.num_board > 0:
                        active_usb = self.controller.usbs[self.state.activeboard]
                        adctemp, boardtemp = gettemps(active_usb)
                        self.cached_temps = (adctemp, boardtemp)
                        self.last_temp_update_time = current_time

                # Always call _set_measurement with cached values to keep the row active
                if self.state.num_board > 0:
                    _set_measurement("ADC temp", self.cached_temps[0], "\u00b0C")
                    _set_measurement("Board temp", self.cached_temps[1], "\u00b0C")

            if hasattr(self, 'xydata'):
                x_data_for_analysis = self.plot_manager.lines[self.state.activexychannel].xData
                y_data_for_analysis = self.plot_manager.lines[self.state.activexychannel].yData

                if y_data_for_analysis is not None and len(y_data_for_analysis) > 0:
                    vline_val = self.plot_manager.otherlines['vline'].value()
                    measurements, fit_results = self.processor.calculate_measurements(
                        x_data_for_analysis, y_data_for_analysis, vline_val,
                        do_risetime_calc=self.ui.actionRisetime.isChecked()
                    )

                    if self.ui.actionMean.isChecked(): _set_measurement("Mean", measurements.get('Mean', 0), "mV")
                    if self.ui.actionRMS.isChecked(): _set_measurement("RMS", measurements.get('RMS', 0), "mV")
                    if self.ui.actionMinimum.isChecked(): _set_measurement("Min", measurements.get('Min', 0), "mV")
                    if self.ui.actionMaximum.isChecked(): _set_measurement("Max", measurements.get('Max', 0), "mV")
                    if self.ui.actionVpp.isChecked(): _set_measurement("Vpp", measurements.get('Vpp', 0), "mV")
                    if self.ui.actionFreq.isChecked():
                        freq = measurements.get('Freq', 0)
                        freq, unit = format_freq(freq, "Hz", False)
                        _set_measurement("Freq", freq, unit)
                    if self.ui.actionRisetime.isChecked():
                        self.plot_manager.update_risetime_fit_lines(fit_results)
                        risetime_val = measurements.get('Risetime', 0)
                        if math.isfinite(risetime_val): _set_measurement("Risetime", risetime_val, "ns")
                        if self.ui.actionRisetime_error.isChecked():
                            risetime_err_val = measurements.get('Risetime error', 0)
                            if math.isfinite(risetime_err_val):_set_measurement("Risetime error", risetime_err_val, "ns")

        # Remove stale measurements that are no longer selected
        stale_keys = list(self.measurement_items.keys() - active_measurements)

        rows_to_remove = []
        for key in stale_keys:
            # Find the item in the model by its text to avoid accessing a deleted C++ object
            items = self.measurement_model.findItems(key, QtCore.Qt.MatchStartsWith)
            if items:
                rows_to_remove.append(items[0].row())

        # Remove rows from the model, from bottom to top, to avoid index shifting issues
        for row in sorted(list(set(rows_to_remove)), reverse=True):
            self.measurement_model.removeRow(row)

        # Now, clean up the tracking dictionary and history
        for key in stale_keys:
            if key in self.measurement_items:
                del self.measurement_items[key]
            if key in self.measurement_history:
                del self.measurement_history[key]

    def _adjust_table_view_geometry(self):
        """Sets the table view geometry to fill the bottom of the side panel."""
        frame_height = self.ui.frame.height()
        table_top_y = 600  # The Y coordinate where the table should start
        table_height = frame_height - table_top_y

        # Ensure the height is not negative if the window is very short
        if table_height < 50:
            table_height = 50

        # Also account for the frame's width
        frame_width = self.ui.frame.width()

        self.ui.tableView.setGeometry(
            0,            # x
            table_top_y,  # y
            frame_width,  # width
            table_height  # height
        )

    def resizeEvent(self, event):
        """Handles window resize events to adjust the table view."""
        super().resizeEvent(event)  # Call the parent's resize event
        
        # Close histogram window when main window resizes
        if self.histogram_window.isVisible():
            self.hide_histogram()

        # Use a single shot timer to ensure the layout has settled before adjusting
        QtCore.QTimer.singleShot(1, self._adjust_table_view_geometry)
    
    def moveEvent(self, event):
        """Handles window move events."""
        super().moveEvent(event)

        # Close histogram window when main window moves
        if self.histogram_window.isVisible():
            self.hide_histogram()

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
        self.histogram_window.close()
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
            self.timer2.start(20)  # 20ms interval = 50 Hz for measurements
            self.status_timer.start(200)  # Start status timer at 5 Hz
            self.state.paused = False
            self.ui.runButton.setChecked(True)
        else:
            self.timer.stop()
            self.timer2.stop()
            #self.status_timer.stop() # Stop status timer
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

    def toggle_xy_view_slot(self, checked, board_num=0):
        """Slot for the 'XY Plot' menu action."""
        board = self.state.activeboard
        if checked:
            ch0_index = board * self.state.num_chan_per_board
            pen = self.plot_manager.linepens[ch0_index]
            self.plot_manager.set_xy_pen(pen)
        self.plot_manager.toggle_xy_view(checked, board)

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

        # If we are in XY mode and two-channel is turned off, exit XY mode
        if s.xy_mode and not is_two_channel:
            self.ui.actionXY_Plot.setChecked(False)
            self.plot_manager.toggle_xy_view(False, s.activeboard)
        
        # The next event after a mode switch can be glitchy, so we'll skip it.
        s.skip_next_event = True


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
