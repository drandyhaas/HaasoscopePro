#-*- coding:utf-8 -*-
# Python3


import sys, time, ctypes

import ftd3xx.defines


def open_ft_usb_device(device_type, device_name):
    '''
        open_ft_usb_device(str device_type, str device_name) -> USB-device object
        function:
            open an FTDI USB device
        parameters :
            device_type : 
                'FTX232H' : FT232H or FT2232H
                'FT60X'   : FT600 or FT601
            device_name : the USB device's product name to be opened
                for 'FTX232H', the chip's default device_name = 'USB <-> Serial Converter'    unless the user has modified it.
                for 'FT60X'  , the chip's default device_name = 'FTDI SuperSpeed-FIFO Bridge' unless the user has modified it.
        return:
            a USB-device object
    '''
    
    b_device_name = bytes(device_name, encoding="ASCII")
    
    if device_type == 'FT60X' :      # search the FT60X device ################################################################################################
        
        try:
            import ftd3xx                                                                                               # import #
        except:
            return None, 'Failed to import ftd3xx'
        
        for device_id in range(16):
            
            if sys.platform == 'win32':
                usb = ftd3xx.create(device_id, ftd3xx._ftd3xx_win32.FT_OPEN_BY_INDEX)
            elif sys.platform == 'linux2':
                usb = ftd3xx.create(device_id, ftd3xx._ftd3xx_linux.FT_OPEN_BY_INDEX)
            
            if usb is None:
                continue
            
            if sys.platform == 'win32' and usb.getDriverVersion() < 0x01020006:
                usb.close()
                return None, 'Old D3XX driver version. Please update driver!'
            
            if usb.getDeviceInfo()['Description'] != b_device_name:
                usb.close()
                continue
            
            numChannel = [4, 2, 1, 0, 0][usb.getChipConfiguration().ChannelConfig]
            if numChannel != 1:
                usb.close()
                return None, 'This %s is not in sync-245-fifo mode because number of channel is not 1 ! (numChannel=%d)' % (device_type, numChannel)
            
            return usb, 'Successfully opened %s USB device: %s' % (device_type, device_name)
        
    else:                           # search the FTX232H device ##############################################################################################
        
        try:
            import ftd2xx                                                                                               # import #
        except:
            return None, 'Failed to import ftd2xx'
        
        for i in range(16):
            
            try:
                usb = ftd2xx.open(i)
            except:
                continue
            
            if usb.description != b_device_name:
                usb.close()
                continue
            
            usb.setBitMode(0xff, 0x40)
            
            return usb, 'Successfully opened %s USB device: %s' % (device_type, device_name)
    
    return None, 'Could not open %s USB device: %s' % (device_type, device_name)





