import time
from MainWindow import *

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

if __name__ == '__main__': # calls setup_connection for each board, then init
    print('Argument List:', str(sys.argv))
    for a in sys.argv:
        if a[0] == "-": print(a)
    print("Python version", sys.version)
    app = QtWidgets.QApplication.instance()
    standalone = app is None
    if standalone: app = QtWidgets.QApplication(sys.argv)
    try:
        font = app.font()
        font.setPixelSize(11)
        app.setFont(font)
        app.setWindowIcon(QIcon('icon.png'))
        win = MainWindow(usbs)
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
