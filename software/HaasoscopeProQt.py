import numpy as np
import sys, time, warnings
import pyqtgraph as pg
import PyQt5
from pyqtgraph.Qt import QtCore, QtWidgets, loadUiType
from PyQt5.QtGui import QPalette, QColor
from scipy.optimize import curve_fit
from scipy.signal import resample
import struct
from usbs import *
from board import *

usbs = connectdevices()
if len(usbs)==0: sys.exit(0)
for b in range(len(usbs)):
    version(usbs[b])
    version(usbs[b])
    version(usbs[b])
usbs = orderusbs(usbs)

# Define fft window class from template
FFTWindowTemplate, FFTTemplateBaseClass = loadUiType("HaasoscopeProFFT.ui")
class FFTWindow(FFTTemplateBaseClass):
    def __init__(self):
        FFTTemplateBaseClass.__init__(self)
        self.ui = FFTWindowTemplate()
        self.ui.setupUi(self)
        self.ui.plot.setLabel('bottom', 'Frequency (MHz)')
        self.ui.plot.setLabel('left', 'Amplitude')
        self.ui.plot.showGrid(x=True, y=True, alpha=1.0)
        #self.ui.plot.setRange(xRange=(0.0, 1600.0))
        self.ui.plot.setBackground('w')
        c = (10, 10, 10)
        self.fftpen = pg.mkPen(color=c)  # add linewidth=0.5, alpha=.5
        self.fftline = self.ui.plot.plot(pen=self.fftpen, name="fft_plot")
        self.fftlastTime = time.time() - 10
        self.fftyrange = 1

