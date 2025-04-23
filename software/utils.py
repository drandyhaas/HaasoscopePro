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

def find_longest_zero_stretch(arr, wrap):
    if wrap: arr = arr+arr # to handle wraparounds
    max_length = 0
    current_length = 0
    start_index = -1
    current_start = -1
    for i, num in enumerate(arr):
        if num == 0:
            if current_length == 0:
                current_start = i
            current_length += 1
            if current_length > max_length:
                max_length = current_length
                start_index = current_start
        else:
            current_length = 0
    return start_index, max_length

def bytestoint(thebytes):
    return thebytes[0] + pow(2, 8) * thebytes[1] + pow(2, 16) * thebytes[2] + pow(2, 24) * thebytes[3]

def oldbytes(usb):
    while True:
        olddata = usb.recv(100000)
        if len(olddata)>0:
            print("Got", len(olddata), "old bytes")
            print("Old byte0:", olddata[0])
        else: break

def inttobytes(theint):  # convert length number to a 4-byte byte array (with type of 'bytes')
    return [theint & 0xff, (theint >> 8) & 0xff, (theint >> 16) & 0xff, (theint >> 24) & 0xff]

def send_leds(usb, r1,g1,b1, r2,g2,b2): # ch0, ch1
    r1 = reverse_bits(r1)
    g1 = reverse_bits(g1)
    b1 = reverse_bits(b1)
    r2 = reverse_bits(r2)
    g2 = reverse_bits(g2)
    b2 = reverse_bits(b2)
    usb.send(bytes([11, 1, g1, r1, b1, g2, r2, b2]))  # send
    usb.recv(4)
    usb.send(bytes([11, 0, g1, r1, b1, g2, r2, b2]))  # stop sending
    usb.recv(4)

def flash_erase(usb):
    usb.send(bytes([17, 0, 0, 0, 99, 99, 99, 99])) # erase
    res = usb.recv(4)
    print("bulk erase got", res[0])

def flash_write(usb, byte3, byte2, byte1, valuetowrite, dorecieve=True):
    usb.send(bytes([16, byte3, byte2, byte1, reverse_bits(valuetowrite), 99, 99, 99])) # write to address
    if dorecieve:
        res = usb.recv(4)
        print("write got", res[0])

def flash_writeall_from_file(usb, filename, dowrite=True):
    with open(filename, 'rb') as f:
        allbytes = f.read()
        print("opened",filename,"with length",len(allbytes))
        if dowrite:
            for b in range(len(allbytes)):
                flash_write(usb,b//(256*256),(b//256)%256,b%256,allbytes[b],False)
                if b%1024==1023:
                    res = usb.recv(4*1024)
                    if b%(1024*50)==1023: print("wrote byte",b+1,"/ 1191788")
                    if len(res)!=4*1024:
                        print("got only",len(res),"bytes read back?")
        f.close()
    if dowrite:
        res = usb.recv(4 * (len(allbytes)%1024))
        print("wrote byte", b+1, "(leftover",len(allbytes)%1024,"bytes)")
        if len(res)!=(4*(len(allbytes)%1024)):
            print("got only",len(res),"bytes read back?")
        oldbytes(usb) # make sure there's none left over to read
    return allbytes

def flash_read(usb, byte3, byte2, byte1, dorecieve=True):
    usb.send(bytes([15, byte3, byte2, byte1, 99, 99, 99, 99]))  # read from address
    if dorecieve:
        res = usb.recv(4)
        print(byte3 * 256 * 256 + byte2 * 256 + byte1, "", reverse_bits(res[0]) )

def flash_readall(usb):
    readbytes = bytearray([])
    for k in range(20):
        print("reading block", k, "of 20")
        for j in range(256):
            for i in range(256):
                flash_read(usb, k, j, i,False) # read from address, but don't recieve the data yet
        res = usb.recv(256*256*4)
        if len(res) == 256*256*4:
            for j in range(256):
                for i in range(256):
                    if (k*256*256 + j*256 + i)<1191788:
                        outbyte = reverse_bits((res[256 * 4 * j + 4 * i]))
                        readbytes.append(outbyte)
        else: print("timeout?")
    return readbytes
