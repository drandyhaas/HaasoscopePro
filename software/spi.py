
def spicommand(usb, name, first, second, third, read, fourth=100, show_bin=False, cs=0, nbyte=3, quiet=True):
    # first byte to send, start of address
    # second byte to send, rest of address
    # third byte to send, value to write, ignored during read
    # cs is which chip to select, adc 0 by default
    # nbyte is 2 or 3, second byte is ignored in case of 2 bytes
    if read: first = first + 0x80  # set the highest bit for read, i.e. add 0x80
    usb.send(bytes([3, cs, first, second, third, fourth, 100, nbyte]))  # get SPI result from command
    spires = usb.recv(4)
    if read:
        if not quiet:
            if show_bin:
                print("SPI read:\t" + name, "(", hex(first), hex(second), ")", binprint(spires[1]), binprint(spires[0]))
            else:
                print("SPI read:\t" + name, "(", hex(first), hex(second), ")", hex(spires[1]), hex(spires[0]))
        return spires
    else:
        if not quiet:
            if nbyte == 4:
                print("SPI write:\t" + name, "(", hex(first), hex(second), ")", hex(third), hex(fourth))
            else:
                print("SPI write:\t" + name, "(", hex(first), hex(second), ")", hex(third))

def spicommand2(usb, name, first, second, third, fourth, read, cs=0, nbyte=3, quiet=True):
    # first byte to send, start of address
    # second byte to send, rest of address
    # third byte to send, value to write, ignored during read, to address +1 (the higher 8 bits)
    # fourth byte to send, value to write, ignored during read
    # cs is which chip to select, adc 0 by default
    # nbyte is 2 or 3, second byte is ignored in case of 2 bytes
    if read: first = first + 0x80  # set the highest bit for read, i.e. add 0x80
    usb.send(bytes([3, cs, first, second, fourth, 100, 100, nbyte]))  # get SPI result from command
    spires = usb.recv(4)
    usb.send(bytes([3, cs, first, second + 0x01, third, 100, 100, nbyte]))  # get SPI result from command for next byte
    spires2 = usb.recv(4)
    if read:
        if not quiet:
            print("SPI read:\t" + name, "(", hex(first), hex(second), ")", hex(spires2[0]), hex(spires[0]))
    else:
        if not quiet:
            print("SPI write:\t" + name, "(", hex(first), hex(second), ")", hex(fourth), hex(third))

debugspi = False
def spimode(usb, mode):  # set SPI mode (polarity of clk and data)
    usb.send(bytes([4, mode, 0, 0, 0, 0, 0, 0]))
    spires = usb.recv(4)
    if debugspi: print("SPI mode now", spires[0])

