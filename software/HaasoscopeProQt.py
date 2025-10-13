# HaasoscopeProQt.py

import sys
import os
import time
import ftd2xx
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt

# Import the new main window and necessary hardware functions
from main_window import MainWindow
from utils import oldbytes
from usbs import connectdevices, orderusbs, tellfirstandlast, version
from board import clkout_ena
from utils import get_pwd

# --- Hardware Discovery and Initial Setup ---
print("Searching for Haasoscope Pro boards...")
max_devices = 100
try:
    usbs = connectdevices(max_devices) # This will now return an empty list if none are found
    if usbs:
        for b in range(len(usbs)):

            # Reading version multiple times seems to be a hardware quirk to ensure a stable read
            version(usbs[b])
            version(usbs[b])
            version(usbs[b], quiet=True)
            oldbytes(usbs[b])

            # Turn on lvdsout_clk for multi-board setups
            if len(usbs) > 1:
                clkout_ena(usbs[b], b, True, True)

            # Check for special beta device serial numbers
            usbs[b].beta = 0.0  # Assign default
            index = str(usbs[b].serial).find("_v1.")
            if index > -1:
                usbs[b].beta = float(str(usbs[b].serial)[index + 2:index + 6])
                print(f"Board {b} is a special beta device: v{usbs[b].beta}")

    time.sleep(0.1)  # Wait for clocks to lock after configuration
    usbs = orderusbs(usbs)
    if len(usbs) > 1:
        tellfirstandlast(usbs)

except (RuntimeError, IndexError) as e:
    print(f"An unexpected error occurred: {e}")
    sys.exit(-1)

# --- Main Application Execution ---
if __name__ == '__main__':
    #print('Argument List:', str(sys.argv))
    print("Python version", sys.version)

    # The most common fix for UI scaling and grid misalignment issues
    if sys.platform.startswith('win'):
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(True)
            print("Windows: Set high DPI awareness.")
        except Exception as e:
            print(f"Could not set DPI awareness on Windows: {e}")

    # noinspection PyTypeChecker
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv)
    font = app.font()
    font.setPixelSize(11)
    app.setFont(font)
    if sys.platform.startswith('win'): app.setWindowIcon(QIcon(get_pwd()+'\\icon.png'))
    else: app.setWindowIcon(QIcon(get_pwd()+'/icon.png'))

    win = None
    try:
        # MainWindow.__init__ now handles all setup. If it fails, it will
        # set the `setup_successful` flag to False.
        win = MainWindow(usbs)
        win.setWindowTitle('Haasoscope Pro Qt')

        if not win.setup_successful:
            print("ERROR: Initialization failed. Please check hardware and power.")
            # The window will still show, but the run button will be disabled.
        else:
            print("Initialization successful. Starting application.")

        rv = app.exec_()
        sys.exit(rv)

    except ftd2xx.DeviceError as e:
        print(f"FATAL: A hardware communication error occurred: {e}")
        print("Please ensure the device is connected and drivers are installed correctly.")
        sys.exit(-1)

    # except Exception as e:
    #     print(f"An unexpected error occurred: {e}")
    #     # Perform cleanup in case of any other crash
    #     if win:
    #         win.close()  # This will trigger the closeEvent for cleanup
    #     sys.exit(-1)
