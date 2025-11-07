# HaasoscopeProQt.py

import sys
import os
import time
import argparse
import ftd2xx
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt

# Import the new main window and necessary hardware functions
from main_window import MainWindow
from utils import oldbytes
from usbs import connectdevices, orderusbs, tellfirstandlast, version, connect_socket_devices
from board import clkout_ena
from utils import get_pwd

# --- Main Application Execution ---
if __name__ == '__main__':
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='HaasoscopePro Oscilloscope Software')
    parser.add_argument('--socket', action='append', metavar='ADDRESS',
                        help='Connect to dummy server via TCP socket (format: host:port). '
                             'Can be specified multiple times for multi-board simulation. '
                             'Example: --socket localhost:9999 --socket localhost:10000')
    parser.add_argument('--max-devices', type=int, default=100, metavar='N',
                        help='Maximum number of devices to connect (default: 100)')
    parser.add_argument('--testing', action='store_true',
                        help='Enable testing mode (disables dynamic status bar updates for stable screenshots)')
    args = parser.parse_args()

    print("Python version", sys.version)

    try:
        # --- Hardware Discovery and Initial Setup ---
        print("Searching for Haasoscope Pro boards...")
        usbs = connectdevices(100)

        # Try to use dummy server if requested via --socket or if no hardware found
        socket_addresses = args.socket if args.socket else None

        if socket_addresses:
            # User specified --socket argument(s), connect to those
            print(f"Connecting to socket device(s): {socket_addresses}")
            socket_usbs = connect_socket_devices(socket_addresses)
            usbs.extend(socket_usbs)
        elif len(usbs) < 1:
            # No hardware found and no --socket specified, try default dummy server
            print("No hardware found. Looking for dummy scope at localhost:9998...")
            socket_usbs = connect_socket_devices(["localhost:9998"])
            usbs.extend(socket_usbs)

        if usbs:
            for b in range(len(usbs)):

                # Reading version multiple times seems to be a hardware quirk to ensure a stable read
                version(usbs[b])
                version(usbs[b])
                version(usbs[b], quiet=True)
                oldbytes(usbs[b])

                # Turn on lvdsout_clk for multi-board setups
                if len(usbs)>1: # for all boards, including the "last" one, since we don't know the ordering yet
                    clkout_ena(usbs[b], b, True, False)

                # Check for special beta device serial numbers
                usbs[b].beta = 0.0  # Assign default
                index = str(usbs[b].serial).find("_v1.")
                if index > -1:
                    usbs[b].beta = float(str(usbs[b].serial)[index + 2:index + 6])
                    print(f"Board {b} is a special beta device: v{usbs[b].beta}")

        time.sleep(0.1)  # Wait for clocks to lock after configuration
        usbs = orderusbs(usbs)

        # just use the first max_devices number of devices
        max_devices = args.max_devices
        if max_devices<len(usbs): usbs = usbs[:max_devices]

        if len(usbs) > 1:
            tellfirstandlast(usbs)
            clkout_ena(usbs[len(usbs)-1], len(usbs)-1, False, False) # now can turn off clkout on the truly last board, now that we know the ordering

    except (RuntimeError, IndexError) as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(-1)

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
        win = MainWindow(usbs, testing_mode=args.testing)
        win.setWindowTitle('Haasoscope Pro Qt')
        if args.testing:
            print("Testing mode enabled: Status bar dynamic updates disabled")

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
