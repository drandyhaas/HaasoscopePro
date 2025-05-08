import socket
import struct

HOST = '127.0.0.1'  # Standard loopback interface address (localhost)
PORT = 32001        # Port to listen on (non-privileged ports are > 1023)

numchan = 1

def data_seqnum():
    return bytearray([1,0,0,0])
def data_numchan():
    return bytearray([numchan,0])
def data_fspersample():
    return bytearray([0,100,0,0, 0,0,0,0])
def data_triggerpos():
    return bytearray([27,0,0,0, 0,0,0,0])
def data_wfms_per_s():
    return struct.pack('d', 3.14159)

def data_channel(chan):
    res = bytearray([chan]) # channel index
    memdepth = 40*100
    res += memdepth.to_bytes(8,"little")
    res += struct.pack('f', 0.01) # scale
    res += struct.pack('f', 0.5) # offset
    res += struct.pack('f', 1.0) # trigphase
    res += bytearray([0]) # clipping?
    val=-100
    for thesamp in range(memdepth):
        val+=1
        if val>100: val=-100
        res+=val.to_bytes(1, byteorder='little', signed=True)
    return res

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind((HOST, PORT))
    s.listen()
    print("listening on",HOST,PORT)
    conn, addr = s.accept()
    with conn:
        print(f"Connected by {addr}")
        while True:
            data = conn.recv(1024)
            if not data: break
            print(data)
            if data==b'*IDN?\n':
                conn.sendall(b"DrAndyHaas Electronics,HaasoscopePro,v1.0,v26,\n")
            if data==b'RATES?\n':
                conn.sendall(b"1000000,2000000,\n")
            if data==b'DEPTHS?\n':
                conn.sendall(b"400,800,2000,8000,40000,\n")
            if data == b'START\n':
                print("Run")
            if data == b'STOP\n':
                print("Stop")
            if data == b'SINGLE\n':
                print("Single")
            if data == b'FORCE\n':
                print("Force")
            if data == b'K':
                print("Get event")
                conn.sendall(data_seqnum())
                conn.sendall(data_numchan())
                conn.sendall(data_fspersample())
                conn.sendall(data_triggerpos())
                conn.sendall(data_wfms_per_s())
                for c in range(numchan): conn.sendall(data_channel(c))
