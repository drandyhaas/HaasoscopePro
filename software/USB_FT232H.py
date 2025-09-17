def open_ft_usb_device(device_type, device_name, serial):
    b_device_name = bytes(device_name, encoding="ASCII")
    try:
        import ftd2xx
    except:
        return None, 'Failed to import ftd2xx'
    try:
        usb = ftd2xx.openEx(serial)
    except:
        return None, 'Faled to open device'
    if usb.description != b_device_name:
        usb.close()
        #print('Device did not match:', usb.description, b_device_name)
        return None, 'Other type of USB device: '+str(usb.description)
    else:
        usb.setBitMode(0xff, 0x40)
        #print(usb.getDeviceInfo())
        #print(usb.getComPortNumber())
        return usb, 'Successfully opened %s USB device: %s %s' % (device_type, device_name, serial)

class UsbFt232hSync245mode:

    def __init__(self, device_type, device_name, serial):
        usb, message = open_ft_usb_device(device_type, device_name, serial)
        print(message)
        self.good=False
        if usb is not None:
            self.good=True
            self.device_type = device_type
            self.device_name = device_name
            self.serial = serial
            self.beta = 1000.0
            self._usb = usb
            self._recv_timeout = 250
            self._send_timeout = 2000
            self.set_recv_timeout(self._recv_timeout)
            self.set_send_timeout(self._send_timeout)
            self.set_latencyt(1)  # ms
            self._chunk = 65536
            usb.setUSBParameters(self._chunk * 4, self._chunk * 4)

    def close(self):
        self._usb.close()
        self._usb = None

    def set_latencyt(self, latency):
        self._usb.setLatencyTimer(latency)

    def set_recv_timeout(self, timeout):
        self._recv_timeout = timeout
        self._usb.setTimeouts(self._recv_timeout, self._send_timeout)

    def set_send_timeout(self, timeout):
        self._send_timeout = timeout
        self._usb.setTimeouts(self._recv_timeout, self._send_timeout)

    def send(self, data):
        txlen = 0
        for si in range(0, len(data), self._chunk):
            ei = si + self._chunk
            ei = min(ei, len(data))
            chunk = data[si:ei]
            txlen_once = self._usb.write(chunk)
            txlen += txlen_once
            if txlen_once < len(chunk):
                break
        return txlen

    def recv(self, recv_len):
        data = b''
        for si in range(0, recv_len, self._chunk):
            ei = si + self._chunk
            ei = min(ei, recv_len)
            chunk_len = ei - si
            chunk = self._usb.read(chunk_len)
            data += chunk
            if len(chunk) < chunk_len:
                break
        return data
