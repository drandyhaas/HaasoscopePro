# main_window.py

import sys
import time
import numpy as np
import threading
from scipy.signal import resample
from pyqtgraph.Qt import QtCore, QtWidgets, loadUiType
from PyQt5.QtWidgets import QMessageBox, QColorDialog, QFrame
from PyQt5.QtGui import QPalette, QIcon
import math
import warnings

# Import all the refactored components
from scope_state import ScopeState
from hardware_controller import HardwareController
from data_processor import DataProcessor, format_freq
from plot_manager import PlotManager
from data_recorder import DataRecorder

# Import remaining dependencies
from FFTWindow import FFTWindow
from SCPIsocket import hspro_socket
from board import get_pwd, setupboard  # Assuming get_pwd and other funcs are in board.py or usbs.py

WindowTemplate, TemplateBaseClass = loadUiType(get_pwd() + "/HaasoscopePro.ui")


class MainWindow(TemplateBaseClass):
    def __init__(self, usbs):
        super().__init__()

        # 1. Initialize core components
        self.state = ScopeState(num_boards=len(usbs), num_chan_per_board=2)
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
        self.hsprosock = None
        self.hsprosock_t1 = None
        self.fftui = None
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

    def _sync_initial_ui_state(self):
        """A one-time function to sync the UI's visual state after the window has loaded."""
        # This function is called just after the main event loop starts.
        self.ui.rollingButton.setChecked(bool(self.state.isrolling))
        self.ui.rollingButton.setText("Auto" if self.state.isrolling else "Normal")

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
        self.ui.fftCheck.clicked.connect(self.fft_clicked)
        self.ui.persistTbox.valueChanged.connect(self.plot_manager.set_persistence)
        self.ui.persistavgCheck.clicked.connect(self.set_average_line_pen)
        self.ui.persistlinesCheck.clicked.connect(self.set_average_line_pen)
        self.ui.actionLine_color.triggered.connect(self.change_channel_color)

        # Advanced/Hardware controls
        self.ui.pllresetButton.clicked.connect(
            lambda: self.controller.pllreset(self.state.activeboard, from_button=True))
        self.ui.tadBox.valueChanged.connect(self.tad_changed)
        self.ui.ToffBox.valueChanged.connect(lambda val: setattr(self.state, 'toff', val))
        self.ui.Auxout_comboBox.currentIndexChanged.connect(self.auxout_changed)

        # Menu actions
        self.ui.actionAbout.triggered.connect(self.about_dialog)
        self.ui.actionTake_screenshot.triggered.connect(self.take_screenshot)
        self.ui.actionRecord.triggered.connect(self.toggle_recording)
        self.ui.actionUpdate_firmware.triggered.connect(self.update_firmware)
        self.ui.actionDo_autocalibration.triggered.connect(self.autocalibration)

        # Plot manager signals
        self.plot_manager.vline_dragged_signal.connect(self.on_vline_dragged)
        self.plot_manager.hline_dragged_signal.connect(self.on_hline_dragged)

    def _update_channel_mode_ui(self):
        """
        A centralized function to synchronize all UI elements related to the
        channel mode (Single, Two Channel, Oversampling).
        """
        s = self.state

        # Set the maximum value of the channel selector based on the two-channel state.
        # This is the key fix for your issue.
        if s.dotwochannel:
            self.ui.chanBox.setMaximum(s.num_chan_per_board - 1)
        else:
            # If not in two-channel mode, force chanBox to 0 and set its maximum to 0.
            if self.ui.chanBox.value() != 0:
                self.ui.chanBox.setValue(0)
            self.ui.chanBox.setMaximum(0)

        # Also update the trigger channel dropdown
        self.ui.trigchan_comboBox.setMaxVisibleItems(2 if s.dotwochannel else 1)
        if not s.dotwochannel:
            self.ui.trigchan_comboBox.setCurrentIndex(0)

    def open_socket(self):
        print("Starting SCPI socket thread...")
        self.hsprosock = hspro_socket()
        self.hsprosock.hspro = self
        self.hsprosock.runthethread = True
        self.hsprosock_t1 = threading.Thread(target=self.hsprosock.open_socket, args=(10,))
        self.hsprosock_t1.start()

    def close_socket(self):
        """Safely stops and joins the SCPI socket thread before exiting."""
        if self.hsprosock is not None:
            print("Closing SCPI socket...")
            self.hsprosock.runthethread = False
            # Check if the thread is alive before trying to join it
            if self.hsprosock_t1 and self.hsprosock_t1.is_alive():
                self.hsprosock_t1.join()

    # #########################################################################
    # ## Core Application Logic
    # #########################################################################

    def update_plot_loop(self):
        """Main acquisition loop, with full status bar reporting."""
        if self.hsprosock and self.hsprosock.issending:
            time.sleep(0.001)
            return

        self.state.isdrawing = True
        raw_data_map, rx_len = self.controller.get_event()
        if not raw_data_map:
            self.state.isdrawing = False
            return

        s = self.state
        s.nevents += 1
        s.lastsize = rx_len

        # RESTORED: Logic to calculate event rate (Hz) and throughput (MB/s) periodically
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
                self.controller.adjustclocks(board_idx, nbadA, nbadB, nbadC, nbadD, nbadS)
            elif (nbadA + nbadB + nbadC + nbadD + nbadS) > 0:
                print(f"Bad clock/strobe detected on board {board_idx}. Triggering PLL reset.")
                self.controller.pllreset(board_idx)

        self.plot_manager.update_plots(self.xydata, self.xydatainterleaved)

        if self.recorder.is_recording:
            lines_vis = [line.isVisible() for line in self.plot_manager.lines]
            self.recorder.record_event(self.xydata, self.plot_manager.otherlines['vline'].value(), lines_vis)

        # RESTORED: Full status message formatting
        now = time.time()
        dt = now - self.last_time + 1e-9
        self.last_time = now
        self.fps = 1.0 / dt if self.fps is None else self.fps * 0.9 + (1.0 / dt) * 0.1

        # Calculate effective sample rate based on current mode
        sradjust = 1e9
        if s.dointerleaved[s.activeboard]:
            sradjust = 2e9
        elif s.dotwochannel:
            sradjust = 0.5e9
        effective_sr = s.samplerate * sradjust / (s.downsamplefactor if not s.highresval else 1)

        # Build the complete status string
        status_text = (
            f"{format_freq(effective_sr, 'S/s')}, "
            f"{self.fps:.2f} fps, "
            f"{s.nevents} events, "
            f"{s.lastrate:.2f} Hz, "
            f"{(s.lastrate * s.lastsize / 1e6):.2f} MB/s"
        )
        self.ui.statusBar.showMessage(status_text)
        self.state.isdrawing = False

    def update_measurements_display(self):
        """Slow timer callback to update text-based measurements."""
        the_str = ""
        if self.recorder.is_recording:
            the_str += f"Recording to file {self.recorder.file_handle.name}\n"

        if self.state.dodrawing:
            if self.ui.persistavgCheck.isChecked() and self.plot_manager.average_line.isVisible():
                target_x = self.plot_manager.average_line.xData
                target_y = self.plot_manager.average_line.yData
                source_str = "from average"
            else:
                target_x = self.xydata[self.state.activexychannel][0]
                target_y = self.xydata[self.state.activexychannel][1]
                source_str = ""

            the_str += f"\nMeasurements {source_str} for board {self.state.activeboard} ch {self.state.selectedchannel}:\n"

            vline_val = self.plot_manager.otherlines['vline'].value()
            measurements = self.processor.calculate_measurements(target_x, target_y, vline_val)

            # Format results for display
            if self.ui.actionMean.isChecked(): the_str += f"Mean: {measurements.get('Mean', 'N/A')}\n"
            if self.ui.actionRMS.isChecked(): the_str += f"RMS: {measurements.get('RMS', 'N/A')}\n"
            if self.ui.actionVpp.isChecked(): the_str += f"Vpp: {measurements.get('Vpp', 'N/A')}\n"
            if self.ui.actionFreq.isChecked(): the_str += f"Freq: {measurements.get('Freq', 'N/A')}\n"
            if self.ui.actionRisetime.isChecked(): the_str += f"Risetime: {measurements.get('Risetime', 'N/A')}\n"

        self.ui.textBrowser.setText(the_str)

    def allocate_xy_data(self):
        """Creates or re-sizes the numpy arrays for storing waveform data."""
        s = self.state
        num_ch = s.num_chan_per_board * s.num_board
        shape = (num_ch, 2, (2 if s.dotwochannel else 4) * 10 * s.expect_samples)
        ishape = (num_ch, 2, 2 * 4 * 10 * s.expect_samples)

        if not hasattr(self, 'xydata') or self.xydata.shape != shape:
            self.xydata = np.zeros(shape, dtype=float)
            self.xydatainterleaved = np.zeros(ishape, dtype=float)
            self.time_changed()  # Initialize x-axis values

    def time_changed(self):
        """Updates plot manager and recalculates x-axis arrays on timebase change."""
        self.plot_manager.time_changed()
        self.ui.timebaseBox.setText(f"2^{self.state.downsample}")
        s = self.state
        x_step1 = (2 if s.dotwochannel else 1) * s.downsamplefactor / s.nsunits / s.samplerate
        x_step2 = 0.5 * s.downsamplefactor / s.nsunits / s.samplerate
        for c in range(s.num_chan_per_board * s.num_board):
            if hasattr(self, 'xydata'):
                self.xydata[c][0] = np.arange(self.xydata.shape[2]) * x_step1
            if hasattr(self, 'xydatainterleaved'):
                self.xydatainterleaved[c][0] = np.arange(self.xydatainterleaved.shape[2]) * x_step2

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

    def select_channel(self):
        """Called when board or channel selector is changed."""
        self.state.activeboard = self.ui.boardBox.value()
        self.state.selectedchannel = self.ui.chanBox.value()
        self._update_channel_mode_ui()

        # Update UI widgets to reflect the state of the newly selected channel
        s = self.state
        self.ui.gainBox.setValue(s.gain[s.activexychannel])
        self.ui.offsetBox.setValue(s.offset[s.activexychannel])
        self.ui.acdcCheck.setChecked(s.acdc[s.activexychannel])
        self.ui.ohmCheck.setChecked(s.mohm[s.activexychannel])
        self.ui.attCheck.setChecked(s.att[s.activexychannel])
        self.ui.tenxCheck.setChecked(s.tenx[s.activexychannel] == 10)
        self.ui.chanonCheck.setChecked(self.plot_manager.lines[s.activexychannel].isVisible())
        self.ui.tadBox.setValue(s.tad[s.activeboard])

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

    def on_vline_dragged(self, value):
        """
        Handles dragging the vertical trigger line.
        If zoomed in, it pans the view and manually constrains the drag to the window.
        Otherwise, it adjusts the trigger position.
        """
        s = self.state

        if s.downsamplezoom > 1:  # Panning mode when zoomed in
            # --- NEW CONSTRAINT LOGIC ---
            # Manually clamp the line's proposed position to the visible x-axis range.
            value = max(s.min_x, min(value, s.max_x))

            # --- PANNING LOGIC ---
            # Calculate how far the line was dragged from its last known central position
            drag_delta = value - self.plot_manager.current_vline_pos

            # Shift the view range by that amount
            s.min_x -= drag_delta
            s.max_x -= drag_delta
            self.plot_manager.plot.setRange(xRange=(s.min_x, s.max_x), padding=0.00)

            # Snap the trigger line back to its original (central) position within the new view
            self.plot_manager.draw_trigger_lines()

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

    def trigger_pos_changed(self, value):
        self.state.triggerpos = int(self.state.expect_samples * value / 10000.)
        self.controller.send_trigger_info_all()
        self.plot_manager.draw_trigger_lines()

    def time_fast(self):
        self.state.downsample -= 1
        self.controller.tell_downsample_all(self.state.downsample)

        is_zoomed = self.state.downsample < 0

        if is_zoomed:
            self.state.downsamplezoom = pow(2, -self.state.downsample)
        else:
            self.state.downsamplezoom = 1

        self.ui.thresholdPos.setEnabled(not is_zoomed)
        self.time_changed()

    def time_slow(self):
        self.state.downsample += 1
        self.controller.tell_downsample_all(self.state.downsample)

        is_zoomed = self.state.downsample < 0

        if is_zoomed:
            self.state.downsamplezoom = pow(2, -self.state.downsample)
        else:
            self.state.downsamplezoom = 1

        self.ui.thresholdPos.setEnabled(not is_zoomed)
        self.time_changed()

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
        reply = QMessageBox.question(self, 'Confirmation', f'Update firmware on board {board}?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.No: return
        self.dostartstop()  # Pause
        success, message = self.controller.update_firmware(board)
        QMessageBox.information(self, "Firmware Update", message)
        if success: self.ui.runButton.setEnabled(False)

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
        Updates the appearance of the persistence average line based on UI settings.
        This is called when the 'Channel On' or persistence checkboxes change.
        """
        self.plot_manager.set_average_line_pen()
        # The average line is only visible if both its own box and the main channel box are checked
        self.plot_manager.average_line.setVisible(
            self.ui.persistavgCheck.isChecked() and self.ui.chanonCheck.isChecked()
        )

    # #########################################################################
    # ## Slot Implementations (Callbacks for UI events)
    # #########################################################################

    def fft_clicked(self):
        """Toggles the FFT window."""
        self.state.dofft = self.ui.fftCheck.isChecked()
        if self.state.dofft:
            if self.fftui is None or not self.fftui.isVisible():
                self.fftui = FFTWindow()
                self.fftui.setWindowTitle(
                    f'Haasoscope Pro FFT of board {self.state.activeboard} channel {self.state.selectedchannel}')
                self.fftui.show()
        else:
            if self.fftui:
                self.fftui.close()

    def twochan_changed(self):
        """Switches between single and dual channel mode."""
        self.state.dotwochannel = self.ui.twochanCheck.isChecked()

        # Reconfigure hardware for the new mode
        for i in range(self.state.num_board):
            setupboard(self.controller.usbs[i], self.state.dopattern, self.state.dotwochannel, self.state.dooverrange,
                       self.state.basevoltage == 200)
            self.controller.tell_downsample(self.controller.usbs[i], self.state.downsample)

        self.allocate_xy_data()
        self.time_changed()

        # Call the centralized UI update function
        self._update_channel_mode_ui()

        # Update everything else for the currently selected channel
        self.select_channel()

    def gain_changed(self):
        """Handles changes to the gain slider."""
        s = self.state
        s.gain[s.activexychannel] = self.ui.gainBox.value()
        self.controller.set_channel_gain(s.activeboard, s.selectedchannel, s.gain[s.activexychannel])
        # Also update the coupled board in oversampling mode
        if s.dooversample[s.activeboard] and s.activeboard % 2 == 0:
            self.controller.set_channel_gain(s.activeboard + 1, s.selectedchannel, s.gain[s.activexychannel])
            s.gain[s.activexychannel + s.num_chan_per_board] = s.gain[s.activexychannel]

        # Update V/div text
        db = s.gain[s.activexychannel]
        v2 = (s.basevoltage / 1000.) * s.tenx[s.activexychannel] / pow(10, db / 20.)
        if s.dooversample[s.activeboard]: v2 *= 2.0
        if not s.mohm[s.activexychannel]: v2 /= 2.0

        oldvperd = s.VperD[s.activexychannel]
        s.VperD[s.activexychannel] = v2
        if s.dooversample[s.activeboard] and s.activeboard % 2 == 0:
            s.VperD[s.activexychannel + s.num_chan_per_board] = v2

        # Adjust offset to maintain same voltage offset
        self.ui.offsetBox.setValue(int(self.ui.offsetBox.value() * oldvperd / v2))

        v2_rounded = round(1002 * v2, 0)  # Rounding trick for clean numbers
        if v2_rounded > 50: v2_rounded = round(v2_rounded, -1)
        self.ui.VperD.setText(f"{v2_rounded:.1f} mV/div")
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
        board = self.state.activeboard
        self.state.doextsmatrig[board] = bool(checked)
        self.controller.set_extsmatrig(board, bool(checked))
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

            # Convert the sub-sample shift into a hardware TAD value
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
            print("Error: Please select the even-numbered board of a pair (e.g., 0, 2).")
            return

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

        # Calculate mean and standard deviation
        mean1, std1 = np.mean(yc1), np.std(yc1)
        mean2, std2 = np.mean(yc2), np.std(yc2)

        # Update state with the correction factors (these are used by the DataProcessor)
        s.extrigboardmeancorrection[s.activeboard] += mean2 - mean1
        if std2 > 0:
            s.extrigboardstdcorrection[s.activeboard] *= std1 / std2

        print(
            f"Calculated corrections: Mean={s.extrigboardmeancorrection[s.activeboard]:.4f}, Std={s.extrigboardstdcorrection[s.activeboard]:.4f}")