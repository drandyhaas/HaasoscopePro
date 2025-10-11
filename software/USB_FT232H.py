"""
Provides a low-level wrapper around the ftd2xx library for communicating
with an FTDI FT232H chip in Synchronous 245 FIFO mode.
"""
try:
    import ftd2xx

    FTD2XX_IMPORTED = True
except ImportError:
    ftd2xx = None
    FTD2XX_IMPORTED = False


def open_ft_usb_device(device_name: str, serial: bytes) -> tuple:
    """
    Attempts to open an FTDI device by its serial number and checks its description.

    Args:
        device_name (str): The expected device description string.
        serial (bytes): The serial number of the device to open.

    Returns:
        A tuple containing the ftd2xx device handle (or None on failure) and a status message.
    """
    if not FTD2XX_IMPORTED:
        return None, 'Failed to import ftd2xx library. Please ensure it is installed.'

    try:
        usb = ftd2xx.openEx(serial)
    except ftd2xx.DeviceError as e:
        return None, f'Failed to open device {serial.decode()}: {e}'

    if usb.description != device_name.encode('ASCII'):
        usb.close()
        return None, f'Device {serial.decode()} is not a {device_name}: {usb.description.decode()}'

    usb.setBitMode(0xff, 0x40)  # Set for Sync FIFO mode
    return usb, f'Successfully opened {device_name}: {serial.decode()}'


class UsbFt232hSync245mode:
    """
    A class representing a connection to a HaasoscopePro board via an FT232H USB chip.
    """

    def __init__(self, device_name: str, serial: bytes):
        """
        Initializes the USB connection.

        Args:
            device_name (str): The expected device description (e.g., 'HaasoscopePro USB2').
            serial (bytes): The serial number of the device.
        """
        self.beta = None
        self._usb, message = open_ft_usb_device(device_name, serial)
        print(message)

        self.good = self._usb is not None
        if not self.good:
            return

        self.serial = serial
        self.device_name = device_name
        self._recv_timeout = 250  # ms
        self._send_timeout = 2000  # ms
        self._chunk = 65536  # 64kB chunks for sending/receiving

        self.set_recv_timeout(self._recv_timeout)
        self.set_send_timeout(self._send_timeout)
        self.set_latency_timer(1)  # Lower latency for better performance
        self._usb.setUSBParameters(self._chunk, self._chunk)

    def close(self):
        """Closes the USB device handle."""
        if self._usb:
            self._usb.close()
            self._usb = None

    def reopen(self):
        self.close()
        self._usb, message = open_ft_usb_device(self.device_name, self.serial)
        #print(message)

    def set_latency_timer(self, latency_ms: int):
        """Sets the USB latency timer."""
        self._usb.setLatencyTimer(latency_ms)

    def set_recv_timeout(self, timeout_ms: int):
        """Sets the receive timeout."""
        self._recv_timeout = timeout_ms
        self._usb.setTimeouts(self._recv_timeout, self._send_timeout)

    def set_send_timeout(self, timeout_ms: int):
        """Sets the send timeout."""
        self._send_timeout = timeout_ms
        self._usb.setTimeouts(self._recv_timeout, self._send_timeout)

    def send(self, data: bytes) -> int:
        """
        Sends data to the device, handling chunking for large transfers.

        Returns:
            int: The total number of bytes sent.
        """
        return self._usb.write(data)

    def recv(self, recv_len: int) -> bytes:
        """
        Receives data from the device, handling chunking for large transfers.

        Returns:
            bytes: The received data.
        """
        return self._usb.read(recv_len)
