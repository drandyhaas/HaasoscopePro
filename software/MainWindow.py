import os.path
import sys
import time
import struct
import threading
import warnings

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets, loadUiType
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtWidgets import QMessageBox
from scipy.optimize import curve_fit
from scipy.signal import resample
import matplotlib.cm as cm

from usbs import *
from board import *
from SCPIsocket import hspro_socket
from FFTWindow import *

# --- Constants ---
# Using constants for magic numbers improves readability and maintainability.
DEFAULT_EXPECT_SAMPLES = 100
DEFAULT_EXPECT_SAMPLES_EXTRA = 5
DEFAULT_SAMPLERATE_GHZ = 3.2
NUM_RECORD_EVENTS_PER_FILE = 1000
PLL_ADJUSTMENT_STEPS = 12

# Define main window class from template
WindowTemplate, TemplateBaseClass = loadUiType("HaasoscopePro.ui")


class MainWindow(TemplateBaseClass):
    """
    Main application window for the Haasoscope Pro.

    This class manages the user interface, handles hardware communication with
    the oscilloscope boards, processes incoming data, and updates the plots.
    """

    def __init__(self, usbs):
        super().__init__()
        self.usbs = usbs
        self.num_board = len(usbs)

        self.ui = WindowTemplate()
        self.ui.setupUi(self)
        self.setWindowTitle('Haasoscope Pro Qt')

        self._initialize_state()
        self._connect_ui_signals()

        if not self._initialize_hardware():
            # Initialization failed, so we should exit gracefully.
            cleanup_and_exit(self.usbs, 2)

        self.show()

    def _initialize_state(self):
        """Initializes all state variables for the application."""
        self.phasecs = [[[0] * 5 for _ in range(4)] for _ in range(self.num_board)]
        self.firmwareversion = None
        self.hsprosock_t1 = None
        self.hsprosock = None
        self.outf = None
        self.dofft = False
        self.db = False
        self.lastTime = time.time()
        self.fps = None
        self.lastclk = -1
        self.lines = []
        self.otherlines = []
        self.dorecordtofile = False
        self.timer = QtCore.QTimer()
        self.timer2 = QtCore.QTimer()

        self.expect_samples = DEFAULT_EXPECT_SAMPLES
        self.expect_samples_extra = DEFAULT_EXPECT_SAMPLES_EXTRA
        self.samplerate = DEFAULT_SAMPLERATE_GHZ
        self.nsunits = 1
        self.num_chan_per_board = 2
        self.num_logic_inputs = 0

        # Debug and internal flags
        self.debug = False
        self.dopattern = 0
        self.debugprint = True
        self.showbinarydata = True
        self.debugstrobe = False
        self.dofast = False
        self.dotwochannel = False
        self.dointerleaved = [False] * self.num_board
        self.dooverrange = False
        self.total_rx_len = 0
        self.time_start = time.time()

        # Trigger and acquisition state
        self.triggertype = 1
        self.isrolling = 0
        self.selectedchannel = 0
        self.activeboard = 0
        self.activexychannel = 0
        self.tad = [0] * self.num_board
        self.toff = 36
        self.triggershift = 2
        self.themuxoutV = True
        self.phaseoffset = 0
        self.doexttrig = [0] * self.num_board
        self.doextsmatrig = [0] * self.num_board
        self.paused = True  # Start paused, will be unpaused by toggle_run_pause

        # Scaling and plotting parameters
        self.downsample = 0
        self.downsamplefactor = 1
        self.highresval = 1
        self.xscale = 1
        self.xscaling = 1
        self.yscale = 3.3 / 2.03 * 10 * 5 / 8 / pow(2, 12) / 16
        self.min_y, self.max_y = -5, 5
        self.min_x = 0
        self.max_x = 4 * 10 * self.expect_samples * self.downsamplefactor / self.nsunits / self.samplerate
        self.xydata = 0
        self.xydatainterleaved = 0
        self.fftui = 0
        self.downsamplezoom = 1
        self.triggerlevel = 127
        self.triggerdelta = 1
        self.triggerpos = int(self.expect_samples * 128 / 256)
        self.triggertimethresh = 0
        self.triggerchan = [0] * self.num_board
        self.hline = 0
        self.vline = 0
        self.getone = False
        self.downsamplemerging = 1
        self.units = "ns"
        self.dodrawing = True
        self.chtext = ""
        self.linepens = []
        self.nlines = 0

        # Status and event counters
        self.statuscounter = 0
        self.nevents = 0
        self.oldnevents = 0
        self.tinterval = 100.
        self.oldtime = time.time()
        self.nbadclkA, self.nbadclkB, self.nbadclkC, self.nbadclkD, self.nbadstr = 0, 0, 0, 0, 0
        self.eventcounter = [0] * self.num_board
        self.nsubsamples = 10 * 4 + 8 + 2
        self.sample_triggered = [0] * self.num_board
        self.triggerphase = [0] * self.num_board
        self.downsamplemergingcounter = [0] * self.num_board
        self.fitwidthfraction = 0.2

        # Calibration and correction values
        self.extrigboardstdcorrection = [1] * self.num_board
        self.extrigboardmeancorrection = [0] * self.num_board
        self.lastrate, self.lastsize = 0, 0
        self.VperD = [0.16] * (self.num_board * 2)
        self.plljustreset = [-10] * self.num_board
        self.plljustresetdir = [0] * self.num_board
        self.phasenbad = [[0] * PLL_ADJUSTMENT_STEPS] * self.num_board
        self.dooversample = [False] * self.num_board
        self.doresamp = 0
        self.dopersist = False
        self.triggerautocalibration = [False] * self.num_board
        self.extraphasefortad = [0] * self.num_board
        self.doexttrigecho = [False] * self.num_board
        self.oldeventcounterdiff, self.oldeventtime = -9999, -9999
        self.doeventcounter, self.doeventtime = False, False
        self.lvdstrigdelay = [0] * self.num_board
        self.lastlvdstrigdelay = [0] * self.num_board

        # Channel-specific settings
        num_total_chans = self.num_board * self.num_chan_per_board
        self.acdc = [False] * num_total_chans
        self.mohm = [False] * num_total_chans
        self.att = [False] * num_total_chans
        self.tenx = [1] * num_total_chans
        self.auxoutval = [0] * self.num_board
        self.offset = [0] * num_total_chans
        self.gain = [0] * num_total_chans
        self.noextboard = -1

    def _connect_ui_signals(self):
        """Connects all UI element signals to their corresponding slots."""
        # Main controls
        self.ui.runButton.clicked.connect(self.toggle_run_pause)
        self.ui.rollingButton.clicked.connect(self.rolling)
        self.ui.singleButton.clicked.connect(self.single)
        self.ui.timeslowButton.clicked.connect(self.time_slow)
        self.ui.timefastButton.clicked.connect(self.time_fast)
        self.ui.drawingCheck.clicked.connect(self.drawing)
        self.ui.persistCheck.clicked.connect(self.persist)
        self.ui.fftCheck.clicked.connect(self.fft)

        # Trigger controls
        self.ui.threshold.valueChanged.connect(self.trigger_level_changed)
        self.ui.thresholdDelta.valueChanged.connect(self.trigger_delta_changed)
        self.ui.thresholdPos.valueChanged.connect(self.trigger_pos_changed)
        self.ui.risingfalling_comboBox.currentIndexChanged.connect(self.rising_falling)
        self.ui.exttrigCheck.stateChanged.connect(self.ext_trig)
        self.ui.extsmatrigCheck.stateChanged.connect(self.ext_sma_trig)
        self.ui.totBox.valueChanged.connect(self.tot)
        self.ui.depthBox.valueChanged.connect(self.depth)
        self.ui.trigchan_comboBox.currentIndexChanged.connect(self.trigger_chan_changed)

        # Board and Channel controls
        self.ui.boardBox.valueChanged.connect(self.board_changed)
        self.ui.chanBox.valueChanged.connect(self.select_channel)
        self.ui.gainBox.valueChanged.connect(self.change_gain)
        self.ui.offsetBox.valueChanged.connect(self.change_offset)
        self.ui.acdcCheck.stateChanged.connect(self.set_acdc)
        self.ui.ohmCheck.stateChanged.connect(self.set_mohm)
        self.ui.oversampCheck.stateChanged.connect(self.set_oversamp)
        self.ui.interleavedCheck.stateChanged.connect(self.interleave)
        self.ui.attCheck.stateChanged.connect(self.set_att)
        self.ui.tenxCheck.stateChanged.connect(self.set_tenx)
        self.ui.chanonCheck.stateChanged.connect(self.chan_on)
        self.ui.twochanCheck.clicked.connect(self.two_chan)
        self.ui.Auxout_comboBox.currentIndexChanged.connect(self.aux_out)

        # Plotting and Display
        self.ui.gridCheck.stateChanged.connect(self.grid)
        self.ui.markerCheck.stateChanged.connect(self.marker)
        self.ui.highresCheck.stateChanged.connect(self.high_res)
        self.ui.resampBox.valueChanged.connect(self.resamp)

        # PLL and Timing Adjustment
        self.ui.pllresetButton.clicked.connect(self.pll_reset)
        self.ui.adfresetButton.clicked.connect(self.adf_reset)
        self.ui.fwfBox.valueChanged.connect(self.fwf)
        self.ui.tadBox.valueChanged.connect(self.set_TAD)
        self.ui.ToffBox.valueChanged.connect(self.set_Toff)

        # PLL Phase buttons
        self.ui.upposButton0.clicked.connect(lambda: self._adjust_pll_phase(0, 1))
        self.ui.downposButton0.clicked.connect(lambda: self._adjust_pll_phase(0, 0))
        self.ui.upposButton1.clicked.connect(lambda: self._adjust_pll_phase(1, 1))
        self.ui.downposButton1.clicked.connect(lambda: self._adjust_pll_phase(1, 0))
        self.ui.upposButton2.clicked.connect(lambda: self._adjust_pll_phase(2, 1))
        self.ui.downposButton2.clicked.connect(lambda: self._adjust_pll_phase(2, 0))
        self.ui.upposButton3.clicked.connect(lambda: self._adjust_pll_phase(3, 1))
        self.ui.downposButton3.clicked.connect(lambda: self._adjust_pll_phase(3, 0))
        self.ui.upposButton4.clicked.connect(lambda: self._adjust_pll_phase(4, 1))
        self.ui.downposButton4.clicked.connect(lambda: self._adjust_pll_phase(4, 0))

        # Menu actions
        self.ui.actionDo_autocalibration.triggered.connect(self.autocalibration)
        self.ui.actionUpdate_firmware.triggered.connect(self.update_firmware)
        self.ui.actionForce_split.triggered.connect(self.force_split)
        self.ui.actionForce_switch_clocks.triggered.connect(self.force_switch_clocks)
        self.ui.actionToggle_PLL_controls.triggered.connect(self.toggle_pll_controls)
        self.ui.actionRecord.triggered.connect(self.record_to_file)
        self.ui.actionAbout.triggered.connect(self.about)

        # Timers
        self.timer.timeout.connect(self.update_plot)
        self.timer2.timeout.connect(self.draw_text)

    def _initialize_hardware(self):
        """Sets up connections and initializes all connected boards."""
        self.ui.statusBar.showMessage(f"{self.num_board} boards connected!")
        self.ui.trigchan_comboBox.setMaxVisibleItems(1)

        for i in range(self.num_board):
            if not self.setup_connection(i):
                print(f"Exiting now - failed setup_connections for board {i}!")
                cleanup(self.usbs[i])
                return False

        # Now that hardware is connected, perform initial setup.
        self.tot()
        self.ui.ToffBox.setValue(self.toff)
        self.setup_channels()
        self.launch()
        self.do_leds()
        self.rolling()
        self.select_channel()
        self.time_changed()
        self.use_ext_trigs()
        self.open_socket()

        if self.num_board > 0:
            self.toggle_run_pause()  # Start acquisition

        if self.num_board < 2:
            self.ui.ToffBox.setEnabled(False)
            self.ui.tadBox.setEnabled(False)

        return True

    # --- UI Action Methods ---
    def about(self):
        QMessageBox.about(
            self,
            "Haasoscope Pro Qt, by DrAndyHaas",
            "A PyQt5 application for the Haasoscope Pro\n\nVersion 27.01"
        )

    def record_to_file(self):
        self.dorecordtofile = not self.dorecordtofile
        if self.dorecordtofile:
            fname = "HaasoscopePro_out_" + time.strftime("%Y%m%d-%H%M%S") + ".csv"
            self.outf = open(fname, "wt")
            header = "Event #, Time (s), Channel, Trigger time (ns), Sample period (ns), # samples"
            num_samples = (2 if self.dotwochannel else 4) * 10 * self.expect_samples
            sample_headers = "".join([f" , Sample {s}" for s in range(num_samples)])
            self.outf.write(header + sample_headers + "\n")
            self.ui.actionRecord.setText("Stop recording")
        else:
            if self.outf:
                self.outf.close()
            self.ui.actionRecord.setText("Record to file")

    def force_split(self):
        setsplit(self.usbs[self.activeboard], self.ui.actionForce_split.isChecked())

    def force_switch_clocks(self):
        switchclock(self.usbs[self.activeboard], self.activeboard)

    def toggle_pll_controls(self):
        is_pll_enabled = self.ui.pllBox.isEnabled()
        new_state = not is_pll_enabled

        buttons_to_toggle = [
            self.ui.upposButton0, self.ui.upposButton1, self.ui.upposButton2,
            self.ui.upposButton3, self.ui.upposButton4, self.ui.downposButton0,
            self.ui.downposButton1, self.ui.downposButton2, self.ui.downposButton3,
            self.ui.downposButton4
        ]

        for button in buttons_to_toggle:
            button.setEnabled(new_state)

        self.ui.pllBox.setEnabled(not new_state)

    def board_changed(self):
        self.activeboard = self.ui.boardBox.value()
        self.select_channel()

    def select_channel(self):
        if self.num_board == 0: return

        is_even_board = self.activeboard % 2 == 0
        can_oversample = is_even_board and not self.dotwochannel and self.num_board > 1

        self.ui.oversampCheck.setEnabled(can_oversample)
        if can_oversample:
            self.ui.interleavedCheck.setEnabled(self.dooversample[self.activeboard])
            self.ui.oversampCheck.setChecked(self.dooversample[self.activeboard])
            self.ui.interleavedCheck.setChecked(self.dointerleaved[self.activeboard])
        else:
            self.ui.oversampCheck.setChecked(False)
            self.ui.interleavedCheck.setEnabled(False)
            self.ui.interleavedCheck.setChecked(False)

        self.ui.exttrigCheck.setChecked(self.doexttrig[self.activeboard])
        self.ui.extsmatrigCheck.setEnabled(not self.doexttrig[self.activeboard])
        self.ui.extsmatrigCheck.setChecked(self.doextsmatrig[self.activeboard])
        self.ui.exttrigCheck.setEnabled(not self.doextsmatrig[self.activeboard])

        self.selectedchannel = self.ui.chanBox.value()
        self.activexychannel = self.activeboard * self.num_chan_per_board + self.selectedchannel

        palette = self.ui.chanColor.palette()
        color = self.linepens[self.activexychannel].color()
        if self.activeboard % 2 == 1 and self.dointerleaved[self.activeboard]:
            color = self.linepens[self.activexychannel - self.num_chan_per_board].color().darker(200)
        palette.setColor(QPalette.Base, color)
        self.ui.chanColor.setPalette(palette)

        self.ui.chanonCheck.setChecked(self.lines[self.activexychannel].isVisible())
        self.ui.tadBox.setValue(self.tad[self.activeboard])
        self.ui.acdcCheck.setChecked(self.acdc[self.activexychannel])
        self.ui.ohmCheck.setChecked(self.mohm[self.activexychannel])
        self.ui.tenxCheck.setChecked(self.tenx[self.activexychannel] == 10)
        self.ui.attCheck.setChecked(self.att[self.activexychannel])
        self.ui.Auxout_comboBox.setCurrentIndex(self.auxoutval[self.activeboard])
        self.ui.offsetBox.setValue(self.offset[self.activexychannel])
        self.ui.gainBox.setValue(self.gain[self.activexychannel])
        self.ui.trigchan_comboBox.setCurrentIndex(self.triggerchan[self.activeboard] if self.dotwochannel else 0)

    def fft(self):
        if self.ui.fftCheck.isChecked():
            self.fftui = FFTWindow()
            self.fftui.setWindowTitle(f'Haasoscope Pro FFT of board {self.activeboard} channel {self.selectedchannel}')
            self.fftui.show()
            self.dofft = True
        else:
            if self.fftui: self.fftui.close()
            self.dofft = False

    def resamp(self, value):
        self.doresamp = value

    def two_chan(self):
        self.dotwochannel = self.ui.twochanCheck.isChecked()
        if self.dorecordtofile:
            self.record_to_file()
            self.record_to_file()

        for board_idx in range(self.num_board):
            for chan_idx in range(self.num_chan_per_board):
                setchanatt(self.usbs[board_idx], chan_idx, self.dotwochannel, self.dooversample[board_idx])

        self.att = [self.dotwochannel] * (self.num_board * self.num_chan_per_board)
        self.ui.attCheck.setChecked(self.dotwochannel)

        self.setup_channels()
        self.do_leds()
        for usb in self.usbs:
            setupboard(usb, self.dopattern, self.dotwochannel, self.dooverrange)
            self.tell_downsample(usb, self.downsample)

        self.time_changed()

        if self.dotwochannel:
            self.ui.chanBox.setMaximum(self.num_chan_per_board - 1)
            self.ui.oversampCheck.setEnabled(False)
            self.ui.trigchan_comboBox.setMaxVisibleItems(2)
        else:
            self.ui.chanBox.setMaximum(0)
            if self.activeboard % 2 == 0 and self.num_board > 1: self.ui.oversampCheck.setEnabled(True)
            self.ui.trigchan_comboBox.setCurrentIndex(0)
            self.ui.trigchan_comboBox.setMaxVisibleItems(1)

        for c in range(self.num_board * self.num_chan_per_board):
            if c % 2 == 1: self.lines[c].setVisible(self.dotwochannel)

    def change_offset(self):
        self.offset[self.activexychannel] = self.ui.offsetBox.value()
        scaling = 1000 * self.VperD[self.activexychannel] / 160
        if self.ui.acdcCheck.isChecked(): scaling *= 245 / 160

        if dooffset(self.usbs[self.activeboard], self.selectedchannel, self.offset[self.activexychannel], scaling / self.tenx[self.activexychannel], self.dooversample[self.activeboard]):
            if self.dooversample[self.activeboard] and self.activeboard % 2 == 0:
                dooffset(self.usbs[self.activeboard + 1], self.selectedchannel, self.offset[self.activexychannel], scaling / self.tenx[self.activexychannel], self.dooversample[self.activeboard])
                self.offset[self.activexychannel + self.num_chan_per_board] = self.offset[self.activexychannel]

            v2 = scaling * 1.5 * self.offset[self.activexychannel]
            if self.dooversample[self.activeboard]: v2 *= 2.0
            if self.ui.acdcCheck.isChecked(): v2 *= (160 / 245)
            self.ui.Voff.setText(f"{int(v2)} mV")

    def change_gain(self):
        self.gain[self.activexychannel] = self.ui.gainBox.value()
        setgain(self.usbs[self.activeboard], self.selectedchannel, self.gain[self.activexychannel], self.dooversample[self.activeboard])

        if self.dooversample[self.activeboard] and self.activeboard % 2 == 0:
            setgain(self.usbs[self.activeboard + 1], self.selectedchannel, self.gain[self.activexychannel], self.dooversample[self.activeboard])
            self.gain[self.activexychannel + self.num_chan_per_board] = self.gain[self.activexychannel]

        db = self.gain[self.activexychannel]
        v2 = 0.1605 * self.tenx[self.activexychannel] / pow(10, db / 20.0)
        if self.dooversample[self.activeboard]: v2 *= 2.0

        old_v_per_d = self.VperD[self.activexychannel]
        self.VperD[self.activexychannel] = v2

        if self.dooversample[self.activeboard] and self.activeboard % 2 == 0:
            self.VperD[self.activexychannel + self.num_chan_per_board] = v2

        self.ui.offsetBox.setValue(int(self.ui.offsetBox.value() * old_v_per_d / v2))
        self.ui.VperD.setText(f"{int(round(1000 * v2, 0))} mV/div")

        self.ui.gainBox.setSingleStep(2 if self.ui.gainBox.value() > 24 else 6)

    def fwf(self):
        self.fitwidthfraction = self.ui.fwfBox.value() / 100.0

    def set_TAD(self):
        self.tad[self.activeboard] = self.ui.tadBox.value()
        spicommand(self.usbs[self.activeboard], "TAD", 0x02, 0xB6, abs(self.tad[self.activeboard]), False, quiet=True)

        if self.tad[self.activeboard] > 135:
            if not self.extraphasefortad[self.activeboard]:
                self.do_phase(self.activeboard, plloutnum=0, updown=1, pllnum=0)
                self.do_phase(self.activeboard, plloutnum=1, updown=1, pllnum=0)
                self.extraphasefortad[self.activeboard] += 1
                print(f"extra phase for TAD>135 now {self.extraphasefortad[self.activeboard]}")
        else:
            if self.extraphasefortad[self.activeboard]:
                self.do_phase(self.activeboard, plloutnum=0, updown=0, pllnum=0)
                self.do_phase(self.activeboard, plloutnum=1, updown=0, pllnum=0)
                self.extraphasefortad[self.activeboard] -= 1
                print(f"extra phase for TAD>135 now {self.extraphasefortad[self.activeboard]}")

    def set_Toff(self):
        self.toff = self.ui.ToffBox.value()

    def adf_reset(self, board):
        if not isinstance(board, int): board = self.activeboard
        usb = self.usbs[board]
        adf4350(usb, self.samplerate * 1000 / 2, None, themuxout=self.themuxoutV)
        time.sleep(0.1)
        res = boardinbits(usb)
        if not getbit(res, 5):
            print(f"Adf pll for board {board} not locked?")
        else:
            print(f"Adf pll locked for board {board}")

    def chan_on(self):
        self.lines[self.activexychannel].setVisible(self.ui.chanonCheck.isChecked())

    def set_acdc(self):
        is_ac = self.ui.acdcCheck.isChecked()
        self.acdc[self.activexychannel] = is_ac
        setchanacdc(self.usbs[self.activeboard], self.selectedchannel, is_ac, self.dooversample[self.activeboard])
        self.change_offset()
        if self.dooversample[self.activeboard] and self.activeboard % 2 == 0:
            setchanacdc(self.usbs[self.activeboard + 1], self.selectedchannel, is_ac, self.dooversample[self.activeboard])
            self.acdc[self.activexychannel + self.num_chan_per_board] = is_ac

    def set_mohm(self):
        is_1M_ohm = self.ui.ohmCheck.isChecked()
        self.mohm[self.activexychannel] = is_1M_ohm
        setchanimpedance(self.usbs[self.activeboard], self.selectedchannel, is_1M_ohm, self.dooversample[self.activeboard])

    def set_att(self):
        is_att_on = self.ui.attCheck.isChecked()
        self.att[self.activexychannel] = is_att_on
        setchanatt(self.usbs[self.activeboard], self.selectedchannel, is_att_on, self.dooversample[self.activeboard])
        if self.dooversample[self.activeboard] and self.activeboard % 2 == 0:
            setchanatt(self.usbs[self.activeboard + 1], self.selectedchannel, is_att_on, self.dooversample[self.activeboard])
            self.att[self.activexychannel + self.num_chan_per_board] = is_att_on

    def set_tenx(self):
        self.tenx[self.activexychannel] = 10 if self.ui.tenxCheck.isChecked() else 1
        self.change_gain()
        self.change_offset()

    def set_oversamp(self):
        assert self.activeboard % 2 == 0 and self.num_board > 1
        is_oversampling = self.ui.oversampCheck.isChecked()
        self.dooversample[self.activeboard] = is_oversampling
        self.dooversample[self.activeboard + 1] = is_oversampling

        setsplit(self.usbs[self.activeboard], is_oversampling)
        setsplit(self.usbs[self.activeboard + 1], False)

        for board_idx in [self.activeboard, self.activeboard + 1]:
            swapinputs(self.usbs[board_idx], is_oversampling)

        self.ui.interleavedCheck.setEnabled(is_oversampling)
        self.ui.twochanCheck.setEnabled(not is_oversampling)
        if not is_oversampling: self.ui.interleavedCheck.setChecked(False)

        self.change_gain()
        self.change_offset()
        self.do_leds()

    def interleave(self):
        assert self.activeboard % 2 == 0 and self.num_board > 1
        is_interleaved = self.ui.interleavedCheck.isChecked()
        self.dointerleaved[self.activeboard] = is_interleaved
        self.dointerleaved[self.activeboard + 1] = is_interleaved

        line_idx = (self.activeboard + 1) * self.num_chan_per_board
        self.lines[line_idx].setVisible(not is_interleaved)

        self.select_channel()
        self.time_changed()
        self.do_leds()

    def do_phase(self, board, plloutnum, updown, pllnum=None, quiet=False):
        if pllnum is None: pllnum = int(self.ui.pllBox.value())

        self.usbs[board].send(bytes([6, pllnum, int(plloutnum + 2), updown, 100, 100, 100, 100]))

        self.phasecs[board][pllnum][plloutnum] += 1 if updown else -1

        if not quiet:
            print(f"phase for pllnum {pllnum} plloutnum {plloutnum} on board {board} now {self.phasecs[board][pllnum][plloutnum]}")

    def _adjust_pll_phase(self, pll_out_num, direction):
        """Helper to adjust PLL phase for the active board."""
        self.do_phase(self.activeboard, plloutnum=pll_out_num, updown=direction)

    def pll_reset(self, board):
        if not isinstance(board, int): board = self.activeboard
        self.usbs[board].send(bytes([5, 99, 99, 99, 100, 100, 100, 100]))
        tres = self.usbs[board].recv(4)
        print(f"pll_reset sent to board {board} - got back: {tres[3]} {tres[2]} {tres[1]} {tres[0]}")

        self.phasecs[board] = [[0] * 5 for _ in range(4)]
        self.plljustreset[board] = 0
        self.plljustresetdir[board] = 1
        self.phasenbad[board] = [0] * PLL_ADJUSTMENT_STEPS
        self.expect_samples = 1000
        self.dodrawing = False
        if self.num_board > 1 and self.doexttrig[board]: self.doexttrigecho[board] = True
        #CALLBACK is to adjustclocks, below, which runs for each event and then finishes up at the end of that function

    def adjust_clocks(self, board, nbadclkA, nbadclkB, nbadclkC, nbadclkD, nbadstr):
        debug_phase = False
        plloutnum, plloutnum2 = 0, 1
        pll_state = self.plljustreset[board]

        if 0 <= pll_state < PLL_ADJUSTMENT_STEPS:
            nbad = nbadclkA + nbadclkB + nbadclkC + nbadclkD + nbadstr
            if debug_phase: print(f"plljustreset for board {board} is {pll_state} nbad {nbad}")
            self.phasenbad[board][pll_state] += nbad
            self.do_phase(board, plloutnum, (self.plljustresetdir[board] == 1), pllnum=0, quiet=True)
            self.do_phase(board, plloutnum2, (self.plljustresetdir[board] == 1), pllnum=0, quiet=True)
            self.plljustreset[board] += self.plljustresetdir[board]

        elif pll_state >= PLL_ADJUSTMENT_STEPS:
            if debug_phase: print(f"plljustreset for board {board} is {pll_state}")
            if pll_state == 15: self.plljustresetdir[board] = -1
            self.plljustreset[board] += self.plljustresetdir[board]
            self.do_phase(board, plloutnum, (self.plljustresetdir[board] == 1), pllnum=0, quiet=True)
            self.do_phase(board, plloutnum2, (self.plljustresetdir[board] == 1), pllnum=0, quiet=True)

        elif pll_state == -1:
            if debug_phase: print(f"plljustreset for board {board} is {pll_state}")
            print(f"bad clkstr per phase step: {self.phasenbad[board]}")
            start, length = find_longest_zero_stretch(self.phasenbad[board], True)
            print(f"good phase starts at {start} and goes for {length} steps")

            if start >= PLL_ADJUSTMENT_STEPS: start -= PLL_ADJUSTMENT_STEPS
            n_steps = start + length // 2 + self.phaseoffset
            if n_steps >= PLL_ADJUSTMENT_STEPS: n_steps -= PLL_ADJUSTMENT_STEPS
            n_steps += 1

            for i in range(n_steps):
                is_last_step = (i == n_steps - 1)
                self.do_phase(board, plloutnum, 1, pllnum=0, quiet=not is_last_step)
                self.do_phase(board, plloutnum2, 1, pllnum=0, quiet=not is_last_step)

            self.plljustreset[board] += self.plljustresetdir[board]

        elif pll_state == -2:
            self.depth()
            self.plljustreset[board] += self.plljustresetdir[board]

        elif pll_state == -3:
            self.dodrawing = True
            self.plljustreset[board] = -10

    def ext_trig(self, value):
        board = self.ui.boardBox.value()
        self.doexttrig[board] = value
        self.ui.exttrigCheck.setChecked(bool(value))
        self.ui.extsmatrigCheck.setEnabled(not self.doexttrig[board])

        rolling_state = self.ui.rollingButton.isChecked()
        if self.doexttrig[board]: rolling_state = False

        self.usbs[board].send(bytes([2, 8, rolling_state, 0, 100, 100, 100, 100]))
        self.usbs[board].recv(4)

        if self.doexttrig[board]:
            self.doexttrigecho = [False] * self.num_board
            self.doexttrigecho[board] = True
        else:
            self.doexttrigecho[board] = False

        self.send_trigger_info(board)

    def ext_sma_trig(self):
        is_checked = self.ui.extsmatrigCheck.isChecked()
        self.doextsmatrig[self.activeboard] = is_checked
        self.ui.exttrigCheck.setEnabled(not is_checked)

    def grid(self):
        is_checked = self.ui.gridCheck.isChecked()
        self.ui.plot.showGrid(x=is_checked, y=is_checked)

    def marker(self):
        is_checked = self.ui.markerCheck.isChecked()
        for i in range(self.nlines):
            if is_checked:
                color = self.linepens[i].color()
                self.lines[i].setSymbol("o")
                self.lines[i].setSymbolSize(3)
                self.lines[i].setSymbolPen(color)
                self.lines[i].setSymbolBrush(color)
            else:
                self.lines[i].setSymbol(None)

    def toggle_run_pause(self):
        if self.paused:
            self.timer.start(0)
            self.timer2.start(1000)
            self.paused = False
            self.ui.runButton.setChecked(True)
        else:
            self.timer.stop()
            self.timer2.stop()
            self.paused = True
            self.ui.runButton.setChecked(False)

    def trigger_level_changed(self, value):
        if 0 < (value - self.triggerdelta) and (value + self.triggerdelta) < 256:
            self.triggerlevel = value
            for board in range(self.num_board): self.send_trigger_info(board)
            self.draw_trigger_lines()

    def trigger_delta_changed(self, value):
        if 0 < (self.triggerlevel - value) and (self.triggerlevel + value) < 256:
            self.triggerdelta = value
            for board in range(self.num_board): self.send_trigger_info(board)

    def trigger_pos_changed(self, value):
        self.triggerpos = int(self.expect_samples * value / 100)
        for board in range(self.num_board): self.send_trigger_info(board)
        self.draw_trigger_lines()

    def trigger_chan_changed(self):
        self.triggerchan[self.activeboard] = self.ui.trigchan_comboBox.currentIndex()
        self.send_trigger_info(self.activeboard)

    def send_trigger_info(self, board):
        triggerpos = self.triggerpos + self.triggershift
        if self.doexttrig[board]:
            delay = int(8 * self.lvdstrigdelay[board] / 40 / self.downsamplefactor)
            if self.dotwochannel: delay //= 2
            triggerpos += delay

        self.usbs[board].send(bytes([8, self.triggerlevel + 1, self.triggerdelta, triggerpos // 256, triggerpos % 256, self.triggertimethresh, self.triggerchan[board], 100]))
        self.usbs[board].recv(4)

        prelengthtotake = self.triggerpos + 5
        self.usbs[board].send(bytes([2, 7] + inttobytes(prelengthtotake) + [0, 0]))
        self.usbs[board].recv(4)

    def draw_trigger_lines(self):
        self.hline = (self.triggerlevel - 127) * self.yscale * 256
        self.otherlines[1].setData([self.min_x, self.max_x], [self.hline, self.hline])

        point = self.triggerpos + 1.0
        self.vline = 40 * point * (self.downsamplefactor / self.nsunits / self.samplerate)
        y_center = max(self.hline + self.min_y / 2, self.min_y)
        y_top = min(self.hline + self.max_y / 2, self.max_y)
        self.otherlines[0].setData([self.vline, self.vline], [y_center, y_top])

    def tot(self):
        self.triggertimethresh = self.ui.totBox.value()
        for board in range(self.num_board): self.send_trigger_info(board)

    def depth(self):
        self.expect_samples = self.ui.depthBox.value()
        self.setup_channels()
        self.trigger_pos_changed(self.ui.thresholdPos.value())
        self.tot()
        self.time_changed()

    def rolling(self):
        self.isrolling = not self.isrolling
        self.ui.rollingButton.setChecked(self.isrolling)
        for board in range(len(self.usbs)):
            r = self.isrolling
            if self.doexttrig[board]: r = False
            self.usbs[board].send(bytes([2, 8, r, 0, 100, 100, 100, 100]))
            self.usbs[board].recv(4)
        self.ui.rollingButton.setText("Auto" if self.isrolling else "Normal")

    def single(self):
        self.getone = not self.getone
        self.ui.singleButton.setChecked(self.getone)

    def high_res(self, value):
        self.highresval = value > 0
        for usb in self.usbs: self.tell_downsample(usb, self.downsample)

    def tell_downsample(self, usb, ds):
        #ds_val = max(ds, 0)

        if ds <= 0: self.downsamplemerging = 1; ds_val = 0
        elif ds == 1: self.downsamplemerging = 2; ds_val = 0
        elif ds == 2: self.downsamplemerging = 4; ds_val = 0
        elif ds == 3: self.downsamplemerging = 10 if self.dotwochannel else 8; ds_val = 0
        elif ds == 4: self.downsamplemerging = 20; ds_val = 0
        else:
            if not self.dotwochannel:
                if ds == 5:
                    self.downsamplemerging = 40; ds_val = 0
                else:
                    ds_val, self.downsamplemerging = ds - 5, 40
            else:
                ds_val, self.downsamplemerging = ds - 4, 20

        self.downsamplefactor = self.downsamplemerging * pow(2, ds_val)
        usb.send(bytes([9, ds_val, self.highresval, self.downsamplemerging, 100, 100, 100, 100]))
        usb.recv(4)

    def time_fast(self):
        if self.downsample - 1 < -10:
            print("downsample too small!")
            return
        self.downsample -= 1
        if self.downsample < 0:
            self.downsamplezoom = pow(2, -self.downsample)
            self.ui.thresholdPos.setEnabled(False)
        else:
            self.downsamplezoom = 1
            self.ui.thresholdPos.setEnabled(True)
            for usb in self.usbs: self.tell_downsample(usb, self.downsample)
        self.time_changed()

    def time_slow(self):
        if (self.downsample + 1 - 5) > 31:
            print("downsample too large!")
            return
        self.downsample += 1
        if self.downsample < 0:
            self.downsamplezoom = pow(2, -self.downsample)
            self.ui.thresholdPos.setEnabled(False)
        else:
            self.downsamplezoom = 1
            self.ui.thresholdPos.setEnabled(True)
            for usb in self.usbs: self.tell_downsample(usb, self.downsample)
        self.time_changed()

    def time_changed(self):
        base_max_x = 40 * self.expect_samples * self.downsamplefactor / self.samplerate

        if base_max_x > 5e9:
            self.nsunits, self.units = 1e9, "s"
        elif base_max_x > 5e6:
            self.nsunits, self.units = 1e6, "ms"
        elif base_max_x > 5e3:
            self.nsunits, self.units = 1e3, "us"
        else:
            self.nsunits, self.units = 1, "ns"

        self.max_x = base_max_x / self.nsunits
        self.ui.plot.setLabel('bottom', f"Time ({self.units})")

        if self.downsamplezoom > 1:
            tp_frac = self.vline / self.max_x if self.max_x != 0 else 0
            new_width = self.max_x / self.downsamplezoom
            self.min_x = self.vline - tp_frac * new_width
            self.max_x = self.vline + (1 - tp_frac) * new_width
        else:
            self.min_x = 0

        if hasattr(self, "hsprosock") and self.hsprosock:
            while self.hsprosock.issending: time.sleep(0.001)

        num_samples = 10 * self.expect_samples
        if self.dotwochannel:
            x_vals = np.arange(2 * num_samples) * (2 * self.downsamplefactor / self.nsunits / self.samplerate)
            for c in range(self.num_chan_per_board * self.num_board): self.xydata[c][0] = x_vals
        else:
            x_vals = np.arange(4 * num_samples) * (self.downsamplefactor / self.nsunits / self.samplerate)
            x_interleaved = np.arange(8 * num_samples) * (0.5 * self.downsamplefactor / self.nsunits / self.samplerate)
            for c in range(self.num_chan_per_board * self.num_board):
                self.xydata[c][0] = x_vals
                if self.dointerleaved[c // 2]: self.xydatainterleaved[c // 2][0] = x_interleaved

        self.ui.plot.setRange(xRange=(self.min_x, self.max_x), padding=0.0)
        self.ui.plot.setRange(yRange=(self.min_y, self.max_y), padding=0.01)
        self.draw_trigger_lines()
        self.tot()
        self.ui.timebaseBox.setText(f"2^{self.downsample}")

    def rising_falling(self):
        is_falling_edge = self.ui.risingfalling_comboBox.currentIndex() == 1
        if self.triggertype == 1 and is_falling_edge:
            self.triggertype = 2
        elif self.triggertype == 2 and not is_falling_edge:
            self.triggertype = 1

    def drawing(self):
        self.dodrawing = self.ui.drawingCheck.isChecked()

    def persist(self):
        self.dopersist = not self.dopersist
        print(f"do persist {self.dopersist}")

    def update_plot(self):
        if hasattr(self, "hsprosock"):
            while self.hsprosock.issending: time.sleep(0.001)

        gotevent = self._get_event()
        now = time.time()
        dt = now - self.lastTime + 1e-6
        self.lastTime = now

        if self.fps is None:
            self.fps = 1.0 / dt
        else:
            s = np.clip(dt * 3., 0, 1)
            self.fps = self.fps * (1 - s) + (1.0 / dt) * s

        self.statuscounter += 1
        if self.statuscounter % 20 == 0:
            status_msg = f"{self.fps:.2f} fps, {self.nevents} events, {self.lastrate:.2f} Hz, {self.lastrate * self.lastsize / 1e6:.2f} MB/s"
            self.ui.statusBar.showMessage(status_msg)

        if not gotevent: return

        if self.dorecordtofile:
            self._record_event_to_file()
            if self.nevents % NUM_RECORD_EVENTS_PER_FILE == 0 and self.dorecordtofile:
                self.record_to_file()
                self.record_to_file()

        if not self.dodrawing: return

        for li in range(self.nlines):
            board_idx = li // 2
            if not self.dointerleaved[board_idx]:
                x_data, y_data = self.xydata[li]
                if self.doresamp: y_data, x_data = resample(y_data, len(x_data) * self.doresamp, t=x_data)
                self.lines[li].setData(x_data, y_data)
            elif li % 4 == 0:
                interleaved_data = self.xydatainterleaved[board_idx]
                interleaved_data[1][0::2] = self.xydata[li][1]
                interleaved_data[1][1::2] = self.xydata[li + self.num_chan_per_board][1]
                x_data, y_data = interleaved_data
                if self.doresamp: y_data, x_data = resample(y_data, len(x_data) * self.doresamp, t=x_data)
                self.lines[li].setData(x_data, y_data)

        if self.dofft and hasattr(self.fftui, "fftfreqplot_xdata"):
            self._update_fft_plot()

    def _record_event_to_file(self):
        time_s = str(time.time())
        for c in range(self.num_board * self.num_chan_per_board):
            if self.lines[c].isVisible():  # only save the data for visible channels
                self.outf.write(str(self.nevents) + ",")  # start of each line is the event number
                self.outf.write(time_s + ",")  # next column is the time in seconds of the current event
                self.outf.write(str(c) + ",")  # next column is the channel number
                self.outf.write(str(self.vline * self.xscaling) + ",")  # next column is the trigger time
                self.outf.write(str(self.downsamplefactor / self.samplerate) + ",")  # next column is the time between samples, in ns
                self.outf.write(str( (2 if self.dotwochannel else 4) * 10 * self.expect_samples) + ",")  # next column is the number of samples
                self.xydata[c][1].tofile(self.outf, ",", format="%.3f")  # save y data (1) from fast adc channel c
                self.outf.write("\n")  # newline

    def _get_event(self):
        if self.paused:
            time.sleep(0.1)
            return 0

        rx_len = 0
        debug_read = False
        try:
            ready_event = [False] * self.num_board
            if debug_read: print("\n_get_event")
            no_ext_boards = []
            self.noextboard = -1

            # Process boards with external triggers first
            for board in range(self.num_board):
                if not self.doexttrig[board]:
                    no_ext_boards.append(board)
                    continue
                if self._get_channels(board):
                    if debug_read: print(f"board {board} ready")
                    self._get_pre_data(board)
                    ready_event[board] = True
                elif debug_read:
                    print(f"board {board} not ready")

            # Process boards without external triggers
            for board in no_ext_boards:
                if self._get_channels(board):
                    if self.noextboard == -1: self.noextboard = board
                    if debug_read: print(f"noext board {board} ready")
                    self._get_pre_data(board)
                    ready_event[board] = True
                elif debug_read:
                    print(f"noext board {board} not ready")

            if not any(ready_event):
                if debug_read: print("none ready")
                return 0

            # Read and draw data for all ready boards
            for board in range(self.num_board):
                if not ready_event[board]: continue
                data = self._get_data(self.usbs[board])
                rx_len += len(data)
                if self.dofft and board == self.activeboard: self._plot_fft()
                self._draw_channels(data, board)

            if self.getone and rx_len > 0: self.toggle_run_pause()

        except Exception as e:
            self.close_socket()
            print(f"Device error: {e}")
            sys.exit(1)

        if rx_len > 0:
            self.nevents += 1
        else:
            return 0

        if self.nevents - self.oldnevents >= self.tinterval:
            now = time.time()
            elapsed_time = now - self.oldtime
            self.oldtime = now
            if elapsed_time > 0: self.lastrate = round(self.tinterval / elapsed_time, 2)
            self.lastsize = rx_len
            self.oldnevents = self.nevents

        return 1

    def _get_channels(self, board):
        tt = self.triggertype
        if self.doexttrig[board]:
            tt = 30 if self.doexttrigecho[board] else 3
        elif self.doextsmatrig[board]:
            tt = 5

        post_trigger_samples = self.expect_samples + self.expect_samples_extra - self.triggerpos + 1
        self.usbs[board].send(bytes([1, tt, self.dotwochannel + 2 * self.dooversample[board], 99] + inttobytes(post_trigger_samples)))
        trigger_counter = self.usbs[board].recv(4)
        acq_state = trigger_counter[0]

        if acq_state == 251:
            got_zero_bit = False
            for s in range(20):
                the_bit = getbit(trigger_counter[s // 8 + 1], s % 8)
                if the_bit == 0: got_zero_bit = True
                if the_bit == 1 and got_zero_bit:
                    self.sample_triggered[board] = s
                    break
            return 1
        return 0

    def _get_pre_data(self, board):
        if self.doeventcounter:
            self.usbs[board].send(bytes([2, 3, 100, 100, 100, 100, 100, 100]))
            res = self.usbs[board].recv(4)
            eventcountertemp = int.from_bytes(res, "little")
            if eventcountertemp != self.eventcounter[board] + 1 and eventcountertemp != 0:
                print(f"Event counter not incremented by 1? {eventcountertemp} vs {self.eventcounter[board]} for board {board}")
            self.eventcounter[board] = eventcountertemp
            if board==0:
                eventcounterdiff = self.eventcounter[board]-self.eventcounter[board+1]
                if eventcounterdiff!=self.oldeventcounterdiff: print("eventcounter diff for board",board,"and",board+1,eventcounterdiff)
                self.oldeventcounterdiff=eventcounterdiff
        if self.doeventtime and board==0:
            self.usbs[board].send(bytes([2, 11, 100, 100, 100, 100, 100, 100]))
            res = self.usbs[board].recv(4)
            eventtime = int.from_bytes(res,"little")
            eventtimediff = eventtime - self.oldeventtime
            print(f"board {board} triggered at clock cycle {eventtime}, a diff of {eventtimediff} cycles, {round(0.0125*eventtimediff,4)} us")
            self.oldeventtime = eventtime
        self.downsamplemergingcounter[board] = 0
        self.usbs[board].send(bytes([2, 4, 100, 100, 100, 100, 100, 100]))  # get downsamplemergingcounter and triggerphase
        res = self.usbs[board].recv(4)
        if self.downsamplemerging > 1:
            self.downsamplemergingcounter[board] = res[0]
            if self.downsamplemergingcounter[board] == self.downsamplemerging and not self.doexttrig[board]:
                self.downsamplemergingcounter[board] = 0
        self.triggerphase[board] = res[1]

        if not self.doexttrig[board] and any(self.doexttrigecho):
            assert self.doexttrigecho.count(True) == 1
            echoboard = -1
            for theb in range(self.num_board):
                if self.doexttrigecho[theb]:
                    assert echoboard == -1
                    echoboard = theb
            assert echoboard != board
            if echoboard > board:
                self.usbs[board].send(bytes([2, 12, 100, 100, 100, 100, 100, 100]))  # get ext trig echo forwards delay
                res = self.usbs[board].recv(4)
            else:
                self.usbs[board].send(bytes([2, 13, 100, 100, 100, 100, 100, 100]))  # get ext trig echo backwards delay
                res = self.usbs[board].recv(4)

            if res[0] == res[1]:
                lvdstrigdelay = (res[0] + res[1]) / 4.0
                if echoboard < board: lvdstrigdelay += round(lvdstrigdelay / 11.5, 1)
                if lvdstrigdelay == self.lastlvdstrigdelay[echoboard]:
                    self.lvdstrigdelay[echoboard] = lvdstrigdelay
                    self.tot()
                    if all(item <= -10 for item in self.plljustreset):
                        print(f"lvdstrigdelay from board {board} to echoboard {echoboard} is {lvdstrigdelay}")
                        self.doexttrigecho[echoboard] = False
                self.lastlvdstrigdelay[echoboard] = lvdstrigdelay
            else:
                if all(item <= -10 for item in self.plljustreset):
                    self.do_phase(board, plloutnum=0, updown=1, quiet=True)
                    self.do_phase(board, plloutnum=1, updown=1, quiet=True)
                    self.do_phase(board, plloutnum=2, updown=1, quiet=True)

    def _get_data(self, usb):
        expect_len = (self.expect_samples + self.expect_samples_extra) * 2 * self.nsubsamples
        usb.send(bytes([0, 99, 99, 99] + inttobytes(expect_len)))
        data = usb.recv(expect_len)
        rx_len = len(data)
        self.total_rx_len += rx_len
        if expect_len != rx_len:
            print(f'*** expect_len ({expect_len}) and rx_len ({rx_len}) mismatch')
        return data

    def _draw_channels(self, data, board):
        if self.dofast: return

        if self.doexttrig[board] and self.noextboard != -1:
            board_to_use = self.noextboard
            self.sample_triggered[board] = self.sample_triggered[board_to_use]
            self.triggerphase[board] = self.triggerphase[board_to_use]

        sample_triggered_touse = self.sample_triggered[board]
        triggerphase_raw = self.triggerphase[board]

        if (triggerphase_raw % 4) != (triggerphase_raw >> 2) % 4 and sample_triggered_touse < 10:
            sample_triggered_touse -= 1

        triggerphase = (triggerphase_raw >> 4) if sample_triggered_touse >= 10 else (triggerphase_raw >> 2) % 4

        unpackedsamples = struct.unpack('<' + 'h' * (len(data) // 2), data)
        np_unpacked = np.array(unpackedsamples, dtype='float') * self.yscale

        if self.dooversample[board] and board % 2 == 0:
            np_unpacked += self.extrigboardmeancorrection[board]
            np_unpacked *= self.extrigboardstdcorrection[board]

        downsampleoffset = 2 * (sample_triggered_touse + (self.downsamplemergingcounter[board] - 1) % self.downsamplemerging * 10) // self.downsamplemerging
        downsampleoffset += 20 * self.triggershift
        if not self.dotwochannel: downsampleoffset *= 2

        if self.doexttrig[board]:
            toff_delay = int(self.toff / self.downsamplefactor)
            lvds_delay = int(8 * self.lvdstrigdelay[board] / self.downsamplefactor) % 40
            if self.dotwochannel:
                toff_delay //= 2
                lvds_delay //= 2
            downsampleoffset -= (toff_delay + lvds_delay)

        datasize = self.xydata[board * self.num_chan_per_board][1].size
        nbadclkA, nbadclkB, nbadclkC, nbadclkD, nbadstr = 0, 0, 0, 0, 0

        for s in range(0, self.expect_samples + self.expect_samples_extra):
            base_idx = s * self.nsubsamples
            vals = unpackedsamples[base_idx + 40: base_idx + 50]
            if vals[9] != -16657: print("no beef?")
            if vals[8] != 0 or (self.lastclk != 341 and self.lastclk != 682):
                for n in range(0, 8):
                    val = vals[n]
                    if n < 4:
                        if val != 341 and val != 682:
                            if n == 0: nbadclkA += 1
                            if n == 1: nbadclkB += 1
                            if n == 2: nbadclkC += 1
                            if n == 3: nbadclkD += 1
                        self.lastclk = val
                    elif val not in {0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512}:
                        nbadstr += 1

            if self.dotwochannel:
                samp = s * 20 - downsampleoffset - triggerphase // 2
                nsamp, nstart = 20, 0
                if samp < 0: nsamp += samp; nstart = -samp; samp = 0
                if samp + nsamp > datasize: nsamp = datasize - samp
                if 0 < nsamp <= 20:
                    self.xydata[board * self.num_chan_per_board][1][samp:samp + nsamp] = np_unpacked[base_idx + 20 + nstart: base_idx + 20 + nstart + nsamp]
                    self.xydata[board * self.num_chan_per_board + 1][1][samp:samp + nsamp] = np_unpacked[base_idx + nstart: base_idx + nstart + nsamp]
            else:
                samp = s * 40 - downsampleoffset - triggerphase
                nsamp, nstart = 40, 0
                if samp < 0: nsamp += samp; nstart = -samp; samp = 0
                if samp + nsamp > datasize: nsamp = datasize - samp
                if 0 < nsamp <= 40:
                    self.xydata[board * self.num_chan_per_board][1][samp:samp + nsamp] = np_unpacked[base_idx + nstart: base_idx + nstart + nsamp]

        self.adjust_clocks(board, nbadclkA, nbadclkB, nbadclkC, nbadclkD, nbadstr)
        if board == self.activeboard:
            self.nbadclkA, self.nbadclkB, self.nbadclkC, self.nbadclkD, self.nbadstr = nbadclkA, nbadclkB, nbadclkC, nbadclkD, nbadstr
        if self.triggerautocalibration[board]:
            self.triggerautocalibration[board] = False
            self.autocalibration()

    def draw_text(self):
        the_str = ""
        if self.dorecordtofile: the_str += f"Recording to file {self.outf.name}\n"

        if self.dodrawing:
            if self.ui.actionTrigger_thresh.isChecked(): the_str += f"Trigger threshold: {self.hline:.3f} div\n"
            if self.ui.actionTemperatures.isChecked(): the_str += gettemps(self.usbs[self.activeboard]) + "\n"

            the_str += f"\nMeasurements for board {self.activeboard} chan {self.selectedchannel}:\n"

            y_data = self.xydata[self.activexychannel][1]
            v_per_d = self.VperD[self.activexychannel]

            if self.ui.actionMean.isChecked(): the_str += f"Mean: {1000 * v_per_d * np.mean(y_data):.3f} mV\n"
            if self.ui.actionRMS.isChecked(): the_str += f"RMS: {1000 * v_per_d * np.std(y_data):.3f} mV\n"
            if self.ui.actionMaximum.isChecked(): the_str += f"Max: {1000 * v_per_d * np.max(y_data):.3f} mV\n"
            if self.ui.actionMinimum.isChecked(): the_str += f"Min: {1000 * v_per_d * np.min(y_data):.3f} mV\n"
            if self.ui.actionVpp.isChecked(): the_str += f"Vpp: {1000 * v_per_d * (np.max(y_data) - np.min(y_data)):.3f} mV\n"

            if self.ui.actionFreq.isChecked():
                sampling_rate = self.samplerate * 1e9 / self.downsamplefactor
                if self.dotwochannel: sampling_rate /= 2
                found_freq = find_fundamental_frequency_scipy(y_data, sampling_rate)
                the_str += f"Freq: {format_freq(found_freq)}\n"

            # ** MODIFIED BLOCK TO SUPPRESS WARNING **
            if self.ui.actionRisetime.isChecked():
                targety = self.xydatainterleaved[self.activeboard // 2] if self.dointerleaved[self.activeboard] else self.xydata[self.activexychannel]
                fitwidth = (self.max_x - self.min_x) * self.fitwidthfraction
                mask = (targety[0] > self.vline - fitwidth) & (targety[0] < self.vline + fitwidth)
                xc, yc = targety[0][mask], targety[1][mask]
                if xc.size > 10:
                    try:
                        p0 = [max(targety[1]), self.vline - 10, 20, min(targety[1])]
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            popt, pcov = curve_fit(fit_rise, xc, yc, p0=p0)
                            # This line is now inside the warning suppression block
                            perr = np.sqrt(np.diag(pcov))

                        risetime, risetimeerr = 0.8 * popt[2], perr[2]
                        the_str += f"Risetime: {risetime:.2f} +- {risetimeerr:.2f} {self.units}\n"
                    except RuntimeError:
                        pass

        self.ui.textBrowser.setText(the_str)

    def aux_out(self):
        val = self.ui.Auxout_comboBox.currentIndex()
        self.auxoutval[self.activeboard] = val
        auxoutselector(self.usbs[self.activeboard], val)

    def update_firmware(self):
        print(f"thinking about updating firmware on board {self.activeboard}")
        firmware_path = "../adc board firmware/output_files/coincidence_auto.rpd"
        if not os.path.exists(firmware_path):
            print(f"{firmware_path} was not found!")
            return

        reply = QMessageBox.question(self, "Confirmation", f"Do you really want to update the firmware with {firmware_path}?", QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
        if reply == QMessageBox.Cancel:
            print("update canceled!")
            return

        print(f"updating firmware on board {self.activeboard}")
        starttime = time.time()
        for bo in range(self.num_board): clkout_ena(self.usbs[bo], 0)

        print("erasing flash")
        flash_erase(self.usbs[self.activeboard])
        while flash_busy(self.usbs[self.activeboard], doprint=False) > 0: time.sleep(0.1)
        print("should be erased now")
        print("took",round(time.time()-starttime,3),"seconds so far")
        verifyerase=False
        if verifyerase:
            print("verifying flash erase")
            baderase=False
            readbytes = flash_readall(self.usbs[self.activeboard])
            for theb in range(len(readbytes)):
                if readbytes[theb]!=255:
                    print("byte",theb,"was",readbytes[theb])
                    baderase=True
            if not baderase: print("erase verified")
            else: return
        writtenbytes = flash_writeall_from_file(self.usbs[self.activeboard],'../adc board firmware/output_files/coincidence_auto.rpd', dowrite=True)
        print("took",round(time.time()-starttime,3),"seconds so far")
        print("verifying write")
        readbytes = flash_readall(self.usbs[self.activeboard])

        if writtenbytes == readbytes:
            print("verified!")
        else:
            print("not verified!!!")
            nbad = sum(1 for a, b in zip(writtenbytes, readbytes) if a != b)
            print(f"Found {nbad} mismatched bytes.")

        for bo in range(self.num_board): clkout_ena(self.usbs[bo], self.num_board > 1)
        print(f"Total time: {time.time() - starttime:.3f} seconds")

    def autocalibration(self, calresamp=2, dofiner=False, oldtoff=0, finewidth=16):
        if not calresamp: # called from GUI, defaults aren't filled
            calresamp = 2
            dofiner = False
            oldtoff = 0
            finewidth = 16
        print(f"autocalibration calresamp={calresamp} dofiner={dofiner} finewidth={finewidth}")
        if self.activeboard % 2 == 1:
            print("Select the even board number first!")
            return
        if self.tad[self.activeboard]!=0:
            for t in range(255//5):
                if self.tad[self.activeboard]>0: self.ui.tadBox.setValue(self.tad[self.activeboard]-5)
                self.setTAD()
                time.sleep(.1) # be gentle

        c1_idx, c_idx = self.activeboard * self.num_chan_per_board, (self.activeboard + 1) * self.num_chan_per_board
        fitwidth = (self.max_x - self.min_x) * self.fitwidthfraction
        c1data_y, c1data_x = resample(self.xydata[c1_idx][1], len(self.xydata[c1_idx][0]) * calresamp, t=self.xydata[c1_idx][0])
        cdata_y, cdata_x = resample(self.xydata[c_idx][1], len(self.xydata[c_idx][0]) * calresamp, t=self.xydata[c_idx][0])

        min_range, max_range = (-self.toff * calresamp, 10 * self.expect_samples * calresamp)
        if dofiner: min_range, max_range = (self.toff - oldtoff - finewidth) * calresamp, (self.toff - oldtoff + finewidth) * calresamp

        cdata_y = np.roll(cdata_y, int(min_range))
        min_rms, min_shift = 1e9, 0

        for nshift in range(int(min_range), int(max_range)):
            mask = (cdata_x > self.vline - fitwidth) & (cdata_x < self.vline + fitwidth)
            therms = np.std(c1data_y[mask] - cdata_y[mask]) * (1 + nshift / (20 * self.expect_samples * calresamp))
            if therms < min_rms:
                min_rms, min_shift = therms, nshift
            cdata_y = np.roll(cdata_y, 1)

        print(f"minrms found for shift = {min_shift}, toff {self.toff}, have minshift//calresamp {min_shift//calresamp}, and extra {min_shift%calresamp}/{calresamp}")
        if dofiner:
            self.toff = min_shift // calresamp + oldtoff - 1
            self.ui.ToffBox.setValue(self.toff)
            tadshift = round((138.4 * 2 / calresamp) * (min_shift % calresamp), 1)
            tadshiftround = round(tadshift + 138.4)
            print(f"should set TAD to {tadshift} + 138.4 ~= {tadshiftround}")
            if tadshiftround < 250:
                for t in range(255 // 5):
                    if abs(self.tad[self.activeboard] - tadshiftround) < 5: break
                    if self.tad[self.activeboard] < tadshiftround:
                        self.ui.tadBox.setValue(self.tad[self.activeboard] + 5)
                    else:
                        self.ui.tadBox.setValue(self.tad[self.activeboard] - 5)
                    self.set_TAD()
                    time.sleep(.1)
            else:
                self.do_phase(self.activeboard + 1, plloutnum=0, updown=1, pllnum=0)
                self.do_phase(self.activeboard + 1, plloutnum=1, updown=1, pllnum=0)
                self.do_phase(self.activeboard + 1, plloutnum=2, updown=1, pllnum=0)
                self.triggerautocalibration[self.activeboard + 1] = True
        else:
            oldtoff = self.toff
            self.toff = min_shift // calresamp + self.toff
            mask = (self.xydata[c_idx][0] > self.vline - fitwidth) & (self.xydata[c_idx][0] < self.vline + fitwidth)
            yc, yc1 = self.xydata[c_idx][1][mask], self.xydata[c1_idx][1][mask]

            extrigboardmean, otherboardmean = np.mean(yc), np.mean(yc1)
            self.extrigboardmeancorrection[self.activeboard] += extrigboardmean - otherboardmean
            extrigboardstd, otherboardstd = np.std(yc), np.std(yc1)
            if otherboardstd > 0:
                self.extrigboardstdcorrection[self.activeboard] *= extrigboardstd / otherboardstd

            print(f"calculated mean and std corrections {self.extrigboardmeancorrection[self.activeboard]}, {self.extrigboardstdcorrection[self.activeboard]}")
            self.autocalibration(64, True, oldtoff)

    def _plot_fft(self):
        y_data = self.xydatainterleaved[self.activeboard // 2][1] if self.dointerleaved[self.activeboard] else self.xydata[self.activexychannel][1]
        n = len(y_data)
        if n == 0: return

        k = np.arange(n)
        us_per_sample = self.downsamplefactor / self.samplerate / 1000.
        if self.dointerleaved[self.activeboard]: us_per_sample /= 2

        frq_range = list(range(n // 2))
        frq = (k / us_per_sample)[frq_range] / n
        Y = np.fft.fft(y_data)[frq_range] / n
        Y[0] = 0

        max_frq = np.max(frq) if len(frq) > 0 else 0
        if max_frq < 0.001:
            scale, unit, xlim = 1e6, 'Hz', 1e6 * max_frq
        elif max_frq < 1.0:
            scale, unit, xlim = 1e3, 'kHz', 1e3 * max_frq
        else:
            scale, unit, xlim = 1.0, 'MHz', max_frq

        self.fftui.fftfreqplot_xdata = frq * scale
        self.fftui.fftax_xlabel = f'Frequency ({unit})'
        self.fftui.fftax_xlim = xlim
        self.fftui.fftfreqplot_ydata = abs(Y)
        self.fftui.fftfreqplot_ydatamax = np.max(abs(Y)) if len(Y) > 0 else 1

    def _update_fft_plot(self):
        self.fftui.fftline.setPen(self.linepens[self.activexychannel])
        self.fftui.fftline.setData(self.fftui.fftfreqplot_xdata, self.fftui.fftfreqplot_ydata)
        self.fftui.ui.plot.setTitle(f'Haasoscope Pro FFT of board {self.activeboard} channel {self.selectedchannel}')
        self.fftui.ui.plot.setLabel('bottom', self.fftui.fftax_xlabel)
        self.fftui.ui.plot.setRange(xRange=(0.0, self.fftui.fftax_xlim))

        now = time.time()
        if (now - self.fftui.fftlastTime) > 3.0 or self.fftui.fftyrange < self.fftui.fftfreqplot_ydatamax * 1.1:
            self.fftui.fftlastTime = now
            self.fftui.fftyrange = self.fftui.fftfreqplot_ydatamax * 1.1
            self.fftui.ui.plot.setRange(yRange=(0.0, self.fftui.fftyrange))

        if not self.fftui.isVisible():
            self.dofft = False
            self.ui.fftCheck.setChecked(False)

    def _on_fast_adc_line_click(self, curve):
        for li, line in enumerate(self.lines):
            if curve is line.curve:
                self.ui.chanBox.setValue(li % self.num_chan_per_board)
                self.ui.boardBox.setValue(li // self.num_chan_per_board)
                break

    def use_ext_trigs(self):
        for board in range(1, self.num_board):
            self.ui.boardBox.setValue(board)
            self.ext_trig(True)
            if clockused(self.usbs[board], board, False) == 0:
                switchclock(self.usbs[board], board)
            assert clockused(self.usbs[board], board, False) == 1
        self.ui.boardBox.setValue(0)

    def launch(self):
        self.nlines = self.num_chan_per_board * self.num_board
        colors = cm.rainbow(np.linspace(1.0, 0.1, self.nlines))

        for chan in range(self.nlines):
            color = QColor.fromRgbF(*colors[chan])
            pen = pg.mkPen(color=color)
            line = self.ui.plot.plot(pen=pen, name=f"Chan {chan}")
            line.curve.setClickable(True)
            line.curve.sigClicked.connect(self._on_fast_adc_line_click)
            self.lines.append(line)
            self.linepens.append(pen)

        for c in range(self.nlines):
            if c % 2 == 1: self.lines[c].setVisible(self.dotwochannel)

        self.ui.chanBox.setMaximum(self.num_chan_per_board - 1 if self.dotwochannel else 0)
        self.ui.boardBox.setMaximum(self.num_board - 1)

        pen = pg.mkPen(color="w", style=QtCore.Qt.DashLine)
        self.otherlines.append(self.ui.plot.plot([0, 0], [-2, 2], pen=pen))  # V-line
        self.otherlines.append(self.ui.plot.plot([-2, 2], [0, 0], pen=pen))  # H-line

        self.ui.plot.setLabel('left', "Voltage (divisions)")
        self.ui.plot.getAxis("left").setTickSpacing(1, 0.1)
        self.ui.plot.setBackground(QColor('black'))
        self.ui.plot.showGrid(x=True, y=True)
        for usb in self.usbs: self.tell_downsample(usb, 0)

    def setup_connection(self, board):
        print(f"Setting up board {board}")
        ver = version(self.usbs[board], False)
        if self.firmwareversion is None:
            self.firmwareversion = ver
        elif ver < self.firmwareversion:
            print("Warning - this board has older firmware than another being used!")
            self.firmwareversion = ver

        self.adf_reset(board)
        setupboard(self.usbs[board], self.dopattern, self.dotwochannel, self.dooverrange)
        for c in range(self.num_chan_per_board):
            setchanacdc(self.usbs[board], c, 0, self.dooversample[board])
            setchanimpedance(self.usbs[board], c, 0, self.dooversample[board])
            setchanatt(self.usbs[board], c, 0, self.dooversample[board])
        setsplit(self.usbs[board], False)
        self.pll_reset(board)
        auxoutselector(self.usbs[board], 0)
        return True

    def open_socket(self):
        print("starting socket thread")
        self.hsprosock = hspro_socket()
        self.hsprosock.hspro = self
        self.hsprosock.runthethread = True
        self.hsprosock_t1 = threading.Thread(target=self.hsprosock.open_socket, args=(10,))
        self.hsprosock_t1.start()

    def close_socket(self):
        if self.hsprosock: self.hsprosock.runthethread = False
        if self.hsprosock_t1: self.hsprosock_t1.join()

    def do_leds(self):
        for board in range(self.num_board):
            col1 = self.linepens[board * self.num_chan_per_board].color()
            r1, g1, b1 = col1.red(), col1.green(), col1.blue()
            r2, g2, b2 = 0, 0, 0

            if self.dotwochannel:
                col2 = self.linepens[board * self.num_chan_per_board + 1].color()
                r2, g2, b2 = col2.red(), col2.green(), col2.blue()
            if self.dooversample[board]:
                r2, g2, b2 = r1, g1, b1
                r1, g1, b1 = 0, 0, 0
            if self.dointerleaved[board] and board % 2 == 1:
                col1_inter = self.linepens[(board - 1) * self.num_chan_per_board].color()
                dim = 10
                r2, g2, b2 = col1_inter.red() / dim, col1_inter.green() / dim, col1_inter.blue() / dim

            send_leds(self.usbs[board], r1, g1, b1, r2, g2, b2)

    def setup_channels(self):
        if hasattr(self, "hsprosock") and self.hsprosock:
            while self.hsprosock.issending: time.sleep(0.001)

        total_chans = self.num_chan_per_board * self.num_board
        if self.dotwochannel:
            self.xydata = np.empty([total_chans, 2, 2 * 10 * self.expect_samples], dtype=float)
        else:
            self.xydata = np.empty([total_chans, 2, 4 * 10 * self.expect_samples], dtype=float)
            self.xydatainterleaved = np.empty([total_chans, 2, 8 * 10 * self.expect_samples], dtype=float)

    def closeEvent(self, event):
        print("Handling closeEvent")
        self.close_socket()
        self.timer.stop()
        self.timer2.stop()
        if self.dorecordtofile and self.outf: self.outf.close()
        if self.fftui: self.fftui.close()
        for usb in self.usbs: cleanup(usb)
        if event: event.accept()


def cleanup_and_exit(usbs, exit_code):
    """Clean up USB resources and exit the application."""
    for usb in usbs: cleanup(usb)
    sys.exit(exit_code)
