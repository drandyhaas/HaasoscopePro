import socket
import struct
import random
import math
import time


def split_bytearray(data, delimiter):
    split_list = []
    start = 0
    while True:
        try:
            index = data.index(delimiter, start)
            split_list.append(data[start:index])
            start = index + len(delimiter)
        except ValueError:
            split_list.append(data[start:])
            break
    return split_list


class hspro_socket:
    hspro = None

    #HOST = '127.0.0.1'  # Standard loopback interface address (localhost)
    HOST = '0.0.0.0'    # Listen on all interfaces
    PORT = 32001        # Port to listen on (non-privileged ports are > 1023)

    eventnum = 1
    numchan = 1
    triggerpos = 0
    wfms_per_s = 100.0
    memdepth = 40 * 100 # for depth = 100
    maxval = 5.0
    trigphase = 0.0
    offset = 0.0
    clipping = 0

    def data_seqnum(self):
        return self.eventnum.to_bytes(4,"little")
    def data_numchan(self):
        if self.hspro.dotwochannel: self.numchan = self.hspro.num_board * 2
        else: self.numchan = self.hspro.num_board
        return self.numchan.to_bytes(2,"little")
    def data_fspersample(self):
        fspersample = int(312500 * self.hspro.downsamplefactor)
        return fspersample.to_bytes(8,"little")
    def data_triggerpos(self):
        return self.triggerpos.to_bytes(8,"little")
    def data_wfms_per_s(self):
        return struct.pack('d', self.wfms_per_s)

    issending = False
    def data_channel(self,chan):
        self.issending = True
        res = bytearray([chan]) # channel index
        hsprochan = chan
        if not self.hspro.dotwochannel: hsprochan*=2 # we use just every other channel in single-channel mode
        memdepth = self.hspro.xydata[hsprochan][1].size
        if memdepth < self.memdepth: self.memdepth = memdepth
        res += self.memdepth.to_bytes(8,"little")
        scale = self.maxval/pow(2,15)
        res += struct.pack('f', scale) # scale
        res += struct.pack('f', self.offset) # offset
        res += struct.pack('f', self.trigphase) # trigphase
        res += bytearray([self.clipping]) # clipping?

        #these are the samples, 16-bit signed
        for thesamp in range(self.memdepth):
            val = self.hspro.xydata[hsprochan][1][thesamp] / scale
            if math.isinf(val) or math.isnan(val): scaledval=0
            else: scaledval = int(val)
            if scaledval<-32767: scaledval=-32767
            if scaledval>32767: scaledval=32767
            res+=scaledval.to_bytes(2, byteorder='little', signed=True)
        self.memdepth = memdepth # update at the end in case it's changed
        self.issending = False
        return res

    runthethread = True
    opened = False
    connected = False
    def open_socket(self,arg1):
        print('started socket with arg1',arg1)
        while self.runthethread:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as self.s:
                self.s.bind((self.HOST, self.PORT))
                self.s.listen()
                self.s.settimeout(1)
                print("socket listening on",self.HOST,self.PORT)
                self.opened = True
                self.connected = False
                while self.runthethread and self.opened:
                    try:
                        conn, addr = self.s.accept()
                        with conn:
                            print(f"Connected by {addr}")
                            while self.runthethread and self.opened:
                                self.connected = True
                                data = conn.recv(1024)
                                if not data:
                                    self.s.close()
                                    self.opened = False
                                #print("Got data:",data)
                                commands = split_bytearray(data, b'\n')
                                #print(commands)
                                for com in commands:
                                    if com == b'': continue # empty from end of line
                                    elif com == b'K':
                                        #print("Got command: Get event")
                                        conn.sendall(self.data_seqnum())
                                        conn.sendall(self.data_numchan())
                                        conn.sendall(self.data_fspersample())
                                        conn.sendall(self.data_triggerpos())
                                        conn.sendall(self.data_wfms_per_s())
                                        for c in range(self.numchan): conn.sendall(self.data_channel(c))
                                    else:
                                        if com==b'*IDN?':
                                            print("Got command: IDN")
                                            conn.sendall(b"DrAndyHaas Electronics,HaasoscopePro,v1.0,v26,\n")
                                        elif com==b'RATES?':
                                            print("Got command: Rates")
                                            conn.sendall(b"1000000,2000000,\n")
                                        elif com==b'DEPTHS?':
                                            print("Got command: Depths")
                                            conn.sendall(b"400,800,2000,8000,40000,\n")
                                        elif com == b'START':
                                            print("Got command: Start")
                                            #print(self.hspro.paused)
                                            #if self.hspro.paused: self.hspro.dostartstop()
                                        elif com == b'STOP':
                                            print("Got command: Stop")
                                            #print(self.hspro.paused)
                                            #if not self.hspro.paused: self.hspro.dostartstop()
                                        elif com == b'SINGLE':
                                            print("Got command: Single")
                                            #self.hspro.getone = True
                                            #if self.hspro.paused: self.hspro.dostartstop()
                                        elif com == b'FORCE':
                                            print("Got command: Force")
                                        else:
                                            print("Got command:", com)
                    except socket.timeout:
                        pass
