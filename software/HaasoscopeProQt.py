import time
from usbs import *
from PyQt5.QtGui import QIcon
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


if __name__ == '__main__':
    print('Argument List:', str(sys.argv))
    for a in sys.argv:
        if a[0] == "-": print(a)
    print("Python version", sys.version)

    app = QtWidgets.QApplication(sys.argv)
    font = app.font()
    font.setPixelSize(11)
    app.setFont(font)
    app.setWindowIcon(QIcon('icon.png'))

    connected_usbs = usbs # get_usbs()
    if not connected_usbs:
        QMessageBox.critical(None, "Error", "No Haasoscope Pro boards found!")
        # sys.exit(1) # Comment out to allow running without stubs

    window = MainWindow(connected_usbs)
    window.show()
    sys.exit(app.exec_())

