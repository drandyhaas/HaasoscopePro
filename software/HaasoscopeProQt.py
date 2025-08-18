from MainWindow import *

if __name__ == '__main__': # calls setup_connection for each board, then init
    print('Argument List:', str(sys.argv))
    for a in sys.argv:
        if a[0] == "-": print(a)
    print("Python version", sys.version)
    app = QtWidgets.QApplication.instance()
    standalone = app is None
    if standalone: app = QtWidgets.QApplication(sys.argv)
    font = app.font()
    font.setPixelSize(11)
    app.setFont(font)
    app.setWindowIcon(QIcon('icon.png'))
    try:
        usbs = connectdevices(100)  # max of 100 devices
        for b in range(len(usbs)):
            for i in range(3): version(usbs[b]) # read a few times to make sure communication works
            clkout_ena(usbs[b], 1 if len(usbs)>1 else 0)  # turn on lvdsout_clk for boards if needed
        time.sleep(.1)  # wait for clocks to lock
        usbs = orderusbs(usbs)
        tellfirstandlast(usbs)
        win = MainWindow(usbs)
    except ftd2xx.DeviceError:
        print("Device com failed!")
    if standalone:
        rv = app.exec_()
        sys.exit(rv)
