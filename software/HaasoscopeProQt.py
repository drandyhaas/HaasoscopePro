from MainWindow import *

usbs = connectdevices(100) # max of 100 devices
#if len(usbs)==0: sys.exit(0)
for b in range(len(usbs)):
    if len(usbs) > 1: clkout_ena(usbs[b], 1) # turn on lvdsout_clk for boards
    version(usbs[b])
    version(usbs[b])
    version(usbs[b])
    index = str(usbs[b].serial).find("_v1.")
    if index > -1:
        usbs[b].beta = float(str(usbs[b].serial)[index + 2:index + 6])
        print("Special beta device:", usbs[b].beta)
time.sleep(.1) # wait for clocks to lock
usbs = orderusbs(usbs)
tellfirstandlast(usbs)

if __name__ == '__main__': # calls setup_connection for each board, then init
    print('Argument List:', str(sys.argv))
    for a in sys.argv:
        if a[0] == "-":
            print(a)
    print("Python version", sys.version)
    app = QtWidgets.QApplication.instance()
    standalone = app is None
    if standalone:
        # The most common fix for grid misalignment
        if sys.platform.startswith('win'):
            import ctypes
            print("On Windows, SetProcessDpiAwareness(True)")
            ctypes.windll.shcore.SetProcessDpiAwareness(True)
        # For all platforms, you can also try setting environment variables
        QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
        os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
        os.environ["QT_SCALE_FACTOR"] = "1"
        app = QtWidgets.QApplication(sys.argv)
        font = app.font()
        font.setPixelSize(11)
        app.setFont(font)
        app.setWindowIcon(QIcon('icon.png'))
        win = MainWindow(usbs)
        win.setWindowTitle('Haasoscope Pro Qt')
        print("Haasoscope Pro Qt, version "+f"{win.softwareversion:.2f}")
        try:
            goodsetup=True
            for usbi in range(len(usbs)):
                if not win.setup_connection(usbi):
                    print("Failed to setup!")
                    for usbj in usbs: cleanup(usbj)
                    if not win.paused: win.dostartstop()
                    win.ui.runButton.setEnabled(False)
                    goodsetup=False
            if not goodsetup or not win.init():
                print("Failed initialization!")
                for usbi in usbs: cleanup(usbi)
                if not win.paused: win.dostartstop()
                win.ui.runButton.setEnabled(False)
        except ftd2xx.DeviceError:
            print("Device com failed!")
            if not win.paused: win.dostartstop()
            win.ui.runButton.setEnabled(False)
            win.close_socket()
        rv = app.exec_()
        sys.exit(rv)
    else:
        print("Done, but Qt window still active!")
