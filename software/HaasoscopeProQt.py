import math
import os.path
import numpy as np
import sys, time, warnings
from collections import deque
import pyqtgraph as pg
import PyQt5
from pyqtgraph.Qt import QtCore, QtWidgets, loadUiType
from PyQt5.QtGui import QPalette, QColor, QIcon
from PyQt5.QtWidgets import QApplication, QMessageBox, QWidget, QPushButton, QFrame
from scipy.optimize import curve_fit
from scipy.signal import resample
from scipy.interpolate import interp1d
import struct
from usbs import *
from board import *
from SCPIsocket import hspro_socket
from datetime import datetime
import threading
import matplotlib.cm as cm

# Look for special paths when double-clicking on the pre-made exe, so we can find the .ui files
path_string = sys.path[0]
pwd = path_string # it will be the current direct directory already if we are running from the command line
target = ["Mac_HaasoscopeProQt", "Windows_HaasoscopeProQt"]
for tar in target:
    index = path_string.find(tar)
    if index != -1: # The substring was found
        index_with_target = index + len(tar)
        pwd = path_string[:index_with_target]
print("Current dir is "+pwd)

usbs = connectdevices(100) # max of 100 devices
#if len(usbs)==0: sys.exit(0)
for b in range(len(usbs)):
    if len(usbs) > 1: clkout_ena(usbs[b], 1) # turn on lvdsout_clk for boards
    version(usbs[b])
    version(usbs[b])
    version(usbs[b])
time.sleep(.1) # wait for clocks to lock
usbs = orderusbs(usbs)
tellfirstandlast(usbs)

# Define fft window class from template
FFTWindowTemplate, FFTTemplateBaseClass = loadUiType(pwd+"/HaasoscopeProFFT.ui")
class FFTWindow(FFTTemplateBaseClass):
    def __init__(self):
        FFTTemplateBaseClass.__init__(self)
        self.ui = FFTWindowTemplate()
        self.ui.setupUi(self)
        self.ui.actionTake_screenshot.triggered.connect(self.take_screenshot)
        self.ui.actionLog_scale.triggered.connect(self.log_scale)
        self.ui.plot.setLabel('bottom', 'Frequency (MHz)')
        self.ui.plot.setLabel('left', 'Amplitude')
        self.ui.plot.showGrid(x=True, y=True, alpha=1)
        #self.ui.plot.setRange(xRange=(0.0, 1600.0))
        self.ui.plot.setBackground(QColor('black'))
        c = (10, 10, 10)
        self.fftpen = pg.mkPen(color=c) # width=2 slower
        self.fftline = self.ui.plot.plot(pen=self.fftpen, name="fft_plot", skipFiniteCheck=True, connect="finite")
        self.fftlastTime = time.time() - 10
        self.fftyrange = 1
        self.fftyrangelow = 1e-10
        self.dolog = False
        self.newplot = True

    def take_screenshot(self):
        # Capture the entire FFT window
        pixmap = self.grab()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"HaasoscopePro_FFT_{timestamp}.png"
        pixmap.save(filename)
        print(f"Screenshot saved as {filename}")

    def log_scale(self):
        self.dolog = self.ui.actionLog_scale.isChecked()
        self.ui.plot.setLogMode(x=False, y=self.dolog)
        self.newplot = True
        if self.dolog: self.ui.plot.setLabel('left', 'log10 Amplitude')
        else: self.ui.plot.setLabel('left', 'Amplitude')

