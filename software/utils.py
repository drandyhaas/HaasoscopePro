def reverse_bits(byte):
    reversed_byte = 0
    for i in range(8):
        if (byte >> i) & 1:
            reversed_byte |= 1 << (7 - i)
    return reversed_byte

def binprint(x):
    return bin(x)[2:].zfill(8)

# get bit n from byte i
def getbit(i, n):
    return (i >> n) & 1

def bytestoint(thebytes):
    return thebytes[0] + pow(2, 8) * thebytes[1] + pow(2, 16) * thebytes[2] + pow(2, 24) * thebytes[3]

def oldbytes(usb):
    while True:
        olddata = usb.recv(1000000)
        print("Got", len(olddata), "old bytes")
        if len(olddata) == 0: break
        print("Old byte0:", olddata[0])

def inttobytes(theint):  # convert length number to a 4-byte byte array (with type of 'bytes')
    return [theint & 0xff, (theint >> 8) & 0xff, (theint >> 16) & 0xff, (theint >> 24) & 0xff]

def send_leds(usb, r1,g1,b1, r2,g2,b2):
    usb.send(bytes([11, 1, g1, r1, b1, g2, r2, b2]))  # send
    usb.recv(4)
    usb.send(bytes([11, 0, g1, r1, b1, g2, r2, b2]))  # stop sending
    usb.recv(4)

def flash_erase(usb):
    usb.send(bytes([17, 0,0,0, 99, 99, 99, 99]))  # erase
    res = usb.recv(4)
    time.sleep(1)
    print("erase got", res[0])

def flash_write(usb, byte3, byte2, byte1, valuetowrite):
    usb.send(bytes([16, byte3, byte2, byte1, reverse_bits(valuetowrite), 99, 99, 99]))  # write to address
    res = usb.recv(4)
    print("write got", res[0])

def flash_read_print(usb, byte3, byte2, byte1):
    usb.send(bytes([15, byte3, byte2, byte1, 99, 99, 99, 99]))  # read from address
    res = usb.recv(4)
    print(byte3 * 256 * 256 + byte2 * 256 + byte1, "", reverse_bits(res[0]) )

def flash_readall_to_file(usb):
    file = open("output.txt", "w")
    for k in range(20):
        for j in range(256):
            for i in range(256):
                usb.send(bytes([15, k, j, i, 99, 99, 99, 99])) # read from address
        res = usb.recv(256*256*4)
        if len(res) == 256*256*4:
            for j in range(256):
                for i in range(256):
                    if (k*256*256 + j*256 + i)<1191788:
                        print(k*256*256 + j*256 + i, "", reverse_bits((res[256*4*j+4*i])), file=file)
        else: print("timeout?")
    file.close()
