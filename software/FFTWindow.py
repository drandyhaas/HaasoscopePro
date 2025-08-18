import time
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets, loadUiType
from PyQt5.QtGui import QPalette, QColor, QIcon
from PyQt5.QtWidgets import QApplication, QMessageBox, QWidget, QPushButton

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
        self.ui.plot.setBackground(QColor('black'))
        c = (10, 10, 10)
        self.fftpen = pg.mkPen(color=c) # width=2 slower
        self.fftline = self.ui.plot.plot(pen=self.fftpen, name="fft_plot")
        self.fftlastTime = time.time() - 10
        self.fftyrange = 1