# Define main window class from template
WindowTemplate, TemplateBaseClass = loadUiType(pwd+"/HaasoscopePro.ui")
class MainWindow(TemplateBaseClass):

    expect_samples = 100
    expect_samples_extra = 5 # enough to cover downsample shifting and toff shifting
    samplerate = 3.2  # freq in GHz
    nsunits = 1
    num_board = len(usbs)
    num_chan_per_board = 2
    num_logic_inputs = 0
    firmwareversion = -1
    debug = False
    dopattern = 0 # set to 4 to do max varying test pattern
    debugprint = True
    showbinarydata = True
    debugstrobe = False
    debug_trigger_phase = False
    dofast = False
    dotwochannel = False
    dointerleaved = [False] * num_board
    dooverrange = False
    total_rx_len = 0
    time_start = time.time()
    triggertype = 1
    isrolling = 0
    selectedchannel = 0
    activeboard = 0
    activexychannel = 0
    tad = [0] * num_board
    toff = 50
    triggershift = 2 # amount to shift trigger earlier, so we have time to shift later on for toff etc.
    themuxoutV = True
    phasecs = []
    for ph in range(len(usbs)): phasecs.append([[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]])
    phaseoffset = 0 # how many positive phase steps to take from middle of good range
    doexttrig = [0] * num_board
    doextsmatrig = [0] * num_board
    paused = True # will unpause with dostartstop at startup
    downsample = 0
    downsamplefactor = 1
    highresval = 1
    xscale = 1
    xscaling = 1
    yscale = 3.3/2.03 * 10*5/8 / pow(2,12) /16 # this is the size of 1 bit, so that 2^12 bits fill the 10.x divisions on the screen
    min_y = -5 # -pow(2, 11) * yscale
    max_y = 5 # pow(2, 11) * yscale
    min_x = 0
    max_x = 4 * 10 * expect_samples * downsamplefactor / nsunits / samplerate
    xydata = 0
    xydatainterleaved = 0
    fftui = 0
    downsamplezoom = 1
    triggerlevel = 127
    triggerdelta = 1
    triggerpos = int(expect_samples * 128 / 256)
    triggertimethresh = 0
    triggerchan = [0] * num_board
    hline = 0
    vline = 0
    getone = False
    downsamplemerging = 1
    units = "ns"
    dodrawing = True
    chtext = ""
    linepens = []
    nlines = 0
    statuscounter = 0
    nevents = 0
    oldnevents = 0
    tinterval = 100.
    oldtime = time.time()
    nbadclkA = 0
    nbadclkB = 0
    nbadclkC = 0
    nbadclkD = 0
    nbadstr = 0
    eventcounter = [0] * num_board
    nsubsamples = 10 * 4 + 8 + 2  # extra 4+4 for clk+str, and 2 clkstrprob beef
    sample_triggered = [0] * num_board
    triggerphase = [0] * num_board
    downsamplemergingcounter = [0] * num_board
    fitwidthfraction = 0.2
    extrigboardstdcorrection = [1] * num_board
    extrigboardmeancorrection = [0] * num_board
    lastrate = 0
    lastsize = 0
    VperD = [0.16]*(num_board*2)
    plljustreset = [-10] * num_board
    plljustresetdir = [0] * num_board
    phasenbad = [[0] * 12] * num_board
    dooversample = [False] * num_board
    doresamp = 4
    triggerautocalibration = [False] * num_board
    extraphasefortad = [0] * num_board
    doexttrigecho = [False] * num_board
    oldeventcounterdiff = -9999
    doeventcounter = False
    oldeventtime = -9999
    doeventtime = False
    distcorr = [0]*num_board
    totdistcorr = [0]*num_board
    lvdstrigdelay = [0] * num_board
    lastlvdstrigdelay = [0] * num_board
    acdc = [False]*(num_board*num_chan_per_board)
    mohm = [False]*(num_board*num_chan_per_board)
    att = [False]*(num_board*num_chan_per_board)
    tenx = [1]*(num_board*num_chan_per_board)
    auxoutval = [0]*num_board
    offset = [0]*(num_board*num_chan_per_board)
    gain = [0]*(num_board*num_chan_per_board)
    noextboard = -1

    def __init__(self):
        TemplateBaseClass.__init__(self)
        self.ui = WindowTemplate()
        self.ui.setupUi(self)
        self.ui.runButton.clicked.connect(self.dostartstop)
        self.ui.threshold.valueChanged.connect(self.triggerlevelchanged)
        self.ui.thresholdDelta.valueChanged.connect(self.triggerdeltachanged)
        self.ui.thresholdPos.valueChanged.connect(self.triggerposchanged)
        self.ui.rollingButton.clicked.connect(self.rolling)
        self.ui.singleButton.clicked.connect(self.single)
        self.ui.timeslowButton.clicked.connect(self.timeslow)
        self.ui.timefastButton.clicked.connect(self.timefast)
        self.ui.risingfalling_comboBox.currentIndexChanged.connect(self.risingfalling)
        self.ui.exttrigCheck.stateChanged.connect(self.exttrig)
        self.ui.extsmatrigCheck.stateChanged.connect(self.extsmatrig)
        self.ui.totBox.valueChanged.connect(self.tot)
        self.ui.depthBox.valueChanged.connect(self.depth)
        self.ui.boardBox.valueChanged.connect(self.boardchanged)
        self.ui.trigchan_comboBox.currentIndexChanged.connect(self.triggerchanchanged)
        self.ui.actionGrid.triggered.connect(self.grid)
        self.ui.markerCheck.stateChanged.connect(self.marker)
        self.ui.highresCheck.stateChanged.connect(self.highres)
        self.ui.pllresetButton.clicked.connect(self.pllreset)
        self.ui.actionClock_reset.triggered.connect(self.adfreset)
        self.ui.upposButton0.clicked.connect(self.uppos)
        self.ui.downposButton0.clicked.connect(self.downpos)
        self.ui.upposButton1.clicked.connect(self.uppos1)
        self.ui.downposButton1.clicked.connect(self.downpos1)
        self.ui.upposButton2.clicked.connect(self.uppos2)
        self.ui.downposButton2.clicked.connect(self.downpos2)
        self.ui.upposButton3.clicked.connect(self.uppos3)
        self.ui.downposButton3.clicked.connect(self.downpos3)
        self.ui.upposButton4.clicked.connect(self.uppos4)
        self.ui.downposButton4.clicked.connect(self.downpos4)
        self.ui.chanBox.valueChanged.connect(self.selectchannel)
        self.ui.gainBox.valueChanged.connect(self.changegain)
        self.ui.offsetBox.valueChanged.connect(self.changeoffset)
        self.ui.acdcCheck.stateChanged.connect(self.setacdc)
        self.ui.ohmCheck.stateChanged.connect(self.setmohm)
        self.ui.oversampCheck.stateChanged.connect(self.setoversamp)
        self.ui.interleavedCheck.stateChanged.connect(self.interleave)
        self.ui.attCheck.stateChanged.connect(self.setatt)
        self.ui.tenxCheck.stateChanged.connect(self.settenx)
        self.ui.chanonCheck.stateChanged.connect(self.chanon)
        self.ui.actionDrawing.triggered.connect(self.drawing)
        self.ui.wideCheck.clicked.connect(self.wideline)
        self.ui.fwfBox.valueChanged.connect(self.fwf)
        self.ui.tadBox.valueChanged.connect(self.setTAD)
        self.ui.resampBox.valueChanged.connect(self.resamp)
        self.ui.twochanCheck.clicked.connect(self.twochan)
        self.ui.ToffBox.valueChanged.connect(self.setToff)
        self.ui.fftCheck.clicked.connect(self.fft)
        self.ui.actionTake_screenshot.triggered.connect(self.take_screenshot)
        self.ui.actionDo_autocalibration.triggered.connect(self.autocalibration)
        self.ui.actionUpdate_firmware.triggered.connect(self.update_firmware)
        self.ui.actionForce_split.triggered.connect( self.force_split )
        self.ui.actionForce_switch_clocks.triggered.connect( self.force_switch_clocks )
        self.ui.Auxout_comboBox.currentIndexChanged.connect(self.auxout)
        self.ui.actionToggle_PLL_controls.triggered.connect(self.toggle_pll_controls)
        self.ui.actionRecord.triggered.connect(self.recordtofile)
        self.ui.actionAbout.triggered.connect(self.about)
        self.ui.actionOversampling_mean_and_RMS.triggered.connect(self.do_meanrms_calibration)
        self.dofft = False
        self.db = False
        self.lastTime = time.time()
        self.fps = None
        self.lastclk = -1
        self.lines = []
        self.otherlines = []
        self.dorecordtofile = False  # save scope data to file
        self.numrecordeventsperfile = 1000  # number of events in each file to record before opening new file
        self.timer = QtCore.QTimer()
        # noinspection PyUnresolvedReferences
        self.timer.timeout.connect(self.updateplot)
        self.timer2 = QtCore.QTimer()
        # noinspection PyUnresolvedReferences
        self.timer2.timeout.connect(self.drawtext)
        self.ui.statusBar.showMessage(str(self.num_board)+" boards connected!")
        self.ui.trigchan_comboBox.setMaxVisibleItems(1)
        self.max_persist_lines = 16
        self.persist_time = 0 # ms for each line to live
        self.persist_lines = deque(maxlen=self.max_persist_lines)
        self.persist_timer = QtCore.QTimer()
        self.persist_timer.timeout.connect(self.update_persist_effect)
        self.ui.persistTbox.valueChanged.connect(self.persist)
        self.show()

    def about(self):
        QMessageBox.about(
            self,  # Parent widget (optional, but good practice)
            "Haasoscope Pro Qt, by DrAndyHaas",  # Title of the About dialog
            "A PyQt5 application for the Haasoscope Pro\n\nVersion 29.06"  # Text content
        )

    def persist(self):
        self.persist_time = 50*pow(2,self.ui.persistTbox.value())
        if self.ui.persistTbox.value()==0: self.persist_time=0
        if self.persist_time>0: self.persist_timer.start(50) # ms
        self.ui.persistText.setText(str(self.persist_time/1000)+" s")

    def update_persist_effect(self):
        """Updates the alpha/transparency of the persistent lines."""
        if len(self.persist_lines)==0 and self.persist_time==0: self.persist_timer.stop()
        current_time = time.time()
        for item, creation_time, li in list(self.persist_lines):
            age = (current_time - creation_time) * 1000.
            if age > self.persist_time: # this line is too old, though the deque should handle removal as new events come in
                # as a fallback, remove it here
                self.ui.plot.removeItem(item)
                self.persist_lines.remove((item, creation_time, li))
                #alpha = 0
            else:
                # Calculate alpha based on age (linear fade)
                alpha = int(255 * (1 - (age / self.persist_time)))
                pen = self.linepens[li]
                color = pen.color()
                color.setAlpha(alpha)
                new_pen = pg.mkPen(color, width=pen.width())
                item.setPen(new_pen)

    def recordtofile(self):
        self.dorecordtofile = not self.dorecordtofile
        if self.dorecordtofile:
            fname = "HaasoscopePro_out_" + time.strftime("%Y%m%d-%H%M%S") + ".csv"
            self.outf = open(fname, "wt")
            self.outf.write("Event #, Time (s), Channel, Trigger time (ns), Sample period (ns), # samples")
            evtstr = ""
            for s in range( (2 if self.dotwochannel else 4) *10*self.expect_samples): evtstr += " , Sample "+str(s)
            self.outf.write(evtstr+"\n")
            self.ui.actionRecord.setText("Stop recording")
        else:
            self.outf.close()
            self.ui.actionRecord.setText("Record to file")

    def force_split(self):
        setsplit(usbs[self.activeboard], self.ui.actionForce_split.isChecked())

    def force_switch_clocks(self):
        switchclock(usbs[self.activeboard], self.activeboard)

    def toggle_pll_controls(self):
        self.ui.upposButton0.setEnabled(not self.ui.pllBox.isEnabled())
        self.ui.upposButton1.setEnabled(not self.ui.pllBox.isEnabled())
        self.ui.upposButton2.setEnabled(not self.ui.pllBox.isEnabled())
        self.ui.upposButton3.setEnabled(not self.ui.pllBox.isEnabled())
        self.ui.upposButton4.setEnabled(not self.ui.pllBox.isEnabled())
        self.ui.downposButton0.setEnabled(not self.ui.pllBox.isEnabled())
        self.ui.downposButton1.setEnabled(not self.ui.pllBox.isEnabled())
        self.ui.downposButton2.setEnabled(not self.ui.pllBox.isEnabled())
        self.ui.downposButton3.setEnabled(not self.ui.pllBox.isEnabled())
        self.ui.downposButton4.setEnabled(not self.ui.pllBox.isEnabled())
        self.ui.pllBox.setEnabled(not self.ui.pllBox.isEnabled())

    def boardchanged(self):
        self.activeboard = self.ui.boardBox.value()
        self.selectchannel()

    def set_channel_frame(self):
        if self.doexttrig[self.activeboard] or self.doextsmatrig[self.activeboard] or self.triggerchan[self.activeboard]!=self.activexychannel%2: self.ui.chanColor.setFrameStyle(QFrame.NoFrame)
        else: self.ui.chanColor.setFrameStyle(QFrame.Box)

    def selectchannel(self):
        if self.num_board==0: return
        if self.activeboard%2==0 and not self.dotwochannel and self.num_board>1:
            self.ui.oversampCheck.setEnabled(True)
            if self.dooversample[self.activeboard]:
                self.ui.interleavedCheck.setEnabled(True)
                self.ui.oversampCheck.setChecked(True)
                self.ui.interleavedCheck.setChecked(self.dointerleaved[self.activeboard])
            else:
                self.ui.interleavedCheck.setEnabled(False)
                self.ui.interleavedCheck.setChecked(False)
                self.ui.oversampCheck.setChecked(False)
        else:
            self.ui.oversampCheck.setEnabled(False)
            self.ui.interleavedCheck.setEnabled(False)
        if self.doexttrig[self.activeboard]:
            self.ui.exttrigCheck.setChecked(True)
            self.ui.extsmatrigCheck.setEnabled(False)
        else:
            self.ui.exttrigCheck.setChecked(False)
            self.ui.extsmatrigCheck.setEnabled(True)
        if self.doextsmatrig[self.activeboard]:
            self.ui.extsmatrigCheck.setChecked(True)
            self.ui.exttrigCheck.setEnabled(False)
        else:
            self.ui.extsmatrigCheck.setChecked(False)
            self.ui.exttrigCheck.setEnabled(True)
        self.selectedchannel = self.ui.chanBox.value()
        self.activexychannel = self.activeboard*self.num_chan_per_board + self.selectedchannel
        p = self.ui.chanColor.palette()
        col = self.linepens[self.activexychannel].color()
        if self.activeboard%2==1 and self.dointerleaved[self.activeboard]:
            col = self.linepens[self.activexychannel-self.num_chan_per_board].color().darker(200)
        p.setColor(QPalette.Base, col)  # Set background color of box
        self.ui.chanColor.setPalette(p)
        self.set_channel_frame()
        if self.lines[self.activexychannel].isVisible():
            self.ui.chanonCheck.setChecked(QtCore.Qt.Checked)
        else:
            self.ui.chanonCheck.setChecked(QtCore.Qt.Unchecked)
        self.ui.tadBox.setValue(self.tad[self.activeboard])
        self.ui.acdcCheck.setChecked(self.acdc[self.activexychannel])
        self.ui.ohmCheck.setChecked(self.mohm[self.activexychannel])
        self.ui.tenxCheck.setChecked(self.tenx[self.activexychannel]==10)
        self.ui.attCheck.setChecked(self.att[self.activexychannel])
        self.ui.Auxout_comboBox.setCurrentIndex(self.auxoutval[self.activeboard])
        self.ui.offsetBox.setValue(self.offset[self.activexychannel])
        self.ui.gainBox.setValue(self.gain[self.activexychannel])
        self.ui.trigchan_comboBox.setCurrentIndex(self.triggerchan[self.activeboard] if self.dotwochannel else 0)

    def fft(self):
        if self.ui.fftCheck.checkState() == QtCore.Qt.Checked:
            self.fftui = FFTWindow()
            self.fftui.setWindowTitle('Haasoscope Pro FFT of board '+str(self.activeboard)+' channel ' + str(self.selectedchannel))
            self.fftui.show()
            self.dofft = True
        else:
            self.fftui.close()
            self.dofft = False

    def resamp(self, value):
        self.doresamp = value

    def twochan(self):
        self.dotwochannel = self.ui.twochanCheck.checkState() == QtCore.Qt.Checked
        if self.dorecordtofile:  # if writing, close and open new file, by calling recordtofile() twice, since the number of samples per event for each channel will change
            self.recordtofile()
            self.recordtofile()
        for bo in range(self.num_board):
            for ch in range(self.num_chan_per_board):
                setchanatt(usbs[bo], ch, self.dotwochannel, self.dooversample[bo])  # turn on/off antialias for two/single channel mode
        self.ui.attCheck.setChecked(self.dotwochannel)
        self.att = [self.dotwochannel]*(self.num_board*self.num_chan_per_board)
        self.setupchannels()
        self.doleds()
        for usb in usbs: setupboard(usb,self.dopattern,self.dotwochannel,self.dooverrange)
        for usb in usbs: self.telldownsample(usb, self.downsample)
        self.timechanged()
        if self.dotwochannel:
            self.ui.chanBox.setMaximum(self.num_chan_per_board - 1)
            self.ui.oversampCheck.setEnabled(False)
            self.ui.trigchan_comboBox.setMaxVisibleItems(2)
        else:
            self.ui.chanBox.setMaximum(0)
            if self.activeboard%2==0 and self.num_board>1: self.ui.oversampCheck.setEnabled(True)
            self.ui.trigchan_comboBox.setCurrentIndex(0)
            self.ui.trigchan_comboBox.setMaxVisibleItems(1)
        for c in range(self.num_board*self.num_chan_per_board):
            if c%2==1:
                if self.dotwochannel: self.lines[c].setVisible(True)
                else: self.lines[c].setVisible(False)

    def changeoffset(self):
        self.offset[self.activexychannel] = self.ui.offsetBox.value() # remember it
        scaling = 1000*self.VperD[self.activeboard*2+self.selectedchannel]/160 # compare to 0 dB gain
        if self.ui.acdcCheck.checkState() == QtCore.Qt.Checked: scaling *= 245/160 # offset gain is different in AC mode
        if dooffset(usbs[self.activeboard], self.selectedchannel, self.ui.offsetBox.value(),scaling/self.tenx[self.activexychannel],self.dooversample[self.activeboard]):
            if self.dooversample[self.activeboard] and self.ui.boardBox.value()%2==0: # also adjust other board we're oversampling with
                dooffset(usbs[self.ui.boardBox.value()+1], self.selectedchannel, self.ui.offsetBox.value(),scaling/self.tenx[self.activexychannel],self.dooversample[self.activeboard])
                self.offset[self.activexychannel+self.num_chan_per_board] = self.ui.offsetBox.value()  # remember it
            v2 = scaling*1.5*self.ui.offsetBox.value()
            if self.dooversample[self.activeboard]: v2 *= 2.0
            if self.ui.acdcCheck.checkState() == QtCore.Qt.Checked: v2*=(160/245) # offset gain is different in AC mode
            self.ui.Voff.setText(str(int(v2))+" mV")

    def changegain(self):
        self.gain[self.activexychannel] = self.ui.gainBox.value() # remember it
        setgain(usbs[self.activeboard], self.selectedchannel, self.ui.gainBox.value(),self.dooversample[self.activeboard])
        if self.dooversample[self.activeboard] and self.ui.boardBox.value()%2==0: # also adjust other board we're oversampling with
            setgain(usbs[self.ui.boardBox.value()+1], self.selectedchannel, self.ui.gainBox.value(),self.dooversample[self.activeboard])
            self.gain[self.activexychannel+self.num_chan_per_board] = self.ui.gainBox.value()  # remember it
        db = self.ui.gainBox.value()
        v2 = 0.1605*self.tenx[self.activexychannel]/pow(10, db / 20.) # 0.16 V at 0 dB gain
        if self.dooversample[self.activeboard]: v2 *= 2.0
        oldvperd = self.VperD[self.activeboard*2+self.selectedchannel]
        self.VperD[self.activeboard*2+self.selectedchannel] = v2
        if self.dooversample[self.activeboard] and self.ui.boardBox.value()%2==0: # also adjust other board we're oversampling with
            self.VperD[(self.activeboard+1)*2+self.selectedchannel] = v2
        self.ui.offsetBox.setValue(int(self.ui.offsetBox.value()*oldvperd/v2))
        v2 = round(1000*v2,0)
        self.ui.VperD.setText(str(int(v2))+" mV/div")
        if self.ui.gainBox.value()>24: self.ui.gainBox.setSingleStep(2)
        else: self.ui.gainBox.setSingleStep(6)

    def fwf(self):
        self.fitwidthfraction = self.ui.fwfBox.value() / 100.

    def setTAD(self):
        # if self.tad<0 and self.ui.tadBox.value()>=0:
        #     spicommand(usbs[self.activeboard], "TAD", 0x02, 0xB7, 0, False, quiet=False)
        # if self.tad>=0 and self.ui.tadBox.value()<0:
        #     spicommand(usbs[self.activeboard], "TAD", 0x02, 0xB7, 1, False, quiet=False)
        self.tad[self.activeboard] = self.ui.tadBox.value()
        spicommand(usbs[self.activeboard], "TAD", 0x02, 0xB6, abs(self.tad[self.activeboard]), False, quiet=True)
        adjustphaseforTAD = False
        if adjustphaseforTAD:
            if self.tad[self.activeboard]>135:
                if not self.extraphasefortad[self.activeboard]:
                    self.dophase(self.activeboard, plloutnum=0, updown=1, pllnum=0) # adjust up one, to account for phase offset of TAD
                    self.dophase(self.activeboard, plloutnum=1, updown=1, pllnum=0)
                    self.extraphasefortad[self.activeboard]+=1
                    print("extra phase for TAD>135 now",self.extraphasefortad[self.activeboard])
            else:
                if self.extraphasefortad[self.activeboard]:
                    self.dophase(self.activeboard, plloutnum=0, updown=0, pllnum=0) # adjust down one, to not account for phase offset of TAD
                    self.dophase(self.activeboard, plloutnum=1, updown=0, pllnum=0)
                    self.extraphasefortad[self.activeboard]-=1
                    print("extra phase for TAD>135 now",self.extraphasefortad[self.activeboard])

    def setToff(self):
        self.toff = self.ui.ToffBox.value()

    def adfreset(self, board):
        if not board: board=self.activeboard # if called by pressing button
        usb = usbs[board]
        # adf4350(150.0, None, 10) # need larger rcounter for low freq
        adf4350(usb, self.samplerate * 1000 / 2, None, themuxout=self.themuxoutV)
        time.sleep(0.1)
        res = boardinbits(usb)
        if not getbit(res, 5): print("Adf pll for board",board,"not locked?")  # should be 1 if locked
        else: print("Adf pll locked for board",board)

    def chanon(self):
        if self.ui.chanonCheck.checkState() == QtCore.Qt.Checked:
            self.lines[self.activexychannel].setVisible(True)
        else:
            self.lines[self.activexychannel].setVisible(False)

    def setacdc(self):
        self.acdc[self.activexychannel] = self.ui.acdcCheck.checkState() == QtCore.Qt.Checked # remember it
        setchanacdc(usbs[self.activeboard], self.selectedchannel,
                    self.ui.acdcCheck.checkState() == QtCore.Qt.Checked, self.dooversample[self.activeboard])  # will be True for AC, False for DC
        self.changeoffset() # because offset gain is different in AC mode
        if self.dooversample[self.activeboard] and self.activeboard%2==0:  # also adjust other board we're oversampling with
            setchanacdc(usbs[self.activeboard+1], self.selectedchannel,
                    self.ui.acdcCheck.checkState() == QtCore.Qt.Checked, self.dooversample[self.activeboard])
            self.acdc[self.activexychannel+self.num_chan_per_board] = self.ui.acdcCheck.checkState() == QtCore.Qt.Checked  # remember it

    def setmohm(self):
        self.mohm[self.activexychannel] = self.ui.ohmCheck.checkState() == QtCore.Qt.Checked # remember it
        setchanimpedance(usbs[self.activeboard], self.selectedchannel,
                         self.ui.ohmCheck.checkState() == QtCore.Qt.Checked, self.dooversample[self.activeboard])  # will be True for 1M ohm, False for 50 ohm

    def setatt(self):
        self.att[self.activexychannel] = self.ui.attCheck.checkState() == QtCore.Qt.Checked # remember it
        setchanatt(usbs[self.activeboard], self.selectedchannel,
                   self.ui.attCheck.checkState() == QtCore.Qt.Checked, self.dooversample[self.activeboard])  # will be True for attenuation on
        if self.dooversample[self.activeboard] and self.activeboard%2==0:  # also adjust other board we're oversampling with
            setchanatt(usbs[self.activeboard+1], self.selectedchannel,
                       self.ui.attCheck.checkState() == QtCore.Qt.Checked, self.dooversample[self.activeboard])
            self.att[self.activexychannel+self.num_chan_per_board] = self.ui.attCheck.checkState() == QtCore.Qt.Checked  # remember it

    def settenx(self):
        if self.ui.tenxCheck.checkState() == QtCore.Qt.Checked: self.tenx[self.activexychannel] = 10
        else: self.tenx[self.activexychannel] = 1
        self.changegain()
        self.changeoffset()

    def setoversamp(self):
        assert self.activeboard%2==0
        assert self.num_board>1
        self.dooversample[self.activeboard] = self.ui.oversampCheck.checkState() == QtCore.Qt.Checked # will be True for oversampling, False otherwise
        self.dooversample[self.activeboard+1] = self.ui.oversampCheck.checkState() == QtCore.Qt.Checked # will be True for oversampling, False otherwise
        setsplit(usbs[self.activeboard],self.dooversample[self.activeboard])
        setsplit(usbs[self.activeboard+1], False)
        for bo in range(self.num_board):
            if bo==self.activeboard or bo==self.activeboard+1: swapinputs(usbs[bo],self.dooversample[self.activeboard])
        if self.dooversample[self.activeboard]:
            self.ui.interleavedCheck.setEnabled(True)
            self.ui.twochanCheck.setEnabled(False)
        else:
            self.ui.interleavedCheck.setEnabled(False)
            self.ui.interleavedCheck.setChecked(False)
            self.ui.twochanCheck.setEnabled(True)
        self.changegain()
        self.changeoffset()
        self.doleds()

    def interleave(self):
        assert self.activeboard%2==0
        assert self.num_board>1
        self.dointerleaved[self.activeboard] = self.ui.interleavedCheck.checkState() == QtCore.Qt.Checked
        self.dointerleaved[self.activeboard+1] = self.ui.interleavedCheck.checkState() == QtCore.Qt.Checked
        c = (self.activeboard+1) * self.num_chan_per_board
        if self.dointerleaved[self.activeboard]:
            self.lines[c].setVisible(False)
            #self.ui.boardBox.setMaximum(int(self.num_board/2)-1)
        else:
            self.lines[c].setVisible(True)
            #self.ui.boardBox.setMaximum(self.num_board-1)
        self.selectchannel()
        self.timechanged()
        self.doleds()

    def dophase(self, board, plloutnum, updown, pllnum=None, quiet=False):
        # for 3rd byte, 000:all 001:M 010=2:C0 011=3:C1 100=4:C2 101=5:C3 110=6:C4
        # for 4th byte, 1 is up, 0 is down
        if pllnum is None: pllnum = int(self.ui.pllBox.value())
        usbs[board].send(bytes([6, pllnum, int(plloutnum + 2), updown, 100, 100, 100, 100]))
        if updown:
            self.phasecs[board][pllnum][plloutnum] = self.phasecs[board][pllnum][plloutnum] + 1
        else:
            self.phasecs[board][pllnum][plloutnum] = self.phasecs[board][pllnum][plloutnum] - 1
        if not quiet: print("phase for pllnum", pllnum, "plloutnum", plloutnum, "on board", board, "now",
                            self.phasecs[board][pllnum][plloutnum])

    def uppos(self):
        self.dophase(self.activeboard, plloutnum=0, updown=1)

    def uppos1(self):
        self.dophase(self.activeboard, plloutnum=1, updown=1)

    def uppos2(self):
        self.dophase(self.activeboard, plloutnum=2, updown=1)

    def uppos3(self):
        self.dophase(self.activeboard, plloutnum=3, updown=1)

    def uppos4(self):
        self.dophase(self.activeboard, plloutnum=4, updown=1)

    def downpos(self):
        self.dophase(self.activeboard, plloutnum=0, updown=0)

    def downpos1(self):
        self.dophase(self.activeboard, plloutnum=1, updown=0)

    def downpos2(self):
        self.dophase(self.activeboard, plloutnum=2, updown=0)

    def downpos3(self):
        self.dophase(self.activeboard, plloutnum=3, updown=0)

    def downpos4(self):
        self.dophase(self.activeboard, plloutnum=4, updown=0)

    def pllreset(self, board):
        if not board: board = self.activeboard # if we called it from the button
        usbs[board].send(bytes([5, 99, 99, 99, 100, 100, 100, 100]))
        usbs[board].recv(4)
        print("Pllreset sent to board",board)
        self.phasecs[board] = [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]]  # reset counters
        self.plljustreset[board] = 0
        self.plljustresetdir[board] = 1
        self.phasenbad[board] = [0]*12 # reset nbad counters
        self.expect_samples = 1000
        self.dodrawing = False
        #switchclock(usbs,board)
        if self.num_board>1 and self.doexttrig[board]: self.doexttrigecho[board] = True
        #CALLBACK is to adjustclocks, below, which runs for each event and then finishes up at the end of that function

    def adjustclocks(self, board, nbadclkA, nbadclkB, nbadclkC, nbadclkD, nbadstr):
        debugphase=False
        plloutnum = 0 # adjusting clklvds
        plloutnum2 = 1 # adjusting clklvdsout
        if 0<=self.plljustreset[board]<12: # we start by going up in phase
            nbad = nbadclkA + nbadclkB + nbadclkC + nbadclkD + nbadstr
            if debugphase: print("plljustreset for board",board,"is",self.plljustreset[board],"nbad",nbad)
            self.phasenbad[board][self.plljustreset[board]]+=nbad
            if debugphase: print(self.phasenbad[board])
            self.dophase(board, plloutnum, (self.plljustresetdir[board]==1), pllnum=0, quiet=True) # adjust phase of plloutnum
            self.dophase(board, plloutnum2, (self.plljustresetdir[board]==1), pllnum=0, quiet=True) # adjust phase of plloutnum
            self.plljustreset[board]+=self.plljustresetdir[board]
        elif self.plljustreset[board]>=12:
            if debugphase: print("plljustreset for board",board,"is",self.plljustreset[board])
            if self.plljustreset[board]==15: self.plljustresetdir[board]=-1
            self.plljustreset[board] += self.plljustresetdir[board]
            self.dophase(board, plloutnum, (self.plljustresetdir[board] == 1), pllnum=0, quiet=True)  # adjust phase of plloutnum
            self.dophase(board, plloutnum2, (self.plljustresetdir[board] == 1), pllnum=0, quiet=True)  # adjust phase of plloutnum
        elif self.plljustreset[board]==-1:
            if debugphase: print("plljustreset for board",board,"is",self.plljustreset[board])
            print("bad clkstr per phase step:",self.phasenbad[board])
            startofzeros, lengthofzeros = find_longest_zero_stretch(self.phasenbad[board], True)
            print("good phase starts at",startofzeros, "and goes for", lengthofzeros,"steps")
            if lengthofzeros<4:
                print("Bad PLL calibration found! Check power connections?!")
                self.dostartstop()
            else:
                if startofzeros>=12: startofzeros-=12
                n = startofzeros + lengthofzeros//2 + self.phaseoffset # amount to adjust clklvds and clklvdsout (positive)
                if n>=12: n-=12
                n+=1 # extra 1 because we went to phase=-1 before
                for i in range(n):
                    self.dophase(board, plloutnum, 1, pllnum=0, quiet=(i != n - 1)) # adjust phase of plloutnum
                    self.dophase(board, plloutnum2, 1, pllnum=0, quiet=(i != n - 1))  # adjust phase of plloutnum
                self.plljustreset[board] += self.plljustresetdir[board]
        elif self.plljustreset[board] == -2: # pllreset is now ALMOST DONE
            self.depth()
            self.plljustreset[board] += self.plljustresetdir[board]
        elif self.plljustreset[board] == -3: # pllreset is now DONE
            self.dodrawing = True
            self.plljustreset[board] = -10

    def wheelEvent(self, event):  # QWheelEvent
        if hasattr(event, "delta"):
            if event.delta() > 0:
                self.uppos()
            else:
                self.downpos()
        elif hasattr(event, "angleDelta"):
            if event.angleDelta() > 0:
                self.uppos()
            else:
                self.downpos()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Up: self.uppos()
        if event.key() == QtCore.Qt.Key_Down: self.downpos()
        if event.key() == QtCore.Qt.Key_Left: self.timefast()
        if event.key() == QtCore.Qt.Key_Right: self.timeslow()
        # modifiers = QtWidgets.QApplication.keyboardModifiers()

    def exttrig(self, value):
        board = self.ui.boardBox.value()
        self.doexttrig[board] = value
        self.ui.exttrigCheck.setChecked(value)
        #print("doexttrig", self.doexttrig[board], "for board", board)
        if self.doexttrig[board]: self.ui.extsmatrigCheck.setEnabled(False)
        else: self.ui.extsmatrigCheck.setEnabled(True)
        r = self.ui.rollingButton.isChecked()
        if self.doexttrig[board]: r = False
        #print("setting rolling",r,"for board",board)
        usbs[board].send(bytes([2, 8, r, 0, 100, 100, 100, 100]))
        usbs[board].recv(4)
        if self.doexttrig[board]:
            self.doexttrigecho = [False] * self.num_board  # turn off doexttrigecho for all other boards
            self.doexttrigecho[board] = True # and turn on for this one
        else:
            self.doexttrigecho[board] = False  # turn off for this one since it's not doing exttrig anymore
        self.sendtriggerinfo(board) # to account for trigger time delay or not
        self.set_channel_frame()

    def extsmatrig(self):
        self.doextsmatrig[self.activeboard] = self.ui.extsmatrigCheck.isChecked()
        #print("ext SMA trig now",self.doextsmatrig[self.activeboard],"for board",self.activeboard)
        if self.doextsmatrig[self.activeboard]: self.ui.exttrigCheck.setEnabled(False)
        else: self.ui.exttrigCheck.setEnabled(True)
        self.set_channel_frame()

    def grid(self):
        if self.ui.actionGrid.isChecked():
            self.ui.plot.showGrid(x=True, y=True)
        else:
            self.ui.plot.showGrid(x=False, y=False)

    def marker(self):
        if self.ui.markerCheck.isChecked():
            for li in range(self.nlines):
                self.lines[li].setSymbol("o")
                self.lines[li].setSymbolSize(3)
                # self.lines[li].setSymbolPen("black")
                self.lines[li].setSymbolPen(self.linepens[li].color())
                self.lines[li].setSymbolBrush(self.linepens[li].color())
        else:
            for li in range(self.nlines):
                self.lines[li].setSymbol(None)

    def dostartstop(self):
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

    def triggerlevelchanged(self, value):
        if value + self.triggerdelta < 256 and value - self.triggerdelta > 0:
            self.triggerlevel = value
            for board in range(self.num_board): self.sendtriggerinfo(board)
            self.drawtriggerlines()

    def triggerdeltachanged(self, value):
        if value + self.triggerlevel < 256 and self.triggerlevel - value > 0:
            self.triggerdelta = value
            for board in range(self.num_board): self.sendtriggerinfo(board)

    def triggerposchanged(self, value):
        self.triggerpos = int(self.expect_samples * value / 100)
        for board in range(self.num_board): self.sendtriggerinfo(board)
        self.drawtriggerlines()

    def triggerchanchanged(self):
        self.triggerchan[self.activeboard] = self.ui.trigchan_comboBox.currentIndex()
        self.sendtriggerinfo(self.activeboard)
        self.set_channel_frame()

    def sendtriggerinfo(self, board):
        triggerpos = self.triggerpos + self.triggershift # move actual trigger a little earlier, so we have time to shift a bit later on (downsamplemerging, delayoffset, toff etc.)
        if self.doexttrig[board]:
            if self.dotwochannel: triggerpos += int(8*self.lvdstrigdelay[board] / 40 / self.downsamplefactor / 2)
            else: triggerpos += int(8*self.lvdstrigdelay[board] / 40 / self.downsamplefactor)
        #print("board", board, "triggerpos", triggerpos)
        usbs[board].send(bytes([8, self.triggerlevel + 1, self.triggerdelta, int(triggerpos / 256), triggerpos % 256,
                        self.triggertimethresh, self.triggerchan[board], 100]))
        usbs[board].recv(4)
        # length to take after trigger is self.expect_samples - self.triggerpos + 1
        # we want self.expected_samples - that, which is about self.triggerpos, and then pad a little
        prelengthtotake = self.triggerpos + 5
        usbs[board].send(bytes([2, 7]+inttobytes(prelengthtotake)+[0,0]))
        usbs[board].recv(4)

    def drawtriggerlines(self):
        self.hline = (self.triggerlevel - 127) * self.yscale * 16 * 16
        self.otherlines[1].setData([self.min_x, self.max_x],
                                   [self.hline, self.hline])  # horizontal line showing trigger threshold
        point = self.triggerpos + 1.0
        self.vline = 4 * 10 * point * (self.downsamplefactor / self.nsunits / self.samplerate)
        self.otherlines[0].setData([self.vline, self.vline], [max(self.hline + self.min_y / 2, self.min_y),
                                                              min(self.hline + self.max_y / 2,
                                                                  self.max_y)])  # vertical line showing trigger time

    def tot(self):
        self.triggertimethresh = self.ui.totBox.value()
        for board in range(self.num_board): self.sendtriggerinfo(board)

    def depth(self):
        self.expect_samples = self.ui.depthBox.value()
        self.setupchannels()
        self.triggerposchanged(self.ui.thresholdPos.value())
        self.tot()
        self.timechanged()

    def rolling(self):
        self.isrolling = not self.isrolling
        self.ui.rollingButton.setChecked(self.isrolling)
        for board in range(len(usbs)):
            r = self.isrolling
            if self.doexttrig[board]: r = False
            usbs[board].send(bytes([2, 8, r, 0, 100, 100, 100, 100]))
            usbs[board].recv(4)
        if not self.isrolling:
            self.ui.rollingButton.setText("Normal")
        else:
            self.ui.rollingButton.setText("Auto")

    def single(self):
        self.getone = not self.getone
        self.ui.singleButton.setChecked(self.getone)

    def highres(self, value):
        self.highresval = value > 0
        # print("highres",self.highresval)
        for usb in usbs: self.telldownsample(usb, self.downsample)

    def telldownsample(self, usb, ds):
        if ds < 0: ds = 0
        if ds == 0:
            ds = 0
            self.downsamplemerging = 1
        if ds == 1:
            ds = 0
            self.downsamplemerging = 2
        if ds == 2:
            ds = 0
            self.downsamplemerging = 4
        if ds == 3:
            ds = 0
            if not self.dotwochannel:
                self.downsamplemerging = 8
            else:
                self.downsamplemerging = 10
        if ds == 4:
            ds = 0
            self.downsamplemerging = 20
        if not self.dotwochannel:
            if ds == 5:
                ds = 0
                self.downsamplemerging = 40
            if ds > 5:
                ds = ds - 5
                self.downsamplemerging = 40
        else:
            if ds > 4:
                ds = ds - 4
                self.downsamplemerging = 20
        self.downsamplefactor = self.downsamplemerging * pow(2, ds)
        # print("ds, dsm, dsf",ds,self.downsamplemerging,self.downsamplefactor)
        usb.send(bytes([9, ds, self.highresval, self.downsamplemerging, 100, 100, 100, 100]))
        usb.recv(4)

    def timefast(self):
        amount = 1
        if self.downsample - amount < -10:
            print("downsample too small!")
            return
        self.downsample = self.downsample - amount
        if self.downsample<0:
            self.downsamplezoom = pow(2, -self.downsample)
            self.ui.thresholdPos.setEnabled(False)
        else:
            self.downsamplezoom = 1
            self.ui.thresholdPos.setEnabled(True)
            for usb in usbs: self.telldownsample(usb, self.downsample)
        self.timechanged()

    def timeslow(self):
        amount = 1
        if (self.downsample + amount - 5) > 31:
            print("downsample too large!")
            return
        self.downsample = self.downsample + amount
        if self.downsample<0:
            self.downsamplezoom = pow(2, -self.downsample)
            self.ui.thresholdPos.setEnabled(False)
        else:
            self.downsamplezoom = 1
            self.ui.thresholdPos.setEnabled(True)
            for usb in usbs: self.telldownsample(usb, self.downsample)
        self.timechanged()

    def timechanged(self):
        self.max_x = 4 * 10 * self.expect_samples * (self.downsamplefactor / self.nsunits / self.samplerate)
        baremaxx = 4 * 10 * self.expect_samples * self.downsamplefactor / self.samplerate
        if baremaxx > 5:
            self.nsunits = 1
            self.max_x = 4 * 10 * self.expect_samples * (self.downsamplefactor / self.nsunits / self.samplerate)
            self.units = "ns"
        if baremaxx > 5000:
            self.nsunits = 1000
            self.max_x = 4 * 10 * self.expect_samples * (self.downsamplefactor / self.nsunits / self.samplerate)
            self.units = "us"
        if baremaxx > 5000000:
            self.nsunits = 1000000
            self.max_x = 4 * 10 * self.expect_samples * (self.downsamplefactor / self.nsunits / self.samplerate)
            self.units = "ms"
        if baremaxx > 5000000000:
            self.nsunits = 1000000000
            self.max_x = 4 * 10 * self.expect_samples * (self.downsamplefactor / self.nsunits / self.samplerate)
            self.units = "s"
        self.ui.plot.setLabel('bottom', "Time (" + self.units + ")")
        if self.downsamplezoom>1:
            tp = self.vline
            tpfrac = self.vline/self.max_x
            self.min_x = tp - tpfrac * self.max_x/self.downsamplezoom
            self.max_x = tp + (1-tpfrac) * self.max_x/self.downsamplezoom
        else:
            self.min_x = 0

        if hasattr(self,"hsprosock"):
            while self.hsprosock.issending: time.sleep(.001)
        self.totdistcorr = [0]*self.num_board
        if self.dotwochannel:
            for c in range(self.num_chan_per_board * self.num_board):
                self.xydata[c][0] = np.array([range(0, 2 * 10 * self.expect_samples)]) * (
                            2 * self.downsamplefactor / self.nsunits / self.samplerate)
        else:
            for c in range(self.num_chan_per_board * self.num_board):
                self.xydata[c][0] = np.array([range(0, 4 * 10 * self.expect_samples)]) * (
                            1 * self.downsamplefactor / self.nsunits / self.samplerate)
                if self.dointerleaved[c//2]:
                    self.xydatainterleaved[c//2][0] = np.array([range(0, 2 * 4 * 10 * self.expect_samples)]) * (
                            0.5 * self.downsamplefactor / self.nsunits / self.samplerate)
        self.ui.plot.setRange(xRange=(self.min_x, self.max_x), padding=0.00)
        self.ui.plot.setRange(yRange=(self.min_y, self.max_y), padding=0.01)
        self.drawtriggerlines()
        self.tot()
        self.ui.timebaseBox.setText("2^"+str(self.downsample))

    def risingfalling(self):
        fallingedge = self.ui.risingfalling_comboBox.currentIndex()==1
        if self.triggertype == 1:
            if fallingedge: self.triggertype = 2
        if self.triggertype == 2:
            if not fallingedge: self.triggertype = 1

    def drawing(self):
        if self.ui.actionDrawing.isChecked():
            self.dodrawing = True
            # print("drawing now",self.dodrawing)
        else:
            self.dodrawing = False
            # print("drawing now",self.dodrawing)

    def wideline(self):
        for chan in range(self.num_board*self.num_chan_per_board):
            self.linepens[chan].setWidth(3 if self.ui.wideCheck.checkState() == QtCore.Qt.Checked else 1)

    def updateplot(self):
        if hasattr(self,"hsprosock"):
            while self.hsprosock.issending: time.sleep(.001)
        gotevent = self.getevent()
        now = time.time()
        dt = now - self.lastTime + 0.00001
        self.lastTime = now
        if self.fps is None:
            self.fps = 1.0 / dt
        else:
            s = np.clip(dt * 3., 0, 1)
            self.fps = self.fps * (1 - s) + (1.0 / dt) * s
        self.statuscounter = self.statuscounter + 1
        if self.statuscounter % 20 == 0: self.ui.statusBar.showMessage("%0.2f fps, %d events, %0.2f Hz, %0.2f MB/s" % (
            self.fps, self.nevents, self.lastrate, self.lastrate * self.lastsize / 1e6))
        if not gotevent: return
        if self.dorecordtofile:
            self.recordeventtofile()
            if self.nevents % self.numrecordeventsperfile == 0:
                if self.dorecordtofile: # if writing, close and open new file, by calling recordtofile() twice
                    self.recordtofile()
                    self.recordtofile()
        if not self.dodrawing: return
        for li in range(self.nlines):
            xdatanew, ydatanew = None, None
            if not self.dointerleaved[int(li/2)]:
                if self.doresamp:
                    ydatanew, xdatanew = resample(self.xydata[li][1], len(self.xydata[li][0]) * self.doresamp, t=self.xydata[li][0])
                else:
                    if self.persist_time>0: xdatanew, ydatanew = self.xydata[li][0].copy(), self.xydata[li][1].copy()
                    else: xdatanew, ydatanew = self.xydata[li][0], self.xydata[li][1]
            else:
                if li%4 == 0:
                    self.xydatainterleaved[int(li/2)][1][0::2] = self.xydata[li][1]
                    self.xydatainterleaved[int(li/2)][1][1::2] = self.xydata[li+self.num_chan_per_board][1]
                    if self.ui.actionToggle_trig_stabilizer.isChecked():
                        self.xydatainterleaved[int(li/2)][0][0::2] = self.xydata[li][0]
                        self.xydatainterleaved[int(li/2)][0][1::2] = self.xydata[li+self.num_chan_per_board][0] + 0.15625
                    if self.doresamp:
                        xdatanew = np.linspace(self.xydatainterleaved[int(li/2)][0].min(), self.xydatainterleaved[int(li/2)][0].max(), len(self.xydatainterleaved[int(li/2)][0])*1) # first put them on a regular x spacing
                        f_cubic = interp1d(self.xydatainterleaved[int(li/2)][0], self.xydatainterleaved[int(li/2)][1], kind='linear')
                        ydatanew = f_cubic(xdatanew)
                        ydatanew, xdatanew = resample(ydatanew, len(xdatanew) * self.doresamp, t=xdatanew) # then resample
                    else:
                        if self.persist_time>0 or self.ui.actionToggle_trig_stabilizer.isChecked(): xdatanew, ydatanew = self.xydatainterleaved[int(li/2)][0].copy(),self.xydatainterleaved[int(li/2)][1].copy()
                        else: xdatanew, ydatanew = self.xydatainterleaved[int(li/2)][0],self.xydatainterleaved[int(li/2)][1]

                    if self.ui.actionToggle_trig_stabilizer.isChecked(): # special stabilization for interleaved data (it's done on a copy, so we don't have to be careful
                        fitwidth = (self.max_x - self.min_x)
                        xc = xdatanew[(xdatanew > self.vline - fitwidth) & (xdatanew < self.vline + fitwidth)]
                        numsamp = 4  # number of samples to use
                        if self.doresamp: numsamp *= self.doresamp # adjust for extra samples from upsampling
                        fitwidth *= numsamp / max(2, xc.size)
                        xc = xdatanew[(xdatanew > self.vline - fitwidth) & (xdatanew < self.vline + fitwidth)]
                        # print("xc size start end", xc.size, xc[0], xc[-1], "and vline at", self.vline)
                        yc = ydatanew[(xdatanew > self.vline - fitwidth) & (xdatanew < self.vline + fitwidth)]
                        fallingedge = self.ui.risingfalling_comboBox.currentIndex() == 1
                        if fallingedge: yc = -yc
                        if xc.size > 1:
                            distcorrtemp = find_crossing_distance(yc, self.hline, self.vline, xc[0], xc[1] - xc[0])
                            if distcorrtemp is not None and abs(distcorrtemp) < 1.0:
                                xdatanew -= distcorrtemp

            if xdatanew is not None and self.lines[li].isVisible():
                self.lines[li].setData(xdatanew, ydatanew)
                if li==self.activexychannel and self.persist_time>0:
                    if len(self.persist_lines) >= self.max_persist_lines:
                        oldest_item, _, _ = self.persist_lines[0]
                        self.ui.plot.removeItem(oldest_item)
                    persist_item = self.ui.plot.plot(xdatanew, ydatanew, pen=self.linepens[li], skipFiniteCheck=True, connect="finite")
                    self.persist_lines.append((persist_item, time.time(), li))

        if self.dofft and hasattr(self.fftui,"fftfreqplot_xdata"):
            self.fftui.fftline.setPen(self.linepens[self.activeboard * self.num_chan_per_board + self.selectedchannel])
            self.fftui.fftline.setData(self.fftui.fftfreqplot_xdata,self.fftui.fftfreqplot_ydata)
            self.fftui.ui.plot.setTitle('Haasoscope Pro FFT of board '+str(self.activeboard)+' channel ' + str(self.selectedchannel))
            self.fftui.ui.plot.setLabel('bottom', self.fftui.fftax_xlabel)
            self.fftui.ui.plot.setRange(xRange=(0.0, self.fftui.fftax_xlim))
            now = time.time()
            dt = now - self.fftui.fftlastTime
            if dt>3.0 or self.fftui.fftyrange<self.fftui.fftfreqplot_ydatamax or self.fftui.fftyrangelow>self.fftui.fftfreqplot_ydatamin*100 or self.fftui.newplot:
                self.fftui.newplot = False
                self.fftui.fftlastTime = now
                self.fftui.fftyrange = self.fftui.fftfreqplot_ydatamax * 1.2
                self.fftui.fftyrangelow = self.fftui.fftfreqplot_ydatamin / 1.0
                if self.fftui.dolog: self.fftui.ui.plot.setYRange(log(self.fftui.fftyrangelow,10), log(self.fftui.fftyrange,10))
                else: self.fftui.ui.plot.setYRange(0, self.fftui.fftyrange)
            if not self.fftui.isVisible(): # closed the fft window
                self.dofft = False
                self.ui.fftCheck.setChecked(QtCore.Qt.Unchecked)
        app.processEvents()

    def recordeventtofile(self):
        time_s = str(time.time())
        for c in range(self.num_board*self.num_chan_per_board):
            if self.lines[c].isVisible():  # only save the data for visible channels
                self.outf.write(str(self.nevents) + ",")  # start of each line is the event number
                self.outf.write(time_s + ",")  # next column is the time in seconds of the current event
                self.outf.write(str(c) + ",")  # next column is the channel number
                self.outf.write(str(self.vline * self.xscaling) + ",")  # next column is the trigger time
                self.outf.write(str(self.downsamplefactor / self.samplerate) + ",")  # next column is the time between samples, in ns
                self.outf.write(str( (2 if self.dotwochannel else 4) * 10 * self.expect_samples) + ",")  # next column is the number of samples
                self.xydata[c][1].tofile(self.outf, ",", format="%.3f")  # save y data (1) from fast adc channel c
                self.outf.write("\n")  # newline

    # gets event data for all boards
    def getevent(self):
        if self.paused:
            time.sleep(.1)
        else:
            rx_len = 0
            debugread = False
            try:
                readyevent = [0]*self.num_board
                if debugread: print("\ngetevent")
                noextboards=[]
                self.noextboard = -1
                for board in range(self.num_board): # go through the ext trig boards first to make sure the ext triggers are active before the non-ext trig boards fire
                    if not self.doexttrig[board]:
                        noextboards.append(board)
                        continue
                    readyevent[board] = self.getchannels(board)
                    if readyevent[board]:
                        if debugread: print("board",board,"ready")
                        self.getpredata(board) # gets info needed for trigger time adjustments
                    else:
                        if debugread: print("board",board,"not ready")
                #assert self.noextboard > -1 # we should have found at least one board that is not doing ext triggered
                for board in noextboards:
                    readyevent[board] = self.getchannels(board)
                    if readyevent[board]:
                        if self.noextboard == -1: self.noextboard = board # use the first noextboard with data as the trigger reference
                        if debugread: print("noext board", board, "ready")
                        self.getpredata(board) # gets info needed for trigger time adjustments
                    else:
                        if debugread: print("noext board", board, "not ready")
                if not any(readyevent):
                    if debugread: print("none ready")
                for nodoext in [True, False]:
                    if nodoext: continue # first do just the non-ext-trigger boards, to find the right trig stabilizer offsets
                    for board in range(self.num_board):
                        if not readyevent[board]:
                            if debugread: print("board",board,"data not ready?")
                            continue
                        data = self.getdata(usbs[board])
                        rx_len = rx_len + len(data)
                        self.drawchannels(data, board)
                        if self.dofft and board==self.activeboard: self.plot_fft()
                if self.getone and rx_len > 0:
                    self.dostartstop()
                    self.drawtext()
            except ftd2xx.DeviceError:
                self.close_socket()
                print("Device error")
                sys.exit(1)
            if self.db: print(time.time() - self.oldtime, "done with evt", self.nevents)
            if rx_len > 0: self.nevents += 1
            else: return 0
            if self.nevents - self.oldnevents >= self.tinterval:
                now = time.time()
                elapsedtime = now - self.oldtime
                self.oldtime = now
                self.lastrate = round(self.tinterval / elapsedtime, 2)
                self.lastsize = rx_len
                #if not self.dodrawing: print(self.nevents, "events,", self.lastrate, "Hz", round(self.lastrate * self.lastsize / 1e6, 3), "MB/s")
                self.oldnevents = self.nevents
            return 1

    # sets trigger on a board, and sees whether an event is ready to be read out (and then if so calculates sample_triggered)
    def getchannels(self, board):
        tt = self.triggertype
        if self.doexttrig[board] > 0:
            if self.doexttrigecho[board]: tt = 30
            else: tt = 3
        elif self.doextsmatrig[board] > 0: tt = 5
        usbs[board].send(bytes([1, tt, self.dotwochannel+2*self.dooversample[board], 99] + inttobytes(
            self.expect_samples + self.expect_samples_extra - self.triggerpos + 1)))  # length to take after trigger (last 4 bytes)
        triggercounter = usbs[board].recv(4)  # get the 4 bytes
        acqstate = triggercounter[0]
        if acqstate == 251:  # an event is ready to be read out
            self.sample_triggered[board] = triggercounter[1]
            if self.debug_trigger_phase:
                if board==0:
                    print("\nbest sample triggered from triggercounter[1] =", triggercounter[1])
                    print("board",board,"sample triggered", binprint(triggercounter[3]), binprint(triggercounter[2]), binprint(triggercounter[1]))
                    print("sample_triggered", self.sample_triggered[board], "for board", board)
                ststring = [0]*4
                for st in range(4):
                    usbs[board].send(bytes([2, 15+st, 100, 100, 100, 100, 100, 100]))  # get sample triggered 0
                    ststring[st] = usbs[board].recv(4)
                    print("sample triggered", st, binprint(ststring[st][2]), binprint(ststring[st][1]), binprint(ststring[st][0]))
                # if board==0:
                #     if 9<=self.sample_triggered[board]<=11: self.dodrawing=True
                #     else: self.dodrawing=False
                gotzerobit = False
                for tb in range(0,20):
                    for st in range(4):
                        if self.dotwochannel and (st+1)%2==self.triggerchan[board]: continue
                        thebit = getbit(ststring[st][tb//8],tb%8 )
                        print(tb, thebit )
                        if not thebit: gotzerobit = True
                        if gotzerobit and thebit:
                            gotzerobit = False
                            print("X", tb, st)
                            #self.triggerphase[board] = st
                            #self.sample_triggered[board] = tb
            return 1
        else:
            return 0

    # gets some pre info from a board that has data ready to be read out
    def getpredata(self, board):
        if self.doeventcounter:
            usbs[board].send(bytes([2, 3, 100, 100, 100, 100, 100, 100]))  # get eventcounter
            res = usbs[board].recv(4)
            eventcountertemp = int.from_bytes(res,"little")
            if eventcountertemp != self.eventcounter[board] + 1 and eventcountertemp != 0:  # check event count, but account for rollover
                print("Event counter not incremented by 1?", eventcountertemp, self.eventcounter[board], " for board", board)
            self.eventcounter[board] = eventcountertemp
            if board==0:
                eventcounterdiff = self.eventcounter[board]-self.eventcounter[board+1]
                if eventcounterdiff!=self.oldeventcounterdiff: print("eventcounter diff for board",board,"and",board+1,eventcounterdiff)
                self.oldeventcounterdiff=eventcounterdiff
        if self.doeventtime and board==0:
            usbs[board].send(bytes([2, 11, 100, 100, 100, 100, 100, 100]))  # get eventtime
            res = usbs[board].recv(4)
            eventtime = int.from_bytes(res,"little")
            eventtimediff = eventtime-self.oldeventtime
            print("board",board,"triggered at clock cycle",eventtime,"a diff of",eventtimediff,"cycles",round(0.0125*eventtimediff,4),"us")
            self.oldeventtime=eventtime
        self.downsamplemergingcounter[board] = 0
        usbs[board].send(bytes([2, 4, 100, 100, 100, 100, 100, 100]))  # get downsamplemergingcounter and triggerphase
        res = usbs[board].recv(4)
        if self.downsamplemerging > 1: self.downsamplemergingcounter[board] = res[0]
        if self.downsamplemergingcounter[board] == self.downsamplemerging:
            if not self.doexttrig[board]:
                self.downsamplemergingcounter[board] = 0
        if self.debug_trigger_phase: print("got triggerphase from firmware =",res[1])
        self.triggerphase[board] = res[1]

        if not self.doexttrig[board] and any(self.doexttrigecho):
            assert self.doexttrigecho.count(True)==1
            echoboard=-1
            for theb in range(self.num_board): # find the board index we're echoing from
                if self.doexttrigecho[theb]:
                    assert echoboard==-1 # there should only be one echoing board
                    echoboard=theb
            assert echoboard != board
            if echoboard>board:
                usbs[board].send(bytes([2, 12, 100, 100, 100, 100, 100, 100]))  # get ext trig echo forwards delay
                res = usbs[board].recv(4)
                #print("lvdstrigdelay from echo forwards phases ", res[0],res[1],res[2],res[3])
            else:
                usbs[board].send(bytes([2, 13, 100, 100, 100, 100, 100, 100]))  # get ext trig echo backwards delay
                res = usbs[board].recv(4)
                #print("lvdstrigdelay from echo backwards phases ", res[0],res[1],res[2],res[3])
            if res[0] == res[1]:
                lvdstrigdelay = (res[0] + res[1]) / 4
                if echoboard<board: lvdstrigdelay += round(lvdstrigdelay/11.5,1) # this has to be tuned a little experimentally
                if lvdstrigdelay == self.lastlvdstrigdelay[echoboard]:
                    self.lvdstrigdelay[echoboard] = lvdstrigdelay
                    self.tot() # to adjust trigger time to account for delay
                    if all(item <= -10 for item in self.plljustreset):
                        print("lvdstrigdelay from board", board, "to echoboard", echoboard, "is", lvdstrigdelay)
                        self.doexttrigecho[echoboard] = False
                self.lastlvdstrigdelay[echoboard] = lvdstrigdelay
            else:
                if all(item <= -10 for item in self.plljustreset): # adjust phases so the trigger singals are lined up in phase
                    self.dophase(board, plloutnum=0, updown=1, quiet=True) # moving all clocks together will not mess up the ADC phases
                    self.dophase(board, plloutnum=1, updown=1, quiet=True)
                    self.dophase(board, plloutnum=2, updown=1, quiet=True)

    def getdata(self, usb):
        expect_len = (self.expect_samples+ self.expect_samples_extra) * 2 * self.nsubsamples # length to request: each adc bit is stored as 10 bits in 2 bytes, a couple extra for shifting later
        usb.send(bytes([0, 99, 99, 99] + inttobytes(expect_len)))  # send the 4 bytes to usb
        data = usb.recv(expect_len)  # recv from usb
        rx_len = len(data)
        self.total_rx_len += rx_len
        if expect_len != rx_len:
            print('*** expect_len (%d) and rx_len (%d) mismatch' % (expect_len, rx_len))
        if self.debug:
            time.sleep(.5)
            # oldbytes()
        return data

    def drawchannels(self, data, board):
        if self.dofast: return
        if self.num_board>0 and self.firmwareversion<28:
            if self.firmwareversion>-1: print("Firmware v28+ required, for new triggerphase calculation!")
            self.firmwareversion = -1
            return 0
        if self.doexttrig[board]:
            boardtouse = self.noextboard
            self.sample_triggered[board] = self.sample_triggered[boardtouse] # take from the other board when using ext trig
            self.triggerphase[board] = self.triggerphase[boardtouse]
        sample_triggered_touse = self.sample_triggered[board]
        if self.debug_trigger_phase: print("sampletriggered", self.sample_triggered[board], "and triggerphase for board", board, "is", self.triggerphase[board])
        if self.dotwochannel: triggerphase = self.triggerphase[board]//2
        else: triggerphase = self.triggerphase[board]
        nbadclkA = 0
        nbadclkB = 0
        nbadclkC = 0
        nbadclkD = 0
        nbadstr = 0
        unpackedsamples = struct.unpack('<' + 'h' * (len(data) // 2), data)
        npunpackedsamples = np.array(unpackedsamples, dtype='float')
        npunpackedsamples *= self.yscale
        if self.dooversample[board] and board%2==0:
            npunpackedsamples += self.extrigboardmeancorrection[board]
            npunpackedsamples *= self.extrigboardstdcorrection[board]
        downsampleoffset = 2 * (sample_triggered_touse + (self.downsamplemergingcounter[board]-1)%self.downsamplemerging * 10) // self.downsamplemerging
        downsampleoffset += 20*self.triggershift # account for having moved actual trigger a little earlier, so we had time to shift a bit now for things like toff
        if not self.dotwochannel: downsampleoffset *= 2
        if self.doexttrig[board]:
            # 2.5 ns is the period of clklvds, which is 8 samples (1ns/3.2 per sample), we just do the mod here, but the majority of it is handled in setting triggerpos
            if self.dotwochannel: downsampleoffset -= int(self.toff/self.downsamplefactor/2) + int(8*self.lvdstrigdelay[board]/self.downsamplefactor/2) %40
            else: downsampleoffset -= int(self.toff/self.downsamplefactor) + int(8*self.lvdstrigdelay[board]/self.downsamplefactor) %40
        datasize = self.xydata[board][1].size
        for s in range(0, self.expect_samples+self.expect_samples_extra):
            vals = unpackedsamples[s*self.nsubsamples+40:s*self.nsubsamples + 50]
            if vals[9]!=-16657: print("no beef?") # -16657 is 0xbeef
            if vals[8]!=0 or (self.lastclk!=341 and self.lastclk!=682):
                # only bother checking if there was a clkstr problem detected in firmware, or we need to decode
                # because of a previous clkstr prob and now want to update self.lastclk
                for n in range(0,8): # the subsample to get
                    val = vals[n]
                    if n < 4:
                        if val!=341 and val!= 682: # 0101010101 or 1010101010
                            if n == 0: nbadclkA += 1
                            if n == 1: nbadclkB += 1
                            if n == 2: nbadclkC += 1
                            if n == 3: nbadclkD += 1
                            #print("s=", s, "n=", n, "clk", val, binprint(val))
                        self.lastclk = val
                    elif val not in {0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512}: # 10 bits long, and just one 1
                        nbadstr = nbadstr + 1
                        #print("s=", s, "n=", n, "str", val, binprint(val))
            if self.dotwochannel:
                samp = s*20 - downsampleoffset - triggerphase
                nsamp=20
                nstart=0
                if samp<0:
                    nsamp = 20 + samp
                    nstart = -samp
                    samp = 0
                if samp+20 >= datasize:
                    nsamp = datasize - samp
                if 0 < nsamp <= 20:
                    self.xydata[board * self.num_chan_per_board+0][1][samp:samp + nsamp] = npunpackedsamples[s*self.nsubsamples+20+nstart:s*self.nsubsamples+20+nstart+nsamp]
                    self.xydata[board * self.num_chan_per_board+1][1][samp:samp + nsamp] = npunpackedsamples[s*self.nsubsamples+nstart:s*self.nsubsamples+nstart+nsamp]
            else:
                samp = s*40 - downsampleoffset - triggerphase
                nsamp=40
                nstart=0
                if samp<0:
                    nsamp = 40 + samp
                    nstart = -samp
                    samp = 0
                if samp+40 >= datasize:
                    nsamp = datasize - samp
                if 0 < nsamp <= 40:
                    self.xydata[board * self.num_chan_per_board][1][samp:samp + nsamp] = npunpackedsamples[s*self.nsubsamples+nstart:s*self.nsubsamples+nstart+nsamp]

        if self.ui.actionToggle_trig_stabilizer.isChecked():
            if abs(self.totdistcorr[board]) > 1.0:
                self.xydata[board * self.num_chan_per_board][0] += self.totdistcorr[board]
                if self.dotwochannel: self.xydata[board * self.num_chan_per_board + 1][0] += self.totdistcorr[board]
                self.totdistcorr[board] = 0
            distcorrtemp=None
            if self.doexttrig[board]: # take from the best non exttrig board
                if self.dooversample[board] and board%2==1: distcorrtemp = self.distcorr[board-1]
                elif not self.doexttrig[self.activeboard]: distcorrtemp = self.distcorr[self.activeboard]
                else: # take from first triggering board
                    for bn in range(self.num_board):
                        if not self.doexttrig[board]:
                            distcorrtemp = self.distcorr[bn]
                            break
            else: # find distcorr for this board which is triggering
                thed = self.xydata[board * self.num_chan_per_board + self.triggerchan[board]]
                fitwidth = (self.max_x - self.min_x)
                xc = thed[0][(thed[0] > self.vline - fitwidth) & (thed[0] < self.vline + fitwidth)]
                numsamp = 4 # number of samples to use
                fitwidth *= numsamp / max(2,xc.size)
                xc = thed[0][(thed[0] > self.vline - fitwidth) & (thed[0] < self.vline + fitwidth)]
                #print("xc size start end", xc.size, xc[0], xc[-1], "and vline at", self.vline)
                yc = thed[1][(thed[0] > self.vline - fitwidth) & (thed[0] < self.vline + fitwidth)]
                fallingedge = self.ui.risingfalling_comboBox.currentIndex() == 1
                if fallingedge: yc = -yc
                if xc.size>1:
                    distcorrtemp = find_crossing_distance(yc, self.hline, self.vline, xc[0], xc[1] - xc[0])
            if distcorrtemp is not None and abs(distcorrtemp) < 1.0:
                self.distcorr[board]=distcorrtemp
                self.xydata[board * self.num_chan_per_board][0] -= self.distcorr[board]
                if self.dotwochannel: self.xydata[board * self.num_chan_per_board + 1][0] -= self.distcorr[board]
                self.totdistcorr[board] += self.distcorr[board]
            #print("board totdistcorr distcorrtemp distcorr", board, self.totdistcorr[board], distcorrtemp, self.distcorr[board])

        self.adjustclocks(board, nbadclkA, nbadclkB, nbadclkC, nbadclkD, nbadstr)
        if board == self.activeboard:
            self.nbadclkA = nbadclkA
            self.nbadclkB = nbadclkB
            self.nbadclkC = nbadclkC
            self.nbadclkD = nbadclkD
            self.nbadstr = nbadstr
        if self.triggerautocalibration[board]:
            self.triggerautocalibration[board] = False
            self.autocalibration()

    def drawtext(self):  # happens once per second
        thestr = ""
        if self.dorecordtofile: thestr += "Recording to file "+str(self.outf.name)+str("\n")
        if self.dodrawing:
            if self.ui.actionTrigger_thresh.isChecked(): thestr += "Trigger threshold: "+str(round(self.hline, 3))+" div\n"
            #thestr += "Nbadclks A B C D:" + str(self.nbadclkA) + " " + str(self.nbadclkB) + " " + str(self.nbadclkC) + " " + str(self.nbadclkD) + str("\n")
            #thestr += "Nbadstrobes:" + str(self.nbadstr) + str("\n")
            #thestr += "Last clk:"+str(self.lastclk) + str("\n")
            if self.ui.actionTemperatures.isChecked(): thestr += gettemps(usbs[self.activeboard]) + str("\n")

            thestr += "\nMeasurements for board "+str(self.activeboard)+" and chan "+str(self.selectedchannel)+":\n"
            if self.ui.actionMean.isChecked(): thestr += "Mean: " + str( round( 1000* self.VperD[self.activeboard*2+self.selectedchannel] * np.mean(self.xydata[self.activexychannel][1]), 3) ) + " mV\n"
            if self.ui.actionRMS.isChecked(): thestr += "RMS: " + str( round( 1000* self.VperD[self.activeboard*2+self.selectedchannel] * np.std(self.xydata[self.activexychannel][1]), 3) ) + " mV\n"
            if self.ui.actionMaximum.isChecked(): thestr += "Max: " + str( round( 1000* self.VperD[self.activeboard*2+self.selectedchannel] * np.max(self.xydata[self.activexychannel][1]), 3) ) + " mV\n"
            if self.ui.actionMinimum.isChecked(): thestr += "Min: " + str( round( 1000* self.VperD[self.activeboard*2+self.selectedchannel] * np.min(self.xydata[self.activexychannel][1]), 3) ) + " mV\n"
            if self.ui.actionVpp.isChecked(): thestr += "Vpp: " + str( round( 1000* self.VperD[self.activeboard*2+self.selectedchannel] * (np.max(self.xydata[self.activexychannel][1]) - np.min(self.xydata[self.activexychannel][1])), 3) ) + " mV\n"
            if self.ui.actionFreq.isChecked():
                sampling_rate = self.samplerate*1e9/self.downsamplefactor # Hz
                if self.dotwochannel: sampling_rate /= 2
                found_freq = find_fundamental_frequency_scipy(self.xydata[self.activexychannel][1], sampling_rate)
                thestr += "Freq: " + str(format_freq(found_freq)) + "\n"

            for i in range(3): self.otherlines[2+i].setVisible(False) # assume we're not drawing the risetime fit line
            if self.ui.actionRisetime.isChecked():
                if not self.dointerleaved[self.activeboard]:
                    targety = self.xydata[self.activexychannel]
                else:
                    targety = self.xydatainterleaved[int(self.activeboard/2)]
                fitwidth = (self.max_x - self.min_x) * self.fitwidthfraction
                xc = targety[0][(targety[0] > self.vline - fitwidth) & (targety[0] < self.vline + fitwidth)]  # only fit in range
                yc = targety[1][(targety[0] > self.vline - fitwidth) & (targety[0] < self.vline + fitwidth)]
                fallingedge = self.ui.risingfalling_comboBox.currentIndex() == 1
                if fallingedge:
                    p0 = [min(targety[1]), xc[xc.size//2], -2, max(targety[1])] #initial guess
                else:
                    p0 = [max(targety[1]), xc[xc.size//2], 2, min(targety[1])] #initial guess
                if xc.size < 10: # require at least something to fit, otherwise we'll throw an error
                    thestr += "Risetime: fit range too small\n"
                else:
                    with warnings.catch_warnings():
                        try:
                            warnings.simplefilter("ignore")
                            p0[1] -= (p0[0]-p0[3])/p0[2]/2 # correct the left edge inital guess
                            popt, pcov = curve_fit(fit_rise, xc, yc, p0)
                            perr = np.sqrt(np.diag(pcov))
                            #print(popt)
                            top = popt[0]
                            left = popt[1]
                            slope = popt[2]
                            bot = popt[3]
                            drawinitialguess=False
                            if drawinitialguess:
                                top = p0[0]  # popt[0]
                                left = p0[1]  # popt[1]
                                slope = p0[2]  # popt[2]
                                bot = p0[3]  # popt[3]
                            right = left+(top-bot)/slope
                            #print("right",right)
                            risetime = 0.6 * (top-bot)/slope # from 20 - 80%
                            if fallingedge: risetime*=-1
                            risetimeerr = 0.6 * 4 * (top-bot) * perr[2] / (slope*slope) # 4 is fudge factor, since the error is often underestimated
                            thestr += "Risetime: " + str(risetime.round(2)) + "+-" + str(risetimeerr.round(2)) + " " + self.units + str("\n")
                            if self.ui.actionRisetime_fit_lines.isChecked():
                                self.otherlines[2].setData([right, xc[-1]],[top, top])
                                self.otherlines[3].setData([left, right], [bot, top])
                                self.otherlines[4].setData([xc[0], left], [bot, bot])
                                #print(risetimeerr)
                                if abs(risetimeerr) != math.inf:
                                    for i in range(3): self.otherlines[2+i].setVisible(True)
                                else:
                                    self.otherlines[3].setData([xc[0], xc[-1]], [-2.0, 2.0])
                                    self.otherlines[3].setVisible(True)
                        except RuntimeError:
                            pass

        self.ui.textBrowser.setText(thestr)

    def auxout(self):
        val = self.ui.Auxout_comboBox.currentIndex()
        self.auxoutval[self.activeboard] = val # remember it
        auxoutselector(usbs[self.activeboard], val)

    def update_firmware(self):
        print("thinking about updating firmware on board",self.activeboard)
        firmwarepath = "../adc board firmware/output_files/coincidence_auto.rpd"
        if not os.path.exists(firmwarepath):
            firmwarepath = "../../../adc board firmware/output_files/coincidence_auto.rpd"
            if not os.path.exists(firmwarepath):
                print("coincidence_auto.rpd was not found!")
                return
        msg_box = QMessageBox()
        msg_box.setWindowTitle("Confirmation")
        msg_box.setText("Do you really want to update the firmware with "+firmwarepath)
        msg_box.setIcon(QMessageBox.Question)
        msg_box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg_box.setDefaultButton(QMessageBox.Cancel)  # Set default focused button
        reply = msg_box.exec_()
        if reply == QMessageBox.Cancel:
            print("update canceled!")
            return
        print("updating firmware on board",self.activeboard)
        starttime = time.time()
        for bo in range(self.num_board): clkout_ena(usbs[bo],0)
        doerase=True
        if doerase:
            print("erasing flash")
            flash_erase(usbs[self.activeboard])
            while flash_busy(usbs[self.activeboard],doprint=False)>0: time.sleep(.1)
            print("should be erased now")
        print("took",round(time.time()-starttime,3),"seconds so far")
        verifyerase=False
        if verifyerase:
            print("verifying flash erase")
            baderase=False
            readbytes = flash_readall(usbs[self.activeboard])
            for theb in range(len(readbytes)):
                if readbytes[theb]!=255:
                    print("byte",theb,"was",readbytes[theb])
                    baderase=True
            if not baderase: print("erase verified")
            else: return
        writtenbytes = flash_writeall_from_file(usbs[self.activeboard],firmwarepath, dowrite=True)
        print("took",round(time.time()-starttime,3),"seconds so far")
        print("verifying write")
        readbytes = flash_readall(usbs[self.activeboard])
        if writtenbytes == readbytes:
            print("verified!")
            print("took", round(time.time() - starttime, 3), "seconds")

            ver = version(usbs[self.activeboard], True)
            if ver>=29:
                # now reset the board and exit the softare
                reload_firmware(usbs[self.activeboard])
                self.closeEvent()
                print("Exiting software")
                sys.exit(0)
        else:
            print("not verified!!!")
            nbad=0
            for theb in range(len(writtenbytes)):
                if writtenbytes[theb] != readbytes[theb]:
                    print("byte",theb,"tried to write",writtenbytes[theb],"but read back",readbytes[theb])
                    nbad+=1
                    if nbad>50:
                        print("not showing more")
                        break
        for bo in range(self.num_board): clkout_ena(usbs[bo],self.num_board>1)

    def autocalibration(self, resamp=2, dofiner=False, oldtoff=0, finewidth=16):
        if not resamp: # called from GUI, defaults aren't filled
            resamp=2
            dofiner=False
            oldtoff=0
        print("autocalibration",resamp,dofiner,finewidth)
        if self.activeboard%2==1:
            print("Select the even board number first!")
            return
        if self.tad[self.activeboard]!=0:
            for t in range(255//5):
                if self.tad[self.activeboard]>0: self.ui.tadBox.setValue(self.tad[self.activeboard]-5)
                self.setTAD()
                time.sleep(.1) # be gentle
        c1 = self.activeboard * self.num_chan_per_board
        c = (self.activeboard + 1) * self.num_chan_per_board
        fitwidth = (self.max_x - self.min_x) * self.fitwidthfraction
        #bare_max_x = 4 * 10 * self.expect_samples * self.downsamplefactor / self.nsunits / self.samplerate
        #fitwidth = bare_max_x * self.fitwidthfraction
        c1data = self.xydata[c1] # active board data
        c1datanewy, c1datanewx = resample(c1data[1], len(c1data[0]) * resamp, t=c1data[0])
        cdata = self.xydata[c] # the exttrig board data
        cdatanewy, cdatanewx = resample(cdata[1], len(cdata[0]) * resamp, t=cdata[0])
        minrange = -self.toff * resamp
        if dofiner: minrange = (self.toff-oldtoff-finewidth)*resamp
        maxrange = 10*self.expect_samples*resamp
        if dofiner: maxrange = (self.toff-oldtoff+finewidth)*resamp
        print("min center max ranges",minrange,(minrange+maxrange)//2,maxrange)
        cdatanewy = np.roll(cdatanewy, minrange)
        minrms = 1e9
        minshift = 0
        for nshift in range(minrange, maxrange):
            yc = cdatanewy[(cdatanewx > self.vline - fitwidth) & (cdatanewx < self.vline + fitwidth)]
            yc1 = c1datanewy[(c1datanewx > self.vline - fitwidth) & (c1datanewx < self.vline + fitwidth)]
            therms = np.std(yc1 - yc) * (1+nshift/(20*self.expect_samples*resamp)) # bias towards lower shifts
            #if dofiner: print("nshift",nshift,"std",therms)
            if therms < minrms:
                minrms = therms
                minshift = nshift
            cdatanewy = np.roll(cdatanewy, 1)
        print("minrms found for shift =", minshift, "toff",self.toff,"have minshift//resamp",minshift//resamp,"and extra",minshift%resamp,"/",resamp)
        if dofiner:
            self.toff = minshift // resamp + oldtoff - 1  # the minus one lets us then adjust forward with TAD
            self.ui.ToffBox.setValue(self.toff)
            tadshift = round((138.4*2/resamp) * (minshift%resamp),1)
            tadshiftround = round(tadshift+138.4)
            print("should set TAD to",tadshift,"+ 138.4 ~=",tadshiftround)
            if tadshiftround<250: # good
                for t in range(255//5):
                    if abs(self.tad[self.activeboard] - tadshiftround)<5: break
                    if self.tad[self.activeboard]<tadshiftround: self.ui.tadBox.setValue(self.tad[self.activeboard]+5)
                    else: self.ui.tadBox.setValue(self.tad[self.activeboard]-5)
                    self.setTAD()
                    time.sleep(.1) # be gentle
            else: # too big a shift needed, adjust clock phases of other board and retry
                self.dophase(self.activeboard + 1, plloutnum=0, updown=1, pllnum=0)
                self.dophase(self.activeboard + 1, plloutnum=1, updown=1, pllnum=0)
                self.dophase(self.activeboard + 1, plloutnum=2, updown=1, pllnum=0)
                self.triggerautocalibration[self.activeboard+1] = True # ask for a new calibration once we've gotten the new board and board+1 data
                #self.autocalibration(64, True, oldtoff) # can't call from here because we won't take new data with the new phases
        else:
            oldtoff = self.toff
            self.toff = minshift//resamp + self.toff
            self.do_meanrms_calibration()
            self.autocalibration(64,True, oldtoff)

    def do_meanrms_calibration(self):
        c1 = self.activeboard * self.num_chan_per_board
        c = (self.activeboard + 1) * self.num_chan_per_board
        fitwidth = (self.max_x - self.min_x) * self.fitwidthfraction
        yc = self.xydata[c][1][
                (self.xydata[c][0] > self.vline - fitwidth) & (self.xydata[c][0] < self.vline + fitwidth)]
        yc1 = self.xydata[c1][1][
            (self.xydata[c1][0] > self.vline - fitwidth) & (self.xydata[c1][0] < self.vline + fitwidth)]
        extrigboardmean = np.mean(yc)
        otherboardmean = np.mean(yc1)
        self.extrigboardmeancorrection[self.activeboard] = self.extrigboardmeancorrection[self.activeboard] + extrigboardmean - otherboardmean
        extrigboardstd = np.std(yc)
        otherboardstd = np.std(yc1)
        if otherboardstd > 0:
            self.extrigboardstdcorrection[self.activeboard] = self.extrigboardstdcorrection[self.activeboard] * extrigboardstd / otherboardstd
        else:
            self.extrigboardstdcorrection[self.activeboard] = self.extrigboardstdcorrection[self.activeboard]
        print("calculated mean and std corrections", self.extrigboardmeancorrection[self.activeboard], self.extrigboardstdcorrection[self.activeboard])

    def plot_fft(self):
        if self.dointerleaved[self.activeboard]: y = self.xydatainterleaved[int(self.activeboard/2)][1]
        else: y = self.xydata[self.activeboard * self.num_chan_per_board + self.selectedchannel][1]  # channel signal to take fft of
        n = len(y)  # length of the signal
        k = np.arange(n)
        uspersample = self.downsamplefactor / self.samplerate / 1000.
        if self.dointerleaved[self.activeboard]: uspersample = uspersample/2
        # t = np.arange(0,1,1.0/n) * (n*uspersample) # time vector in us
        frq = (k / uspersample)[list(range(int(n / 2)))] / n  # one side frequency range up to Nyquist
        Y = np.fft.fft(y)[list(range(int(n / 2)))] / n  # fft computing and normalization
        Y[0] = 1e-3  # to suppress DC
        if np.max(frq) < .001:
            self.fftui.fftfreqplot_xdata = frq * 1000000.0
            self.fftui.fftax_xlabel = 'Frequency (Hz)'
            self.fftui.fftax_xlim = 1000000.0 * frq[int(n / 2) - 1]
        elif np.max(frq) < 1.0:
            self.fftui.fftfreqplot_xdata = frq * 1000.0
            self.fftui.fftax_xlabel = 'Frequency (kHz)'
            self.fftui.fftax_xlim = 1000.0 * frq[int(n / 2) - 1]
        else:
            self.fftui.fftfreqplot_xdata = frq
            self.fftui.fftax_xlabel = 'Frequency (MHz)'
            self.fftui.fftax_xlim = frq[int(n / 2) - 1]
        self.fftui.fftfreqplot_ydata = abs(Y)+1e-10
        self.fftui.fftfreqplot_ydatamax = np.max(self.fftui.fftfreqplot_ydata)
        self.fftui.fftfreqplot_ydatamin = np.min(self.fftui.fftfreqplot_ydata)

    def fastadclineclick(self, curve):
        for li in range(self.nlines):
            if curve is self.lines[li].curve:
                # print "selected curve", li
                self.ui.chanBox.setValue(li % self.num_chan_per_board)
                self.ui.boardBox.setValue(int(li / self.num_chan_per_board))
                # modifiers = app.keyboardModifiers()
                # if modifiers == QtCore.Qt.ShiftModifier:
                #     self.ui.trigchanonCheck.toggle()
                # elif modifiers == QtCore.Qt.ControlModifier:
                #     self.ui.chanonCheck.toggle()

    def use_ext_trigs(self):
        for board in range(1,self.num_board):
            self.ui.boardBox.setValue(board)
            self.exttrig(True)
            cu = clockused(usbs[board], board, False)
            if cu==0: switchclock(usbs[board],board)
            cu = clockused(usbs[board], board, False)
            assert cu==1
        self.ui.boardBox.setValue(0)

    def init(self):
        self.tot()
        self.ui.ToffBox.setValue(self.toff)
        self.setupchannels()
        self.launch()
        self.doleds()
        self.rolling()
        self.selectchannel()
        self.timechanged()
        self.use_ext_trigs()
        if self.num_board>0: self.dostartstop()
        self.open_socket()
        if self.num_board<2:
            self.ui.ToffBox.setEnabled(False)
            self.ui.tadBox.setEnabled(False)
        return 1

    def open_socket(self):
        print("starting socket thread")
        self.hsprosock = hspro_socket()
        self.hsprosock.hspro = self
        self.hsprosock.runthethread = True
        self.hsprosock_t1 = threading.Thread(target=self.hsprosock.open_socket, args=(10,))
        self.hsprosock_t1.start()

    def close_socket(self):
        self.hsprosock.runthethread = False
        self.hsprosock_t1.join()

    def doleds(self):
        for board in range(self.num_board):
            col1 = self.linepens[board * self.num_chan_per_board].color()
            r1 = col1.red()
            g1 = col1.green()
            b1 = col1.blue()
            r2 = 0
            g2 = 0
            b2 = 0
            if self.dotwochannel:
                col2 = self.linepens[board * self.num_chan_per_board + 1].color()
                r2 = col2.red()
                g2 = col2.green()
                b2 = col2.blue()
            if self.dooversample[board]:
                r2 = col1.red()
                g2 = col1.green()
                b2 = col1.blue()
                r1 = 0
                g1 = 0
                b1 = 0
            if self.dointerleaved[board] and board%2==1:
                col1 = self.linepens[(board-1) * self.num_chan_per_board].color()
                dim = 10 # factor by which to dim the second led
                r2 = col1.red()/dim
                g2 = col1.green()/dim
                b2 = col1.blue()/dim
            send_leds(usbs[board], r1, g1, b1, r2, g2, b2)

    def setupchannels(self):
        if hasattr(self,"hsprosock"):
            while self.hsprosock.issending: time.sleep(.001)
        if self.dotwochannel:
            self.xydata = np.empty([int(self.num_chan_per_board * self.num_board), 2, 2 * 10 * self.expect_samples], dtype=float)
        else:
            self.xydata = np.empty([int(self.num_chan_per_board * self.num_board), 2, 4 * 10 * self.expect_samples], dtype=float)
            self.xydatainterleaved = np.empty([int(self.num_chan_per_board * self.num_board), 2, 2 * 4 * 10 * self.expect_samples], dtype=float)

    def launch(self):
        self.nlines = self.num_chan_per_board * self.num_board
        chan=0
        colors = cm.rainbow(np.linspace(1.0, 0.1, self.nlines))
        for board in range(self.num_board):
            for boardchan in range( self.num_chan_per_board ):
                #print("chan=",chan, " board=",board, "boardchan=",boardchan)
                alpha = 1
                colors[chan][3] = alpha
                c = QColor.fromRgbF(*colors[chan])
                pen = pg.mkPen(color=c) # width=2 slows drawing down
                line = self.ui.plot.plot(pen=pen, name=self.chtext + str(chan), skipFiniteCheck=True, connect="finite")
                line.curve.setClickable(True)
                line.curve.sigClicked.connect(self.fastadclineclick)
                self.lines.append(line)
                self.linepens.append(pen)
                chan += 1

        for c in range(self.num_board*self.num_chan_per_board):
            if c%2==1:
                if self.dotwochannel: self.lines[c].setVisible(True)
                else: self.lines[c].setVisible(False)

        if self.dotwochannel: self.ui.chanBox.setMaximum(self.num_chan_per_board - 1)
        else: self.ui.chanBox.setMaximum(0)
        self.ui.boardBox.setMaximum(self.num_board - 1)

        # trigger lines
        self.vline = 0.0
        pen = pg.mkPen(color="w", width=1.0, style=QtCore.Qt.DashLine)
        line = self.ui.plot.plot([self.vline, self.vline], [-2.0, 2.0], pen=pen, name="trigger time vert", skipFiniteCheck=True, connect="finite")
        self.otherlines.append(line)

        self.hline = 0.0
        pen = pg.mkPen(color="w", width=1.0, style=QtCore.Qt.DashLine)
        line = self.ui.plot.plot([-2.0, 2.0], [self.hline, self.hline], pen=pen, name="trigger thresh horiz", skipFiniteCheck=True, connect="finite")
        self.otherlines.append(line)

        # risetime fit lines
        for i in range(3):
            pen = pg.mkPen(color="w", width=1.0, style=QtCore.Qt.DotLine)
            line = self.ui.plot.plot([700.0, 700.0], [-2.0, 2.0], pen=pen, name="risetime fit line", skipFiniteCheck=True, connect="finite")
            line.setVisible(False)
            self.otherlines.append(line)

        # other stuff
        # https://pyqtgraph.readthedocs.io/en/latest/api_reference/graphicsItems/plotitem.html
        self.ui.plot.setLabel('bottom', "Time (ns)")
        self.ui.plot.setLabel('left', "Voltage (divisions)")
        self.ui.plot.setRange(yRange=(self.min_y, self.max_y), padding=0.01)
        self.ui.plot.getAxis("left").setTickSpacing(1,.1)
        self.ui.plot.setBackground(QColor('black'))
        self.ui.plot.showGrid(x=True, y=True)
        for usb in usbs: self.telldownsample(usb, 0)

    def setup_connection(self, board):
        print("Setting up board",board)
        ver = version(usbs[board],False)
        if self.firmwareversion<0: self.firmwareversion = ver
        if ver < self.firmwareversion:
            print("Warning - this board has older firmware than another being used!")
            self.firmwareversion = ver # find the minimum firmware being used
        self.adfreset(board)
        setupboard(usbs[board], self.dopattern, self.dotwochannel, self.dooverrange)
        for c in range(self.num_chan_per_board):
            setchanacdc(usbs[board], c, 0, self.dooversample[board])
            setchanimpedance(usbs[board], c, 0, self.dooversample[board])
            setchanatt(usbs[board], c, 0, self.dooversample[board])
        setsplit(usbs[board], False)
        self.pllreset(board)
        auxoutselector(usbs[board],0)
        return 1

    def closeEvent(self, event=None):
        if event: print("Handling closeEvent")
        self.close_socket()
        self.timer.stop()
        self.timer2.stop()
        if self.dorecordtofile: self.outf.close()
        if self.fftui != 0: self.fftui.close()
        for usb in usbs: cleanup(usb)

    def take_screenshot(self):
        # Capture the entire window
        pixmap = self.grab()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"HaasoscopePro_{timestamp}.png"
        pixmap.save(filename)
        print(f"Screenshot saved as {filename}")

if __name__ == '__main__': # calls setup_connection for each board, then init
    print('Argument List:', str(sys.argv))
    for a in sys.argv:
        if a[0] == "-":
            print(a)
    print("Python version", sys.version)
    app = QtWidgets.QApplication.instance()
    standalone = app is None
    if standalone:
        app = QtWidgets.QApplication(sys.argv)
    try:
        font = app.font()
        font.setPixelSize(11)
        app.setFont(font)
        app.setWindowIcon(QIcon('icon.png'))
        win = MainWindow()
        win.setWindowTitle('Haasoscope Pro Qt')
        for usbi in range(len(usbs)):
            if not win.setup_connection(usbi):
                print("Exiting now - failed setup_connections!")
                cleanup(usbs[usbi])
                sys.exit(1)
        if not win.init():
            print("Exiting now - failed init!")
            for usbi in usbs: cleanup(usbi)
            sys.exit(2)
    except ftd2xx.DeviceError:
        print("Device com failed!")
        self.close_socket()
    if standalone:
        rv = app.exec_()
        sys.exit(rv)
    else:
        print("Done, but Qt window still active!")