# Define main window class from template
WindowTemplate, TemplateBaseClass = loadUiType("HaasoscopePro.ui")
class MainWindow(TemplateBaseClass):

    expect_samples = 100
    expect_samples_extra = 5 # enough to cover downsample shifting and toff shifting
    samplerate = 3.2  # freq in GHz
    nsunits = 1
    num_board = len(usbs)
    num_chan_per_board = 2
    num_logic_inputs = 0
    tenx = 1
    debug = False
    dopattern = 0 # set to 4 to do max varying test pattern
    debugprint = True
    showbinarydata = True
    debugstrobe = False
    dofast = False
    dotwochannel = False
    dointerleaved = False
    dooverrange = False
    total_rx_len = 0
    time_start = time.time()
    triggertype = 1
    isrolling = 0
    selectedchannel = 0
    activeusb = usbs[0]
    activeboard = 0
    activexychannel = 0
    tad = 0
    toff = 0
    themuxoutV = True
    phasecs = []
    for ph in range(len(usbs)): phasecs.append([[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]])
    phaseoffset = 2 # how many positive phase steps to take from middle of good range
    doexttrig = [0] * num_board
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
    triggerchan = 0
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
    doeventcounter = False
    fitwidthfraction = 0.2
    extrigboardstdcorrection = 1
    extrigboardmeancorrection = 0
    lastrate = 0
    lastsize = 0
    dodirect = True
    VperD = [0.16]*(num_board*2)
    plljustreset = [0] * num_board
    plljustresetdir = 0
    phasenbad = [0] * 12
    dooversample = False
    doresamp = 0

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
        self.ui.risingedgeCheck.stateChanged.connect(self.risingfalling)
        self.ui.exttrigCheck.stateChanged.connect(self.exttrig)
        self.ui.totBox.valueChanged.connect(self.tot)
        self.ui.depthBox.valueChanged.connect(self.depth)
        self.ui.boardBox.valueChanged.connect(self.boardchanged)
        self.ui.triggerChanBox.valueChanged.connect(self.triggerchanchanged)
        self.ui.gridCheck.stateChanged.connect(self.grid)
        self.ui.markerCheck.stateChanged.connect(self.marker)
        self.ui.highresCheck.stateChanged.connect(self.highres)
        self.ui.pllresetButton.clicked.connect(self.pllreset)
        self.ui.adfresetButton.clicked.connect(self.adfreset)
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
        self.ui.ohmCheck.stateChanged.connect(self.setohm)
        self.ui.oversampCheck.stateChanged.connect(self.setoversamp)
        self.ui.interleavedCheck.stateChanged.connect(self.interleave)
        self.ui.attCheck.stateChanged.connect(self.setatt)
        self.ui.tenxCheck.stateChanged.connect(self.settenx)
        self.ui.chanonCheck.stateChanged.connect(self.chanon)
        self.ui.drawingCheck.clicked.connect(self.drawing)
        self.ui.persistCheck.clicked.connect(self.persist)
        self.ui.fwfBox.valueChanged.connect(self.fwf)
        self.ui.tadBox.valueChanged.connect(self.setTAD)
        self.ui.resampBox.valueChanged.connect(self.resamp)
        self.ui.twochanCheck.clicked.connect(self.twochan)
        self.ui.ToffBox.valueChanged.connect(self.setToff)
        self.ui.fftCheck.clicked.connect(self.fft)
        self.ui.actionDo_autocalibration.triggered.connect(self.actionDo_autocalibration)
        self.dofft = False
        self.db = False
        self.lastTime = time.time()
        self.fps = None
        self.lastclk = -1
        self.lines = []
        self.otherlines = []
        self.savetofile = False  # save scope data to file
        self.doh5 = False  # use the h5 binary file format
        self.numrecordeventsperfile = 1000  # number of events in each file to record before opening new file
        self.timer = QtCore.QTimer()
        # noinspection PyUnresolvedReferences
        self.timer.timeout.connect(self.updateplot)
        self.timer2 = QtCore.QTimer()
        # noinspection PyUnresolvedReferences
        self.timer2.timeout.connect(self.drawtext)
        self.ui.statusBar.showMessage("Hello!")
        self.ui.plot.setBackground('w')
        self.show()

    def boardchanged(self):
        self.activeusb = usbs[self.ui.boardBox.value()]
        self.activeboard = self.ui.boardBox.value()
        self.selectchannel()

    def selectchannel(self):
        if self.activeboard%2==0:
            self.ui.exttrigCheck.setEnabled(False)
            self.ui.oversampCheck.setEnabled(True)
            if self.dooversample: self.ui.interleavedCheck.setEnabled(True)
        else:
            self.ui.exttrigCheck.setEnabled(True)
            self.ui.oversampCheck.setEnabled(False)
            self.ui.interleavedCheck.setEnabled(False)
        if self.doexttrig[self.activeboard]: self.ui.exttrigCheck.setChecked(True)
        else: self.ui.exttrigCheck.setChecked(False)
        self.selectedchannel = self.ui.chanBox.value()
        self.activexychannel = self.activeboard*self.num_chan_per_board + self.selectedchannel
        p = self.ui.chanColor.palette()
        col = QColor("red")
        if self.activexychannel==1: col = QColor("green")
        if self.activexychannel==2: col = QColor("blue")
        if self.activexychannel==3: col = QColor("magenta")
        if self.activexychannel>=4: print("Not ready for >2 boards yet!")
        p.setColor(QPalette.Base, col)  # Set background color of box
        self.ui.chanColor.setPalette(p)
        if self.lines[self.activexychannel].isVisible():
            self.ui.chanonCheck.setCheckState(QtCore.Qt.Checked)
        else:
            self.ui.chanonCheck.setCheckState(QtCore.Qt.Unchecked)

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
        self.setupchannels()
        self.doleds()
        for usb in usbs: setupboard(usb,self.dopattern,self.dotwochannel,self.dooverrange)
        for usb in usbs: self.telldownsample(usb, self.downsample)
        self.timechanged()
        if self.dotwochannel:
            self.ui.chanBox.setMaximum(self.num_chan_per_board - 1)
            self.ui.oversampCheck.setEnabled(False)
        else:
            self.ui.chanBox.setMaximum(0)
            self.ui.oversampCheck.setEnabled(True)
        for c in range(self.num_board*self.num_chan_per_board):
            if c%2==1:
                if self.dotwochannel: self.lines[c].setVisible(True)
                else: self.lines[c].setVisible(False)

    def changeoffset(self):
        scaling = 1000*self.VperD[self.activeboard*2+self.selectedchannel]/160 # compare to 0 dB gain
        if dooffset(self.activeusb, self.selectedchannel, self.ui.offsetBox.value(),scaling/self.tenx,self.dooversample):
            if self.dooversample and self.ui.boardBox.value()%2==0: # also adjust other board we're oversampling with
                dooffset(usbs[self.ui.boardBox.value()+1], self.selectedchannel, self.ui.offsetBox.value(),scaling/self.tenx,self.dooversample)
            v2 = scaling*1.5*self.ui.offsetBox.value()
            if self.dooversample: v2 *= 2.0
            self.ui.Voff.setText(str(int(v2))+" mV")

    def changegain(self):
        setgain(self.activeusb, self.selectedchannel, self.ui.gainBox.value(),self.dooversample)
        if self.dooversample and self.ui.boardBox.value()%2==0: # also adjust other board we're oversampling with
            setgain(usbs[self.ui.boardBox.value()+1], self.selectedchannel, self.ui.gainBox.value(),self.dooversample)
        db = self.ui.gainBox.value()
        v2 = 0.1605*self.tenx/pow(10, db / 20.) # 0.16 V at 0 dB gain
        if self.dooversample: v2 *= 2.0
        oldvperd = self.VperD[self.activeboard*2+self.selectedchannel]
        self.VperD[self.activeboard*2+self.selectedchannel] = v2
        if self.dooversample and self.ui.boardBox.value()%2==0: # also adjust other board we're oversampling with
            self.VperD[(self.activeboard+1)*2+self.selectedchannel] = v2
        self.ui.offsetBox.setValue(int(self.ui.offsetBox.value()*oldvperd/v2))
        v2 = round(1000*v2,0)
        self.ui.VperD.setText(str(int(v2))+" mV/div")
        if self.ui.gainBox.value()>24: self.ui.gainBox.setSingleStep(2)
        else: self.ui.gainBox.setSingleStep(6)

    def fwf(self):
        self.fitwidthfraction = self.ui.fwfBox.value() / 100.

    def setTAD(self):
        if self.tad<0 and self.ui.tadBox.value()>=0:
            spicommand(self.activeusb, "TAD", 0x02, 0xB7, 0, False, quiet=False)
        if self.tad>=0 and self.ui.tadBox.value()<0:
            spicommand(self.activeusb, "TAD", 0x02, 0xB7, 1, False, quiet=False)
        self.tad = self.ui.tadBox.value()
        spicommand(self.activeusb, "TAD", 0x02, 0xB6, abs(self.tad), False, quiet=True)

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
        setchanacdc(self.activeusb, self.selectedchannel,
                    self.ui.acdcCheck.checkState() == QtCore.Qt.Checked, self.dooversample)  # will be True for AC, False for DC
        if self.dooversample and self.ui.boardBox.value() % 2 == 0:  # also adjust other board we're oversampling with
            setchanacdc(usbs[self.ui.boardBox.value()+1], self.selectedchannel,
                    self.ui.acdcCheck.checkState() == QtCore.Qt.Checked, self.dooversample)

    def setohm(self):
        setchanimpedance(self.activeusb, self.selectedchannel,
                         self.ui.ohmCheck.checkState() == QtCore.Qt.Checked, self.dooversample)  # will be True for 1M ohm, False for 50 ohm

    def setatt(self):
        setchanatt(self.activeusb, self.selectedchannel,
                   self.ui.attCheck.checkState() == QtCore.Qt.Checked, self.dooversample)  # will be True for attenuation on

    def settenx(self):
        if self.ui.tenxCheck.checkState() == QtCore.Qt.Checked:
            self.tenx = 10
        else:
            self.tenx = 1
        self.changegain()

    def setoversamp(self):
        self.dooversample = self.ui.oversampCheck.checkState() == QtCore.Qt.Checked # will be True for oversampling, False otherwise
        setsplit(self.activeusb,self.dooversample)
        setsplit(usbs[self.activeboard+1], False)
        for usb in usbs: swapinputs(usb,self.dooversample)
        if self.dooversample:
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
        self.dointerleaved = self.ui.interleavedCheck.checkState() == QtCore.Qt.Checked
        c = (self.activeboard+1) * self.num_chan_per_board
        if self.dointerleaved:
            self.lines[c].setVisible(False)
            self.ui.boardBox.setMaximum(int(self.num_board/2)-1)
        else:
            self.lines[c].setVisible(True)
            self.ui.boardBox.setMaximum(self.num_board-1)
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
        tres = usbs[board].recv(4)
        print("pllreset sent to board",board,"- got back:", tres[3], tres[2], tres[1], tres[0])
        self.phasecs[board] = [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]]  # reset counters
        self.plljustreset[board] = 0
        self.plljustresetdir = 1
        self.phasenbad = [0]*12 # reset nbad counters
        switchclock(usbs,board)

    def adjustclocks(self, board, nbadclkA, nbadclkB, nbadclkC, nbadclkD, nbadstr):
        if 0<=self.plljustreset[board]<12: # we start by going up in phase
            nbad = nbadclkA + nbadclkB + nbadclkC + nbadclkD + nbadstr
            #print("plljustreset for board",board,"is",self.plljustreset[board],"nbad",nbad)
            self.phasenbad[self.plljustreset[board]]+=nbad
            #print(self.phasenbad)
            self.dophase(board, 0, (self.plljustresetdir==1), pllnum=0, quiet=True) # adjust phase of clklvds
            self.plljustreset[board]+=self.plljustresetdir
        if self.plljustreset[board]==12:
            #print("plljustreset for board",board,"is",self.plljustreset[board])
            self.plljustresetdir=-1
            self.plljustreset[board] += self.plljustresetdir
            self.dophase(board, 0, (self.plljustresetdir == 1), pllnum=0, quiet=True)  # adjust phase of clklvds
        if self.plljustreset[board]==-1:
            #print("plljustreset for board",board,"is",self.plljustreset[board])
            print("bad clkstr per phase step:",self.phasenbad)
            startofzeros, lengthofzeros = find_longest_zero_stretch(self.phasenbad, True)
            print("good phase starts at",startofzeros, "and goes for", lengthofzeros,"steps")
            if startofzeros>=12: startofzeros-=12
            n = startofzeros + lengthofzeros//2 + self.phaseoffset # amount to adjust clklvds (positive)
            if n>=12: n-=12
            for i in range(n+1): self.dophase(board, 0, 1, pllnum=0, quiet=(i != n - 1)) # adjust phase of clklvds, extra 1 because we went to phase=-1 before
            self.plljustreset[board] += self.plljustresetdir

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
        r = self.ui.rollingButton.isChecked()
        if self.doexttrig[board]: r = False
        print("setting rolling",r,"for board",board)
        usbs[board].send(bytes([2, 8, r, 0, 100, 100, 100, 100]))
        usbs[board].recv(4)

    def grid(self):
        if self.ui.gridCheck.isChecked():
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
            for usb in usbs: self.sendtriggerinfo(usb)
            self.drawtriggerlines()

    def triggerdeltachanged(self, value):
        if value + self.triggerlevel < 256 and self.triggerlevel - value > 0:
            self.triggerdelta = value
            for usb in usbs: self.sendtriggerinfo(usb)

    def triggerposchanged(self, value):
        self.triggerpos = int(self.expect_samples * value / 100)
        for usb in usbs: self.sendtriggerinfo(usb)
        self.drawtriggerlines()

    def triggerchanchanged(self):
        self.triggerchan = self.ui.triggerChanBox.value()
        for usb in usbs: self.sendtriggerinfo(usb)

    def sendtriggerinfo(self, usb):
        usb.send(bytes([8, self.triggerlevel + 1, self.triggerdelta, int(self.triggerpos / 256), self.triggerpos % 256,
                        self.triggertimethresh, self.triggerchan, 100]))
        usb.recv(4)
        # length to take after trigger is self.expect_samples - self.triggerpos + 1
        # we want self.expected_samples - that, which is about self.triggerpos, and then pad a little
        prelengthtotake = self.triggerpos + 4
        usb.send(bytes([2, 7]+inttobytes(prelengthtotake)+[0,0]))
        usb.recv(4)

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
        for usb in usbs: self.sendtriggerinfo(usb)

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

        # for testing flash functions
        # flash_readall_to_file(usbs[0])
        # flash_erase(usbs[0])
        # lowbyte=2
        # flash_read_print(usbs[0],20,0, lowbyte)
        # flash_write(usbs[0], 20,0, lowbyte,102)
        # flash_read_print(usbs[0], 20,0, lowbyte)

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
        if self.dotwochannel:
            for c in range(self.num_chan_per_board * self.num_board):
                self.xydata[c][0] = np.array([range(0, 2 * 10 * self.expect_samples)]) * (
                            2 * self.downsamplefactor / self.nsunits / self.samplerate)
        else:
            for c in range(self.num_chan_per_board * self.num_board):
                self.xydata[c][0] = np.array([range(0, 4 * 10 * self.expect_samples)]) * (
                            1 * self.downsamplefactor / self.nsunits / self.samplerate)
                if self.num_board%2==0 and self.dointerleaved:
                    self.xydatainterleaved[c][0] = np.array([range(0, 2 * 4 * 10 * self.expect_samples)]) * (
                            0.5 * self.downsamplefactor / self.nsunits / self.samplerate)
        self.ui.plot.setRange(xRange=(self.min_x, self.max_x), padding=0.00)
        self.ui.plot.setRange(yRange=(self.min_y, self.max_y), padding=0.01)
        self.drawtriggerlines()
        self.ui.timebaseBox.setText("2^"+str(self.downsample))

    def risingfalling(self):
        fallingedge = not self.ui.risingedgeCheck.checkState()
        if self.triggertype == 1:
            if fallingedge: self.triggertype = 2
        if self.triggertype == 2:
            if not fallingedge: self.triggertype = 1

    def drawing(self):
        if self.ui.drawingCheck.checkState() == QtCore.Qt.Checked:
            self.dodrawing = True
            # print("drawing now",self.dodrawing)
        else:
            self.dodrawing = False
            # print("drawing now",self.dodrawing)

    def persist(self):
        self.dodirect = not self.dodirect
        print("do direct array drawing now",self.dodirect)

    def updateplot(self):
        self.getevent()
        self.statuscounter = self.statuscounter + 1
        now = time.time()
        dt = now - self.lastTime + 0.00001
        self.lastTime = now
        if self.fps is None:
            self.fps = 1.0 / dt
        else:
            s = np.clip(dt * 3., 0, 1)
            self.fps = self.fps * (1 - s) + (1.0 / dt) * s
        if self.statuscounter % 20 == 0: self.ui.statusBar.showMessage("%0.2f fps, %d events, %0.2f Hz, %0.2f MB/s" % (
            self.fps, self.nevents, self.lastrate, self.lastrate * self.lastsize / 1e6))
        if not self.dodrawing: return
        # self.ui.plot.setTitle("%0.2f fps, %d events, %0.2f Hz, %0.2f MB/s"%(self.fps,self.nevents,self.lastrate,self.lastrate*self.lastsize/1e6))
        for li in range(self.nlines):
            if not self.dointerleaved:
                if self.doresamp:
                    ydatanew, xdatanew = resample(self.xydata[li][1], len(self.xydata[li][0]) * self.doresamp, t=self.xydata[li][0])
                    self.lines[li].setData(xdatanew,ydatanew)
                else:
                    self.lines[li].setData(self.xydata[li][0], self.xydata[li][1])
            else:
                if li%4 == 0:
                    self.xydatainterleaved[int(li/2)][1][0::2] = self.xydata[li][1]
                    self.xydatainterleaved[int(li/2)][1][1::2] = self.xydata[li+self.num_chan_per_board][1]
                    if self.doresamp:
                        ydatanew, xdatanew = resample(self.xydatainterleaved[int(li/2)][1], len(self.xydatainterleaved[int(li/2)][0]) * self.doresamp, t=self.xydatainterleaved[int(li/2)][0])
                        self.lines[li].setData(xdatanew,ydatanew)
                    else:
                        self.lines[li].setData(self.xydatainterleaved[int(li/2)][0],self.xydatainterleaved[int(li/2)][1])

        if self.dofft and hasattr(self.fftui,"fftfreqplot_xdata"):
            self.fftui.fftline.setPen(self.linepens[self.activeboard * self.num_chan_per_board + self.selectedchannel])
            self.fftui.fftline.setData(self.fftui.fftfreqplot_xdata,self.fftui.fftfreqplot_ydata)
            self.fftui.ui.plot.setTitle('Haasoscope Pro FFT of board '+str(self.activeboard)+' channel ' + str(self.selectedchannel))
            self.fftui.ui.plot.setLabel('bottom', self.fftui.fftax_xlabel)
            self.fftui.ui.plot.setRange(xRange=(0.0, self.fftui.fftax_xlim))
            now = time.time()
            dt = now - self.fftui.fftlastTime
            if dt>3.0 or self.fftui.fftyrange<self.fftui.fftfreqplot_ydatamax*1.1:
                self.fftui.fftlastTime = now
                self.fftui.ui.plot.setRange(yRange=(0.0, self.fftui.fftfreqplot_ydatamax*1.1))
                self.fftui.fftyrange = self.fftui.fftfreqplot_ydatamax * 1.1
            if not self.fftui.isVisible(): # closed the fft window
                self.dofft = False
                self.ui.fftCheck.setCheckState(QtCore.Qt.Unchecked)
        app.processEvents()

    def getevent(self):
        if self.paused:
            time.sleep(.1)
        else:
            rx_len = 0
            try:
                readyevent = [0]*self.num_board
                for board in reversed(range(self.num_board)): # go backwards through the boards to make sure the ext triggers are active before the lower number board fires
                    readyevent[board] = self.getchannels(board)
                for board in range(self.num_board):
                    if not readyevent[board]: continue
                    downsamplemergingcounter = self.getpredata(board)
                    data = self.getdata(usbs[board])
                    rx_len = rx_len + len(data)
                    if self.dofft and board==self.activeboard: self.plot_fft()
                    self.drawchannels(data, board, downsamplemergingcounter)
                if self.getone and rx_len > 0:
                    self.dostartstop()
                    self.drawtext()
            except ftd2xx.DeviceError:
                print("Device error")
                sys.exit(1)
            if self.db: print(time.time() - self.oldtime, "done with evt", self.nevents)
            if rx_len > 0: self.nevents += 1
            if self.nevents - self.oldnevents >= self.tinterval:
                now = time.time()
                elapsedtime = now - self.oldtime
                self.oldtime = now
                self.lastrate = round(self.tinterval / elapsedtime, 2)
                self.lastsize = rx_len
                if not self.dodrawing: print(self.nevents, "events,", self.lastrate, "Hz",
                                             round(self.lastrate * self.lastsize / 1e6, 3), "MB/s")
                self.oldnevents = self.nevents

    def getchannels(self, board):
        tt = self.triggertype
        if self.doexttrig[board] > 0: tt = 3
        usbs[board].send(bytes([1, tt, self.dotwochannel+2*self.dooversample, 99] + inttobytes(
            self.expect_samples - self.triggerpos + 1)))  # length to take after trigger (last 4 bytes)
        triggercounter = usbs[board].recv(4)  # get the 4 bytes
        acqstate = triggercounter[0]
        if acqstate == 251:  # an event is ready to be read out
            #print("board",board,"sample triggered", binprint(triggercounter[3]), binprint(triggercounter[2]), binprint(triggercounter[1]))
            gotzerobit = False
            for s in range(21):
                thebit = getbit(triggercounter[int(s / 8) + 1], s % 8)
                if thebit == 0: gotzerobit = True
                if thebit == 1 and gotzerobit:
                    self.sample_triggered[board] = s
                    gotzerobit = False
            #if self.sample_triggered[board]<10: self.sample_triggered[board] += 0
            #print("sample_triggered", self.sample_triggered[board], "for board", board)
            return 1
        else:
            return 0

    def getpredata(self, board):
        if self.doeventcounter:
            usbs[board].send(bytes([2, 3, 100, 100, 100, 100, 100, 100]))  # get eventcounter
            res = usbs[board].recv(4)
            eventcountertemp = res[0] + 256 * res[1] + 256 * 256 * res[2] + 256 * 256 * 256 * res[3]
            if eventcountertemp != self.eventcounter[board] + 1 and eventcountertemp != 0:  # check event count, but account for rollover
                print("Event counter not incremented by 1?", eventcountertemp, self.eventcounter[board], " for board", board)
            self.eventcounter[board] = eventcountertemp
        downsamplemergingcounter = 0
        if self.downsamplemerging > 1:
            usbs[board].send(bytes([2, 4, 100, 100, 100, 100, 100, 100]))  # get downsamplemergingcounter
            res = usbs[board].recv(4)
            downsamplemergingcounter = res[0]
            if downsamplemergingcounter == self.downsamplemerging:
                if not self.doexttrig[board]:
                    downsamplemergingcounter = 0
            # print("downsamplemergingcounter", downsamplemergingcounter)
        return downsamplemergingcounter

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

    def drawchannels(self, data, board, downsamplemergingcounter):
        if self.dofast: return
        if self.doexttrig[board]:
            if board % 2 == 1: boardtouse = board-1
            else: boardtouse = board+1
            self.sample_triggered[board] = self.sample_triggered[boardtouse] # take from the other board when interleaving using ext trig
        nbadclkA = 0
        nbadclkB = 0
        nbadclkC = 0
        nbadclkD = 0
        nbadstr = 0
        unpackedsamples = struct.unpack('<' + 'h' * (len(data) // 2), data)
        npunpackedsamples = None
        if self.dodirect:
            npunpackedsamples = np.array(unpackedsamples, dtype='float')
            npunpackedsamples *= self.yscale
            if self.dooversample and board % 2 == 0:
                npunpackedsamples += self.extrigboardmeancorrection
                npunpackedsamples *= self.extrigboardstdcorrection
        downsampleoffset = 2 * (self.sample_triggered[board] + (downsamplemergingcounter-1)%self.downsamplemerging * 10) // self.downsamplemerging
        if not self.dotwochannel: downsampleoffset *= 2
        if self.doexttrig[board]: downsampleoffset -= self.toff // self.downsamplefactor
        datasize = self.xydata[board][1].size
        for s in range(0, self.expect_samples+self.expect_samples_extra):

            if self.dodirect: #This is the new faster way of doing things
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
                    samp = s*20 - downsampleoffset
                    nsamp=20
                    if samp<0:
                        nsamp = 20 + samp
                        samp = 0
                    if samp+20 >= datasize:
                        nsamp = datasize - samp
                    if 0 < nsamp <= 20:
                        self.xydata[board * self.num_chan_per_board+0][1][samp:samp + nsamp] = npunpackedsamples[s * self.nsubsamples+20:s * self.nsubsamples+20 + nsamp]
                        self.xydata[board * self.num_chan_per_board+1][1][samp:samp + nsamp] = npunpackedsamples[s * self.nsubsamples:s * self.nsubsamples + nsamp]
                else:
                    samp = s*40 - downsampleoffset
                    nsamp=40
                    if samp<0:
                        nsamp = 40 + samp
                        samp = 0
                    if samp+40 >= datasize:
                        nsamp = datasize - samp
                    if 0 < nsamp <= 40:
                        self.xydata[board * self.num_chan_per_board][1][samp:samp + nsamp] = npunpackedsamples[s * self.nsubsamples:s * self.nsubsamples + nsamp]

            else: # This is the older slower way
                for n in range(self.nsubsamples): # the subsample to get
                    val = unpackedsamples[s*self.nsubsamples + n] # this will be 16x larger than the 12 bit value, since it's shifted 4 bits to the left
                    if 40 <= n < 44:
                        if val!=341 and val!= 682: # 0101010101 or 1010101010
                            if n == 40: nbadclkA += 1
                            if n == 41: nbadclkB += 1
                            if n == 42: nbadclkC += 1
                            if n == 43: nbadclkD += 1
                            #print("s=", s, "n=", n, "clk", val, binprint(val))
                        else: self.lastclk = val
                    if (44 <= n < 48) and (val not in {0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512}):
                        # 10 bits long, and just one 1
                        nbadstr = nbadstr + 1
                        #print("s=", s, "n=", n, "str", val, binprint(val))
                    if n < 40:
                        val = val * self.yscale
                        if self.dooversample and board%2==0:
                            val += self.extrigboardmeancorrection
                            val *= self.extrigboardstdcorrection
                        if self.dotwochannel:
                            samp = s*20 + n - downsampleoffset
                            if n>=20: samp -= 20
                            if 0 <= samp < datasize: self.xydata[board*self.num_chan_per_board + (n<20)][1][samp] = val
                        else:
                            samp = s*40 + n - downsampleoffset
                            if 0 <= samp < datasize: self.xydata[board*self.num_chan_per_board][1][samp] = val

        self.adjustclocks(board, nbadclkA, nbadclkB, nbadclkC, nbadclkD, nbadstr)
        if board == self.activeboard:
            self.nbadclkA = nbadclkA
            self.nbadclkB = nbadclkB
            self.nbadclkC = nbadclkC
            self.nbadclkD = nbadclkD
            self.nbadstr = nbadstr

    def drawtext(self):  # happens once per second
        if not self.dodrawing: return
        thestr = "Nbadclks A B C D " + str(self.nbadclkA) + " " + str(self.nbadclkB) + " " + str(self.nbadclkC) + " " + str(self.nbadclkD)
        thestr += "\n" + "Nbadstrobes " + str(self.nbadstr)
        thestr += "\n" + "Last clk "+str(self.lastclk)
        thestr += "\n" + gettemps(self.activeusb)
        thestr += "\n" + "Trigger threshold " + str(round(self.hline, 3))
        thestr += "\n" + "Mean " + str( round( 1000* self.VperD[self.activeboard*2+self.selectedchannel] * np.mean(self.xydata[self.activexychannel][1]), 3) ) + " mV"
        thestr += "\n" + "RMS " + str( round( 1000* self.VperD[self.activeboard*2+self.selectedchannel] * np.std(self.xydata[self.activexychannel][1]), 3) ) + " mV"

        if not self.dointerleaved:
            targety = self.xydata[self.activexychannel]
        else:
            targety = self.xydatainterleaved[int(self.activeboard/2)]
        p0 = [max(targety[1]), self.vline - 10, 20, min(targety[1])]  # this is an initial guess
        fitwidth = (self.max_x - self.min_x) * self.fitwidthfraction
        xc = targety[0][(targety[0] > self.vline - fitwidth) & (targety[0] < self.vline + fitwidth)]  # only fit in range
        yc = targety[1][(targety[0] > self.vline - fitwidth) & (targety[0] < self.vline + fitwidth)]
        if xc.size > 10: # require at least something to fit, otherwise we'll through an area
            with warnings.catch_warnings():
                try:
                    warnings.simplefilter("ignore")
                    popt, pcov = curve_fit(fit_rise, xc, yc, p0)
                    perr = np.sqrt(np.diag(pcov))
                    risetime = 0.8 * popt[2]
                    risetimeerr = perr[2]
                    # print(popt)
                    thestr += "\n" + "Rise time " + str(risetime.round(2)) + "+-" + str(risetimeerr.round(2)) + " " + self.units
                except RuntimeError:
                    pass

        self.ui.textBrowser.setText(thestr)

    def actionDo_autocalibration(self):
        c1 = self.activeboard  # board data we are merging with
        if c1 >= self.num_board - 1: return
        c = (self.activeboard + 1) * self.num_chan_per_board  # the exttrig board data
        # fitwidth = (self.max_x - self.min_x) * self.fitwidthfraction
        bare_max_x = 4 * 10 * self.expect_samples * self.downsamplefactor / self.nsunits / self.samplerate
        fitwidth = bare_max_x * self.fitwidthfraction
        cdata = self.xydata[c]
        cdata[1] = np.roll(cdata[1], -self.toff)
        minrms = 1e9
        minshift = 1000000
        for nshift in range(-self.toff, 20*self.expect_samples):
            yc = cdata[1][(cdata[0] > self.vline - fitwidth) & (cdata[0] < self.vline + fitwidth)]
            yc1 = self.xydata[c1][1][
                (self.xydata[c1][0] > self.vline - fitwidth) & (self.xydata[c1][0] < self.vline + fitwidth)]
            therms = np.std(yc1 - yc)
            # print("nshift",nshift,"std",therms)
            if therms < minrms:
                minrms = therms
                minshift = nshift
            cdata[1] = np.roll(cdata[1], 1)
        #print("minrms found for toff =", minshift)
        minshift = minshift - 1 #better for interleaving
        self.toff = minshift + self.toff
        self.ui.ToffBox.setValue(self.toff)
        cdata[1] = np.roll(cdata[1], -20*self.expect_samples + minshift)

        yc = self.xydata[c][1][
            (self.xydata[c][0] > self.vline - fitwidth) & (self.xydata[c][0] < self.vline + fitwidth)]
        yc1 = self.xydata[c1][1][
            (self.xydata[c1][0] > self.vline - fitwidth) & (self.xydata[c1][0] < self.vline + fitwidth)]
        extrigboardmean = np.mean(yc)
        otherboardmean = np.mean(yc1)
        self.extrigboardmeancorrection = self.extrigboardmeancorrection + extrigboardmean - otherboardmean
        extrigboardstd = np.std(yc)
        otherboardstd = np.std(yc1)
        if otherboardstd > 0:
            self.extrigboardstdcorrection = self.extrigboardstdcorrection * extrigboardstd / otherboardstd
        else:
            self.extrigboardstdcorrection = self.extrigboardstdcorrection
        print("calculated mean and std corrections", self.extrigboardmeancorrection, self.extrigboardstdcorrection)

    def plot_fft(self):
        if self.dointerleaved: y = self.xydatainterleaved[int(self.activeboard/2)][1]
        else: y = self.xydata[self.activeboard * self.num_chan_per_board + self.selectedchannel][1]  # channel signal to take fft of
        n = len(y)  # length of the signal
        k = np.arange(n)
        uspersample = self.downsamplefactor / self.samplerate / 1000.
        if self.dointerleaved: uspersample = uspersample/2
        # t = np.arange(0,1,1.0/n) * (n*uspersample) # time vector in us
        frq = (k / uspersample)[list(range(int(n / 2)))] / n  # one side frequency range up to Nyquist
        Y = np.fft.fft(y)[list(range(int(n / 2)))] / n  # fft computing and normalization
        Y[0] = 0  # to suppress DC
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
        self.fftui.fftfreqplot_ydata = abs(Y)
        self.fftui.fftfreqplot_ydatamax = np.max(abs(Y))

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
        self.ui.boardBox.setValue(0)

    def init(self):
        self.tot()
        self.setupchannels()
        self.launch()
        self.doleds()
        self.rolling()
        self.selectchannel()
        self.timechanged()
        self.use_ext_trigs()
        self.dostartstop()
        return 1

    def doleds(self):
        if self.num_board==1:
            for board in range(self.num_board):
                # board==0
                r1 = 0x0f
                g1 = 0x00
                b1 = 0x00
                r2 = 0x00
                g2 = 0x00
                b2 = 0x00
                if self.dotwochannel:
                    r1 = 0x0f
                    g1 = 0x00
                    b1 = 0x00
                    r2 = 0x00
                    g2 = 0x0f
                    b2 = 0x00
                send_leds(usbs[board], r1, g1, b1, r2, g2, b2)
                send_leds(usbs[board], r1, g1, b1, r2, g2, b2)
        elif self.num_board==2:
            for board in range(self.num_board):
                # board==0
                r1 = 0x0f
                g1 = 0x00
                b1 = 0x00
                r2 = 0x00
                g2 = 0x00
                b2 = 0x00
                if board==1:
                    r1 = 0x00
                    g1 = 0x00
                    b1 = 0x0f
                    r2 = 0x00
                    g2 = 0x00
                    b2 = 0x00
                if self.dotwochannel:
                    # board==0
                    r1 = 0x0f
                    g1 = 0x00
                    b1 = 0x00
                    r2 = 0x00
                    g2 = 0x0f
                    b2 = 0x00
                    if board==1:
                        r1 = 0x00
                        g1 = 0x00
                        b1 = 0x0f
                        r2 = 0x0f
                        g2 = 0x00
                        b2 = 0x0f
                if self.dooversample:
                    # board==0
                    r1 = 0x00
                    g1 = 0x00
                    b1 = 0x00
                    r2 = 0x0f
                    g2 = 0x00
                    b2 = 0x00
                    if board == 1:
                        r1 = 0x00
                        g1 = 0x00
                        b1 = 0x00
                        r2 = 0x00
                        g2 = 0x00
                        b2 = 0x0f
                        if self.dointerleaved:
                            r1 = 0x00
                            g1 = 0x00
                            b1 = 0x00
                            r2 = 0x0f
                            g2 = 0x0f
                            b2 = 0x0f
                send_leds(usbs[board], r1, g1, b1, r2, g2, b2)
                send_leds(usbs[board], r1, g1, b1, r2, g2, b2)
        else:
            print("Don't know how to set lights for",self.num_board,"boards yet!")

    def setupchannels(self):
        if self.dotwochannel:
            self.xydata = np.empty([int(self.num_chan_per_board * self.num_board), 2, 2 * 10 * self.expect_samples], dtype=float)
        else:
            self.xydata = np.empty([int(self.num_chan_per_board * self.num_board), 2, 4 * 10 * self.expect_samples], dtype=float)
            self.xydatainterleaved = np.empty([int(self.num_chan_per_board * self.num_board), 2, 2 * 4 * 10 * self.expect_samples], dtype=float)

    def launch(self):
        self.nlines = self.num_chan_per_board * self.num_board
        chan=0
        for board in range(self.num_board):
            for boardchan in range( self.num_chan_per_board ):
                print("chan=",chan, " board=",board, "boardchan=",boardchan)
                c = (0, 0, 0)
                if chan == 0: c = QColor("red")
                if chan == 1: c = QColor("green")
                if chan == 2: c = QColor("blue")
                if chan == 3: c = QColor("magenta")
                if chan>3:
                    print("Not ready for more channels yet!")
                    sys.exit(3)
                pen = pg.mkPen(color=c)  # add linewidth=1.0, alpha=.9
                line = self.ui.plot.plot(pen=pen, name=self.chtext + str(chan))
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
        pen = pg.mkPen(color="k", width=1.0, style=QtCore.Qt.DashLine)
        line = self.ui.plot.plot([self.vline, self.vline], [-2.0, 2.0], pen=pen, name="trigger time vert")
        self.otherlines.append(line)

        self.hline = 0.0
        pen = pg.mkPen(color="k", width=1.0, style=QtCore.Qt.DashLine)
        line = self.ui.plot.plot([-2.0, 2.0], [self.hline, self.hline], pen=pen, name="trigger thresh horiz")
        self.otherlines.append(line)

        # other stuff
        # https://pyqtgraph.readthedocs.io/en/latest/api_reference/graphicsItems/plotitem.html
        self.ui.plot.setLabel('bottom', "Time (ns)")
        self.ui.plot.setLabel('left', "Voltage (divisions)")
        self.ui.plot.setRange(yRange=(self.min_y, self.max_y), padding=0.01)
        self.ui.plot.getAxis("left").setTickSpacing(1,.1)
        self.ui.plot.showGrid(x=True, y=True)
        for usb in usbs: self.telldownsample(usb, 0)

    def setup_connection(self, board):
        print("Setting up board",board)
        #version(usbs[board])
        self.adfreset(board)
        self.pllreset(board)
        setupboard(usbs[board], self.dopattern, self.dotwochannel, self.dooverrange)
        for c in range(self.num_chan_per_board): setchanacdc(usbs[board], c, 0, self.dooversample)
        return 1

    def closeEvent(self, event):
        print("Handling closeEvent", event)
        self.timer.stop()
        self.timer2.stop()
        if self.fftui != 0: self.fftui.close()
        for usb in usbs: cleanup(usb)

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
    if standalone:
        rv = app.exec_()
        sys.exit(rv)
    else:
        print("Done, but Qt window still active!")
