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
    res = usb.recv(4)
    #print("got back", res[0])
    usb.send(bytes([11, 0, g1, r1, b1, g2, r2, b2]))  # stop sending
    res = usb.recv(4)
    #print("got back", res[0])
