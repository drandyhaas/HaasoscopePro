from PyQt5.QtGui import QIcon
from ftd2xx import DeviceError
from MainWindow import *

def main():
    """
    Initializes the Qt application, connects to the Haasoscope boards,
    and launches the main window.
    """

    # Use an existing application instance or create a new one.
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    # Set a consistent font size and application icon.
    font = app.font()
    font.setPixelSize(11)
    app.setFont(font)
    app.setWindowIcon(QIcon('icon.png'))

    # --- Hardware Connection and Initialization ---
    try:
        # Scan for and connect to a maximum of 100 devices.
        usbs = connectdevices(0)
        if not usbs: print("No devices found!")

        # Initialize and verify communication with each board.
        for board_index, usb_handle in enumerate(usbs):
            # Read version multiple times to ensure a stable connection.
            for _ in range(3): version(usb_handle)
            # Enable the clock output if there are multiple boards.
            is_multiboard = len(usbs) > 1
            clkout_ena(usb_handle, 1 if is_multiboard else 0)
        time.sleep(0.1)  # Wait for board clocks to lock.

        # Order boards and designate the first and last in the chain.
        usbs = orderusbs(usbs)
        tellfirstandlast(usbs)

        # Launch the main application window with the connected devices.
        MainWindow(usbs)
        sys.exit(app.exec_())

    except DeviceError as e:
        print(f"Device communication failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    print("--- Haasoscope Pro ---")
    print(f"Python version: {sys.version}")
    print(f"Argument List: {sys.argv}")
    # A simple loop to print any provided command-line flags.
    for arg in sys.argv:
        if arg.startswith("-"):
            print(f"Detected flag: {arg}")

    main()