class USB_FTX232H_FT60X_sync245mode():
    
    def __init__(self, device_to_open_list = (('FTX232H', 'USB <-> Serial Converter'   ),
                                              ('FT60X'  , 'FTDI SuperSpeed-FIFO Bridge')) ):
        '''
            __init__(str device_type, str device_name) -> USB_FTX232H_FT60X_sync245mode object
            function:
                open FTDI USB device and return a USB_FTX232H_FT60X_sync245mode object
        '''
        
        for device_type, device_name in device_to_open_list:

            usb, message = open_ft_usb_device(device_type, device_name)
            print(message)

            if not usb is None:
                
                self.device_type = device_type
                self.device_name = device_name
                desc = usb.getDeviceDescriptor()
                serial_num = desc.iSerialNumber
                self.serial = serial_num
                self._usb = usb

                if device_type == 'FT60X' :
                    if usb.getDeviceDescriptor().bcdUSB < 0x300:
                        print('Warning: Device is NOT connected using USB3.0 cable or port!')
                    self._chunk = 65536 * 64 * 4
                else:
                    self._chunk = 65536
                    usb.setUSBParameters(self._chunk*4, self._chunk*4)

                self._recv_timeout = 2000
                self._send_timeout = 2000
                # self.show_device()
                self.set_recv_timeout(self._recv_timeout)
                self.set_send_timeout(self._send_timeout)

                break
        
        else:
            raise Exception('Could not open USB device')
        
    
    
    
    def close(self):
        '''
            close()
            function:
                close the FTDI USB device
        '''
        
        self._usb.close()
        self._usb = None
    

    def show_device(self):
        dev = self._usb
        #print(f"Device opened. Description: {dev.getDeviceDescriptor().Description.decode()}")

        # 2. Get Configuration Descriptor to find number of interfaces
        # (FT601 245 FIFO mode usually has 1 interface, but we check to be safe)
        conf_desc = dev.getConfigurationDescriptor()
        print(f"Number of Interfaces: {conf_desc.bNumInterfaces}")

        # 3. Iterate through Interfaces and Pipes
        for i in range(conf_desc.bNumInterfaces):
            # getInterfaceDescriptor returns a tuple/struct with bNumEndpoints
            if_desc = dev.getInterfaceDescriptor(i)
            num_endpoints = if_desc.bNumEndpoints

            print(f"\nInterface {i} has {num_endpoints} endpoints (pipes):")

            for p in range(num_endpoints):
                # getPipeInformation(InterfaceIndex, PipeIndex)
                pipe_info = dev.getPipeInformation(i, p)

                # pipe_info is an FT_PIPE_INFORMATION structure
                pipe_id = pipe_info.PipeId
                pipe_type = pipe_info.PipeType

                # Decode Pipe Type (2 = Bulk, 3 = Interrupt)
                type_str = "Unknown"
                if pipe_type == ftd3xx.defines.FT_PIPE_TYPE_BULK:
                    type_str = "BULK"
                elif pipe_type == ftd3xx.defines.FT_PIPE_TYPE_INTERRUPT:
                    type_str = "INTERRUPT"

                # Determine Direction based on ID (0x80 bit)
                direction = "IN (Read)" if (pipe_id & 0x80) else "OUT (Write)"

                print(f"  - Pipe Index {p}: ID {hex(pipe_id)} [{direction}] Type: {type_str}")
    
    
    def set_recv_timeout(self, timeout):
        '''
            set_recv_timeout(int timeout)
            function:
                set recv timeout
            parameter:
                int timeout : unit: ms
        '''
        
        self._recv_timeout = timeout
        if self.device_type == 'FT60X' :
            status = self._usb.setPipeTimeout(0x82, self._recv_timeout)
            if status is not None and status != ftd3xx.defines.FT_OK:
                print(f"Error setting recv timeout: {status}")
            else:
                #print(f"Timeout recv set successfully (Wrapper returned {status})")

                test_timeout = False
                if test_timeout:
                    print(f"Attempting read (should wait {self._recv_timeout} ms)...")
                    start_time = time.time()

                    # 2. Read (Requesting data when FIFO is likely empty)
                    # This should NOT hang forever. It should return 0 bytes after ~1000ms.
                    #buffer = ctypes.create_string_buffer(1024)
                    rx_data = self.recv(1024) #self._usb.readPipe(0x82, buffer, 1024)

                    end_time = time.time()
                    elapsed = end_time - start_time

                    print(f"Read returned {rx_data}")
                    print(f"Time elapsed: {elapsed:.4f} seconds")

                    if self._recv_timeout-10 < elapsed*1000 < self._recv_timeout+10:
                        print("SUCCESS: Timeout is working correctly.")
                    elif elapsed < 0.1:
                        print("WARNING: Returned immediately (Timeout might be 0/Infinity or data was present).")
                    else:
                        print(f"WARNING: Did not respect the {self._recv_timeout} ms timeout.")
        else:
            self._usb.setTimeouts(self._recv_timeout, self._send_timeout)
    
    
    
    
    def set_send_timeout(self, timeout):
        '''
            set_send_timeout(int timeout)
            function:
                set send timeout
            parameter:
                int timeout : unit: ms
        '''
        
        self._send_timeout = timeout
        if self.device_type == 'FT60X' :
            status = self._usb.setPipeTimeout(0x02, self._send_timeout)
            if status is not None and status != ftd3xx.defines.FT_OK:
                print(f"Error setting send timeout: {status}")
            #else:
            #    print(f"Timeout send set successfully (Wrapper returned {status})")
        else:
            self._usb.setTimeouts(self._recv_timeout, self._send_timeout)
    
    
    
    
    def send(self, data):
        '''
            send(bytes data) -> int actual_send_len
            function:
                send data
            parameter:
                bytes data : data to send
            return:
                int actual_send_len : actual sent byte count
                                      if the device cannot accept so many data until timeout, actual_send_len < len(data)
        '''
        
        txlen = 0
        
        for si in range(0, len(data), self._chunk):
            ei = si + self._chunk
            ei = min(ei, len(data))
            
            chunk = data[si:ei]
            
            if self.device_type == 'FT60X' :
                txlen_once = self._usb.writePipe(0x02, chunk, len(chunk))
            else:
                txlen_once = self._usb.write(chunk)
            
            txlen += txlen_once
            
            if txlen_once < len(chunk):
                break
            
        return txlen
    
    
    
    
    def recv(self, recv_len):
        '''
            recv(int recv_len) -> bytes data
            function:
                receive data
            parameter:
                int recv_len : data length to be received
            return:
                bytes data : received data bytes
                             if the device cannot send so many data until timeout, len(data) < recv_len
        '''
        
        data = b''
        
        if self.device_type == 'FT60X' :
            chunk = bytes(self._chunk)
            
            zero_count = 0
            si = 0
            
            while si < recv_len :
                ei = si + self._chunk
                ei = min(ei, recv_len)

                #print(f"reading {ei-si} bytes")
                rxlen_once = self._usb.readPipe(0x82, chunk, ei-si)      # try to read (ei-si) bytes
                
                si += rxlen_once
                #print(rxlen_once)
                
                if rxlen_once > 0 :
                    zero_count = 0
                    data += chunk[:rxlen_once]
                else :                                                   # no byte received
                    zero_count += 1
                    #print("zero",zero_count)
                    if zero_count >= 1 :
                        # clean up the mess and return what we had so far
                        self._usb.abortPipe(0x82)
                        self._usb.flushPipe(0x82)
                        break
        
        else:
            for si in range(0, recv_len, self._chunk):
                ei = si + self._chunk
                ei = min(ei, recv_len)
                
                chunk_len = ei - si
                
                chunk = self._usb.read(chunk_len)
                
                data += chunk
                
                if len(chunk) < chunk_len:
                    break
        
        return data
        






if __name__ == '__main__':
    
    usb = USB_FTX232H_FT60X_sync245mode(device_to_open_list =
        (('FTX232H', 'USB <-> Serial Converter'   ),           # firstly try to open FTX232H (FT232H or FT2232H) device named 'USB <-> Serial Converter'. Note that 'USB <-> Serial Converter' is the default name of FT232H or FT2232H chip unless the user has modified it. If the chip's name has been modified, you can use FT_Prog software to look up it.
         ('FT60X'  , 'FTDI SuperSpeed-FIFO Bridge'))           # secondly try to open FT60X (FT600 or FT601) device named 'FTDI SuperSpeed-FIFO Bridge'. Note that 'FTDI SuperSpeed-FIFO Bridge' is the default name of FT600 or FT601 chip unless the user has modified it.
    )
    
    print('device opened: device_type=%s, device_name=%s' % (usb.device_type, usb.device_name) )

    usb.close()


