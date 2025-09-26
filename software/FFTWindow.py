import math
import os.path
import numpy as np
import sys, time, warnings
from collections import deque
import pyqtgraph as pg
import PyQt5
from pyqtgraph.Qt import QtCore, QtWidgets, loadUiType
from PyQt5.QtGui import QPalette, QColor, QIcon, QPen
from PyQt5.QtWidgets import QApplication, QMessageBox, QWidget, QPushButton, QFrame, QColorDialog
from scipy.optimize import curve_fit
from scipy.signal import resample, butter, filtfilt
from scipy.interpolate import interp1d
import struct
from usbs import *
from board import *
from SCPIsocket import hspro_socket
from datetime import datetime
import threading
import matplotlib.cm as cm

# Define fft window class from template
FFTWindowTemplate, FFTTemplateBaseClass = loadUiType(get_pwd()+"/HaasoscopeProFFT.ui")
class FFTWindow(FFTTemplateBaseClass):
    def __init__(self):
        FFTTemplateBaseClass.__init__(self)
        self.ui = FFTWindowTemplate()
        self.ui.setupUi(self)
        self.ui.actionTake_screenshot.triggered.connect(self.take_screenshot)
        self.ui.actionLog_scale.triggered.connect(self.log_scale)
        self.ui.plot.setLabel('bottom', 'Frequency (MHz)')
        self.ui.plot.setLabel('left', 'Amplitude')
        self.ui.plot.showGrid(x=True, y=True, alpha=.8)
        self.ui.plot.setMenuEnabled(False) # disables the right-click menu
        self.ui.plot.setMouseEnabled(x=False, y=False) # disables pan and zoom
        self.ui.plot.hideButtons() # hides the little autoscale button in the lower left
        #self.ui.plot.setRange(xRange=(0.0, 1600.0))
        self.ui.plot.setBackground(QColor('black'))
        self.fftpen = pg.mkPen(color="w") # width=2 slower
        self.fftline = self.ui.plot.plot(pen=self.fftpen, name="fft_plot", skipFiniteCheck=True, connect="finite")
        self.dolog = False

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
        if self.dolog: self.ui.plot.setLabel('left', 'log10 Amplitude')
        else: self.ui.plot.setLabel('left', 'Amplitude')
