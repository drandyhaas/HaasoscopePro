import sys
import os
import time
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets, loadUiType
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtWidgets import QMessageBox
import ftd2xx  # For catching hardware exceptions
import matplotlib.cm as cm

# --- Imports from refactored modules ---
from state import ScopeState
from hardware import HardwareManager
from processing import DataManager
from network import SocketManager
from utilsfuncs import calculate_risetime, find_fundamental_frequency_scipy, format_freq

# --- Imports from actual hardware libraries ---
#from usbs import get_usbs
from board import gettemps

# from FFTWindow import FFTWindow # Assuming this UI file exists

# Load the UI template
WindowTemplate, TemplateBaseClass = loadUiType("HaasoscopePro.ui")


class MainWindow(TemplateBaseClass):
    """
    Main application window (UI Controller). This version is complete and hardware-ready.
    """

    def __init__(self, usbs):
        super().__init__()
        self.ui = WindowTemplate()
        self.ui.setupUi(self)
        self.setWindowTitle("Haasoscope Pro (Refactored)")

        # Initialize manager classes
        self.state = ScopeState(num_boards=len(usbs))
        self.hardware = HardwareManager(usbs)
        self.data_manager = DataManager(self.state)
        self.socket_manager = SocketManager(self)

        # UI state variables
        self.processed_data = {}
        self.lines = []
        self.line_pens = []
        self.fft_window = None
        self.output_file = None
        self.last_status_update = time.time()

        self._setup_ui()
        self._connect_signals()
        self._initialize_scope()

    def _setup_ui(self):
        """Initializes UI elements, plots, and channels."""
        self.ui.statusBar.showMessage(f"{self.state.num_boards} boards connected!")
        self.ui.boardBox.setMaximum(self.state.num_boards - 1 if self.state.num_boards > 0 else 0)
        self.ui.plot.setBackground(QColor('black'))
        self.ui.plot.getAxis("left").setTickSpacing(1, 0.1)
        self.ui.plot.setLabel('left', "Voltage (divisions)")
        self.grid()

        # Setup plot lines for each channel
        colors = cm.rainbow(np.linspace(1.0, 0.1, self.state.total_channels or 1))
        for i in range(self.state.total_channels):
            color = QColor.fromRgbF(*colors[i])
            pen = pg.mkPen(color=color)
            line = self.ui.plot.plot(pen=pen, name=f"Channel {i}")
            line.curve.setClickable(True)
            line.curve.sigClicked.connect(self._on_line_clicked)
            self.lines.append(line)
            self.line_pens.append(pen)

        # Setup trigger lines
        self.trigger_v_line = self.ui.plot.plot(pen=pg.mkPen(color="w", style=QtCore.Qt.DashLine))
        self.trigger_h_line = self.ui.plot.plot(pen=pg.mkPen(color="w", style=QtCore.Qt.DashLine))

        # Timers
        self.plot_timer = QtCore.QTimer()
        self.plot_timer.timeout.connect(self.update_plot)
        self.text_timer = QtCore.QTimer()
        self.text_timer.timeout.connect(self.update_text_display)

    def _connect_signals(self):
        """Connects all UI element signals to their corresponding slots."""
        # --- Run Control ---
        self.ui.runButton.clicked.connect(self.toggle_run_stop)
        self.ui.rollingButton.clicked.connect(self._on_rolling_toggle)
        self.ui.singleButton.clicked.connect(self._on_single_toggle)
        self.ui.drawingCheck.clicked.connect(self._on_drawing_toggle)
        self.ui.persistCheck.clicked.connect(self._on_persist_toggle)

        # --- Timebase ---
        self.ui.timeslowButton.clicked.connect(self._on_time_slow)
        self.ui.timefastButton.clicked.connect(self._on_time_fast)
        self.ui.depthBox.valueChanged.connect(self._on_depth_changed)
        self.ui.highresCheck.stateChanged.connect(self._on_high_res_changed)

        # --- Triggering ---
        self.ui.threshold.valueChanged.connect(self._on_trigger_level_changed)
        self.ui.thresholdDelta.valueChanged.connect(self._on_trigger_delta_changed)
        self.ui.thresholdPos.valueChanged.connect(self._on_trigger_pos_changed)
        self.ui.trigchan_comboBox.currentIndexChanged.connect(self._on_trigger_chan_changed)
        self.ui.risingfalling_comboBox.currentIndexChanged.connect(self._on_trigger_edge_changed)
        self.ui.totBox.valueChanged.connect(self._on_tot_changed)
        self.ui.exttrigCheck.stateChanged.connect(self._on_ext_trig_changed)
        self.ui.extsmatrigCheck.stateChanged.connect(self._on_ext_sma_trig_changed)

        # --- Board & Channel Select ---
        self.ui.boardBox.valueChanged.connect(self._on_board_changed)
        self.ui.chanBox.valueChanged.connect(self._on_channel_changed)

        # --- Channel Settings ---
        self.ui.chanonCheck.stateChanged.connect(self._on_chan_on_off)
        self.ui.gainBox.valueChanged.connect(self._on_gain_changed)
        self.ui.offsetBox.valueChanged.connect(self._on_offset_changed)
        self.ui.acdcCheck.stateChanged.connect(self._on_acdc_changed)
        self.ui.ohmCheck.stateChanged.connect(self._on_impedance_changed)
        self.ui.attCheck.stateChanged.connect(self._on_attenuator_changed)
        self.ui.tenxCheck.stateChanged.connect(self._on_tenx_probe_changed)
        self.ui.twochanCheck.clicked.connect(self._on_two_chan_toggle)
        self.ui.oversampCheck.stateChanged.connect(self._on_oversample_changed)
        self.ui.interleavedCheck.stateChanged.connect(self._on_interleave_changed)

        # --- Advanced Controls & Analysis ---
        self.ui.pllresetButton.clicked.connect(lambda: self.hardware.pll_reset(self.state.active_board, self.state))
        self.ui.adfresetButton.clicked.connect(lambda: self.hardware.adf_reset(self.state.active_board, self.state))
        self.ui.tadBox.valueChanged.connect(self._on_tad_changed)
        self.ui.ToffBox.valueChanged.connect(lambda v: setattr(self.state, 'toff', v))
        self.ui.Auxout_comboBox.currentIndexChanged.connect(self._on_aux_out_changed)
        self.ui.fftCheck.clicked.connect(self._on_fft_toggle)
        self.ui.resampBox.valueChanged.connect(lambda v: setattr(self.state, 'resample_factor', v))
        self.ui.fwfBox.valueChanged.connect(lambda v: setattr(self.state, 'fit_width_fraction', v / 100.0))
        for i in range(5):
            getattr(self.ui, f"upposButton{i}").clicked.connect(lambda _, i=i: self._on_phase_up(i))
            getattr(self.ui, f"downposButton{i}").clicked.connect(lambda _, i=i: self._on_phase_down(i))

        # --- Display ---
        self.ui.gridCheck.stateChanged.connect(self.grid)
        self.ui.markerCheck.stateChanged.connect(self.marker)

        # --- Menu Actions ---
        self.ui.actionRecord.triggered.connect(self.toggle_recording)
        self.ui.actionDo_autocalibration.triggered.connect(self.autocalibration)
        self.ui.actionUpdate_firmware.triggered.connect(self.update_firmware)
        self.ui.actionAbout.triggered.connect(self.about)

    def _initialize_scope(self):
        """Sets up the initial state of the oscilloscope."""
        if not self.hardware.usbs:
            self.ui.runButton.setEnabled(False)
            return

        for board_idx in range(self.state.num_boards):
            self.hardware.setup_board(board_idx, self.state)
        if self.state.num_boards > 1:
            self.hardware.use_external_triggers(self.state)

        self._on_rolling_toggle()  # Set initial state
        self._update_time_settings()
        self._update_active_channel_controls()
        self.socket_manager.start()
        self.toggle_run_stop()  # Start running

    def update_plot(self):
        """Main loop for fetching data and updating the plot."""
        if self.socket_manager.is_sending(): return

        event_data = self.hardware.get_event(self.state)
        if not event_data: return

        self.state.event_count += 1
        self.processed_data = self.data_manager.process_event_data(event_data)

        for board_idx in event_data.keys():
            if self.state.pll_just_reset[board_idx] > -10:
                is_done = self.hardware.adjust_clocks(board_idx, self.data_manager.nbad_counts, self.state)
                if is_done:
                    self.state.is_drawing = True
                    self._on_depth_changed(self.ui.depthBox.value())

        if self.state.is_recording:
            self._record_event()

        if self.state.is_drawing:
            for ch_index, data in self.processed_data.items():
                line = self.lines[ch_index]
                if line.isVisible():
                    if self.state.resample_factor > 1:
                        from scipy.signal import resample
                        new_len = int(len(data['x']) * self.state.resample_factor)
                        y_new, x_new = resample(data['y'], new_len, t=data['x'])
                        line.setData(x_new, y_new)
                    else:
                        line.setData(data['x'], data['y'])

            if self.state.is_fft_enabled and self.fft_window:
                self._update_fft_plot()

        self._update_status_bar()
        if self.state.is_single_shot:
            self.state.is_single_shot = False
            self.ui.singleButton.setChecked(False)
            self.toggle_run_stop()

    def update_text_display(self):
        """Updates the text browser with measurements once per second."""
        if not self.processed_data or not self.state.is_drawing:
            self.ui.textBrowser.clear()
            return

        s = self.state
        active_idx = s.active_channel_index
        if active_idx not in self.processed_data:
            self.ui.textBrowser.clear()
            return

        wfm = self.processed_data[active_idx]
        y_data, x_data = wfm['y'], wfm['x']

        text = f"Measurements for Board {s.active_board} Chan {s.selected_channel}:\n"

        # --- ADDED CHECKS FOR EACH MEASUREMENT ---

        # Check if any of the basic V/mV measurements are enabled
        v_per_div = s.get_volts_per_div(s.active_board, s.selected_channel)
        if any([self.ui.actionMean.isChecked(), self.ui.actionRMS.isChecked(),
                self.ui.actionMaximum.isChecked(), self.ui.actionMinimum.isChecked(),
                self.ui.actionVpp.isChecked()]):

            measurements = self.data_manager.calculate_measurements(y_data, v_per_div)

            if self.ui.actionMean.isChecked():
                text += f"Mean: {measurements['Mean'] * 1000:.3f} mV\n"
            if self.ui.actionRMS.isChecked():
                text += f"RMS: {measurements['RMS'] * 1000:.3f} mV\n"
            if self.ui.actionMaximum.isChecked():
                text += f"Max: {measurements['Max'] * 1000:.3f} mV\n"
            if self.ui.actionMinimum.isChecked():
                text += f"Min: {measurements['Min'] * 1000:.3f} mV\n"
            if self.ui.actionVpp.isChecked():
                text += f"Vpp: {measurements['Vpp'] * 1000:.3f} mV\n"

        if self.ui.actionRisetime.isChecked():
            _, trig_x = s.get_trigger_line_positions()
            fit_width = (s.max_x - s.min_x) * s.fit_width_fraction
            rt, rt_err = calculate_risetime(x_data, y_data, trig_x, fit_width)
            if rt is not None:
                text += f"Risetime: {rt:.2f} \u00B1 {rt_err:.2f} {s.x_units}\n"

        if self.ui.actionFreq.isChecked():
            sampling_rate = (s.samplerate_ghz * 1e9) / s.downsample_factor
            if not s.is_two_channel_mode:
                sampling_rate *= 2
            freq = find_fundamental_frequency_scipy(y_data, sampling_rate)
            text += f"Freq: {format_freq(freq)}\n"

        text += f"\n{gettemps(self.hardware.usbs[s.active_board])}"
        self.ui.textBrowser.setText(text)

    def _update_status_bar(self):
        now = time.time()
        if now - self.last_status_update < 0.5: return
        self.last_status_update = now

        rate, size = self.hardware.last_rate, self.hardware.last_size
        fps = self.hardware.rate_calc_events / (
                    now - self.hardware.rate_calc_time + 1e-9) if self.hardware.rate_calc_events > 0 else 0
        msg = f"{fps:.1f} FPS | Events: {self.state.event_count} | Rate: {rate:.1f} Hz | Data: {rate * size / 1e6:.2f} MB/s"
        self.ui.statusBar.showMessage(msg)

    def _update_time_settings(self):
        self.state.update_x_axis_ranges()
        for i in range(self.state.num_boards):
            self.hardware.update_downsample(i, self.state)
        self.ui.plot.setRange(xRange=self.state.get_x_range(), padding=0.0)
        self.ui.plot.setLabel('bottom', f"Time ({self.state.x_units})")
        self.ui.timebaseBox.setText(f"2^{self.state.downsample}")
        self._draw_trigger_lines()
        for i in range(self.state.num_boards):
            self.hardware.send_trigger_info(i, self.state)

    def _draw_trigger_lines(self):
        h_pos, v_pos = self.state.get_trigger_line_positions()
        self.trigger_h_line.setData([self.state.min_x, self.state.max_x], [h_pos, h_pos])
        self.trigger_v_line.setData([v_pos, v_pos], self.state.get_y_range())

    def _update_active_channel_controls(self):
        s, b, c = self.state, self.state.active_board, self.state.selected_channel
        active_idx = s.active_channel_index

        # Temporarily disconnect signals to prevent feedback loops
        self.ui.gainBox.valueChanged.disconnect()
        self.ui.offsetBox.valueChanged.disconnect()
        self.ui.gainBox.setValue(s.gains[active_idx])
        self.ui.offsetBox.setValue(s.offsets[active_idx])
        self.ui.gainBox.valueChanged.connect(self._on_gain_changed)
        self.ui.offsetBox.valueChanged.connect(self._on_offset_changed)

        self.ui.acdcCheck.setChecked(s.is_ac_coupled_list[active_idx])
        self.ui.ohmCheck.setChecked(s.is_high_impedance_list[active_idx])
        self.ui.attCheck.setChecked(s.is_attenuator_on_list[active_idx])
        self.ui.tenxCheck.setChecked(s.probe_attenuation[active_idx] == 10)
        self.ui.chanonCheck.setChecked(self.lines[active_idx].isVisible())
        self.ui.trigchan_comboBox.setCurrentIndex(s.trigger_channels[b])

        v_per_div = s.get_volts_per_div(b, c)
        v_offset = s.get_voltage_offset(b, c)
        self.ui.VperD.setText(f"{v_per_div * 1000:.0f} mV/div")
        self.ui.Voff.setText(f"{v_offset * 1000:.0f} mV")

        palette = self.ui.chanColor.palette()
        palette.setColor(QPalette.Base, self.line_pens[active_idx].color())
        self.ui.chanColor.setPalette(palette)

    # --- Slot Implementations --- (Full list)

    def toggle_run_stop(self):
        self.state.is_paused = not self.state.is_paused
        self.ui.runButton.setChecked(not self.state.is_paused)
        if self.state.is_paused:
            self.plot_timer.stop()
            self.text_timer.stop()
        else:
            self.plot_timer.start(0)
            self.text_timer.start(1000)

    def _on_time_slow(self):
        if self.state.downsample < 36: self.state.downsample += 1
        self._update_time_settings()

    def _on_time_fast(self):
        if self.state.downsample > -10: self.state.downsample -= 1
        self._update_time_settings()

    def _on_depth_changed(self, value):
        self.state.expect_samples = value
        self._on_trigger_pos_changed(self.ui.thresholdPos.value())
        self._update_time_settings()

    def _on_high_res_changed(self, qt_state):
        self.state.is_high_res = (qt_state == QtCore.Qt.Checked)
        for i in range(self.state.num_boards):
            self.hardware.update_downsample(i, self.state)

    def _on_trigger_level_changed(self, value):
        self.state.trigger_level = value
        for i in range(self.state.num_boards): self.hardware.send_trigger_info(i, self.state)
        self._draw_trigger_lines()

    def _on_trigger_delta_changed(self, value):
        self.state.trigger_delta = value
        for i in range(self.state.num_boards): self.hardware.send_trigger_info(i, self.state)

    def _on_trigger_pos_changed(self, value):
        self.state.trigger_pos_percent = value
        for i in range(self.state.num_boards): self.hardware.send_trigger_info(i, self.state)
        self._draw_trigger_lines()

    def _on_trigger_chan_changed(self, index):
        self.state.trigger_channels[self.state.active_board] = index
        self.hardware.send_trigger_info(self.state.active_board, self.state)

    def _on_trigger_edge_changed(self, index):
        self.state.trigger_type = 2 if index == 1 else 1

    def _on_tot_changed(self, value):
        self.state.trigger_time_thresh = value
        for i in range(self.state.num_boards): self.hardware.send_trigger_info(i, self.state)

    def _on_ext_trig_changed(self, qt_state):
        is_on = qt_state == QtCore.Qt.Checked
        b = self.state.active_board
        self.state.is_ext_triggered[b] = is_on
        self.ui.extsmatrigCheck.setEnabled(not is_on)
        self.hardware.set_rolling(b, self.state.is_rolling, is_on)
        self.hardware.send_trigger_info(b, self.state)
        if is_on:
            self.hardware.do_ext_trig_echo = [False] * self.state.num_boards
            self.hardware.do_ext_trig_echo[b] = True
        else:
            self.hardware.do_ext_trig_echo[b] = False

    def _on_ext_sma_trig_changed(self, qt_state):
        is_on = qt_state == QtCore.Qt.Checked
        self.state.is_ext_sma_triggered[self.state.active_board] = is_on
        self.ui.exttrigCheck.setEnabled(not is_on)

    def _on_board_changed(self, value):
        self.state.active_board = value
        self._update_active_channel_controls()

    def _on_channel_changed(self, value):
        self.state.selected_channel = value
        self._update_active_channel_controls()

    def _on_gain_changed(self, value):
        b, c = self.state.active_board, self.state.selected_channel
        old_v_per_div = self.state.get_volts_per_div(b, c)
        self.state.set_gain(b, c, value)
        new_v_per_div = self.state.get_volts_per_div(b, c)

        if old_v_per_div > 0 and new_v_per_div > 0:
            new_offset = int(self.ui.offsetBox.value() * old_v_per_div / new_v_per_div)
            self.ui.offsetBox.setValue(new_offset)

        self.hardware.set_gain(b, c, value, self.state.is_oversampling_list[b])
        self._update_active_channel_controls()

    def _on_offset_changed(self, value):
        b, c = self.state.active_board, self.state.selected_channel
        self.state.offsets[self.state.active_channel_index] = value
        self.hardware.set_offset(b, c, value, self.state)
        self._update_active_channel_controls()

    def _on_acdc_changed(self, qt_state):
        is_ac = qt_state == QtCore.Qt.Checked
        idx, b, c = self.state.active_channel_index, self.state.active_board, self.state.selected_channel
        self.state.is_ac_coupled_list[idx] = is_ac
        self.hardware.set_acdc(b, c, is_ac, self.state.is_oversampling_list[b])
        self._on_offset_changed(self.ui.offsetBox.value())

    def _on_impedance_changed(self, qt_state):
        is_high_z = qt_state == QtCore.Qt.Checked
        idx, b, c = self.state.active_channel_index, self.state.active_board, self.state.selected_channel
        self.state.is_high_impedance_list[idx] = is_high_z
        self.hardware.set_impedance(b, c, is_high_z, self.state.is_oversampling_list[b])

    def _on_attenuator_changed(self, qt_state):
        is_on = qt_state == QtCore.Qt.Checked
        idx, b, c = self.state.active_channel_index, self.state.active_board, self.state.selected_channel
        self.state.is_attenuator_on_list[idx] = is_on
        self.hardware.set_attenuator(b, c, is_on, self.state.is_oversampling_list[b])

    def _on_tenx_probe_changed(self, qt_state):
        is_10x = qt_state == QtCore.Qt.Checked
        idx = self.state.active_channel_index
        self.state.probe_attenuation[idx] = 10 if is_10x else 1
        self._on_gain_changed(self.ui.gainBox.value())

    def _on_two_chan_toggle(self):
        self.state.is_two_channel_mode = self.ui.twochanCheck.isChecked()
        for b in range(self.state.num_boards):
            self.hardware.set_channel_mode(b, self.state)
        self._update_time_settings()
        self.ui.chanBox.setMaximum(1 if self.state.is_two_channel_mode else 0)
        for i in range(self.state.num_boards):
            self.lines[i * 2 + 1].setVisible(self.state.is_two_channel_mode)

    def _on_oversample_changed(self, qt_state):
        is_on = qt_state == QtCore.Qt.Checked
        b = self.state.active_board
        if b % 2 != 0: return
        self.state.is_oversampling_list[b] = is_on
        self.state.is_oversampling_list[b + 1] = is_on
        self.hardware.set_oversampling(b, is_on)
        self.ui.interleavedCheck.setEnabled(is_on)
        self.ui.twochanCheck.setEnabled(not is_on)
        self._on_gain_changed(self.ui.gainBox.value())

    def _on_interleave_changed(self, qt_state):
        is_on = qt_state == QtCore.Qt.Checked
        b = self.state.active_board
        if b % 2 != 0: return
        self.state.is_interleaved_list[b] = is_on
        self.state.is_interleaved_list[b + 1] = is_on
        self.lines[(b + 1) * 2].setVisible(not is_on)
        self.lines[(b + 1) * 2 + 1].setVisible(not is_on)
        self._update_time_settings()

    def _on_chan_on_off(self, qt_state):
        is_on = qt_state == QtCore.Qt.Checked
        self.lines[self.state.active_channel_index].setVisible(is_on)

    def _on_drawing_toggle(self):
        self.state.is_drawing = self.ui.drawingCheck.isChecked()

    def _on_persist_toggle(self):
        self.state.is_persist = self.ui.persistCheck.isChecked()

    def _on_rolling_toggle(self):
        self.state.is_rolling = not self.state.is_rolling
        self.ui.rollingButton.setChecked(self.state.is_rolling)
        self.ui.rollingButton.setText("Auto" if self.state.is_rolling else "Normal")
        for i in range(self.state.num_boards):
            self.hardware.set_rolling(i, self.state.is_rolling, self.state.is_ext_triggered[i])

    def _on_single_toggle(self):
        self.state.is_single_shot = self.ui.singleButton.isChecked()
        if self.state.is_single_shot and self.state.is_paused:
            self.toggle_run_stop()

    def _on_tad_changed(self, value):
        b = self.state.active_board
        self.state.tad_values[b] = value
        self.hardware.set_tad(b, value)

    def _on_aux_out_changed(self, index):
        self.hardware.set_aux_out(self.state.active_board, index)

    def _on_phase_up(self, pll_output_num):
        pllnum = self.ui.pllBox.value()
        self.hardware.dophase(self.state.active_board, pll_output_num, 1, pllnum, self.state)

    def _on_phase_down(self, pll_output_num):
        pllnum = self.ui.pllBox.value()
        self.hardware.dophase(self.state.active_board, pll_output_num, 0, pllnum, self.state)

    def _on_fft_toggle(self):
        self.state.is_fft_enabled = self.ui.fftCheck.isChecked()
        if self.state.is_fft_enabled:
            print("FFT Window would open here.")
        elif self.fft_window:
            self.fft_window.close()
            self.fft_window = None

    def _update_fft_plot(self):
        pass

    def grid(self):
        show = self.ui.gridCheck.isChecked()
        self.ui.plot.showGrid(x=show, y=show)

    def marker(self):
        show = self.ui.markerCheck.isChecked()
        for i, line in enumerate(self.lines):
            if show:
                line.setSymbol("o");
                line.setSymbolSize(3)
                line.setSymbolPen(self.line_pens[i].color());
                line.setSymbolBrush(self.line_pens[i].color())
            else:
                line.setSymbol(None)

    def about(self):
        QMessageBox.about(self, "About Haasoscope Pro",
                          "Version 27.01 (Refactored)\nA PyQt5 application by DrAndyHaas.")

    def toggle_recording(self):
        self.state.is_recording = not self.state.is_recording
        if self.state.is_recording:
            try:
                fname = "HaasoscopePro_out_" + time.strftime("%Y%m%d-%H%M%S") + ".csv"
                self.output_file = open(fname, "wt")
                header = "Event #,Time (s),Channel,Trigger time (ns),Sample period (ns),# samples"
                num_samples = 20 * self.state.expect_samples if self.state.is_two_channel_mode else 40 * self.state.expect_samples
                header += "".join([f",Sample {i}" for i in range(num_samples)])
                self.output_file.write(header + "\n")
                self.ui.actionRecord.setText("Stop Recording")
            except IOError as e:
                QMessageBox.critical(self, "Error", f"Could not open file for writing: {e}")
                self.state.is_recording = False
        else:
            if self.output_file:
                self.output_file.close();
                self.output_file = None
            self.ui.actionRecord.setText("Record to File")

    def _record_event(self):
        if not self.output_file or not self.processed_data: return
        s = self.state
        event_time_str = str(time.time())
        _, trigger_time_ns = s.get_trigger_line_positions()
        sample_period_ns = s.downsample_factor / s.samplerate_ghz
        if not s.is_two_channel_mode: sample_period_ns /= 2

        for ch_idx, wfm_data in self.processed_data.items():
            if self.lines[ch_idx].isVisible():
                num_samples = len(wfm_data['y'])
                line = f"{s.event_count},{event_time_str},{ch_idx},{trigger_time_ns},{sample_period_ns},{num_samples},"
                self.output_file.write(line)
                wfm_data['y'].tofile(self.output_file, ",", format="%.4f")
                self.output_file.write("\n")

    def autocalibration(self):
        QMessageBox.information(self, "Autocalibration", "Autocalibration routine would run here.")

    def update_firmware(self):
        QMessageBox.information(self, "Firmware Update", "Firmware update routine would run here.")

    def _on_line_clicked(self, curve):
        for i, line in enumerate(self.lines):
            if curve is line.curve:
                board = i // self.state.num_chans_per_board
                channel = i % self.state.num_chans_per_board
                self.ui.boardBox.setValue(board)
                self.ui.chanBox.setValue(channel)
                break

    def closeEvent(self, event):
        """Handles application shutdown."""
        self.socket_manager.stop()
        if self.plot_timer.isActive(): self.plot_timer.stop()
        if self.text_timer.isActive(): self.text_timer.stop()
        if self.state.is_recording and self.output_file: self.output_file.close()
        if self.fft_window: self.fft_window.close()
        self.hardware.cleanup()
        event.accept()


