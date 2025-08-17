import time

import ftd2xx, sys
from USB_FT232H import UsbFt232hSync245mode
from utils import *

def version(usb, quiet=True):
    usb.send(bytes([2, 0, 100, 100, 100, 100, 100, 100]))  # get version
    res = usb.recv(4)
    ver = int.from_bytes(res,"little")
    if len(res)==4 and not quiet: print("Firmware version", ver)
    return ver

def connectdevices(nmax=100):
    usbs = []
    try:
        ftds = ftd2xx.listDevices()
        if ftds is not None:
            print("Found",len(ftds),"devices:", ftds)
            for ftdserial in ftds:
                #print("FTD serial:",ftdserial)
                if not ftdserial.startswith(b'FT'): continue
                if len(usbs)==nmax: continue # only connect up to nmax devices
                usbdevice = UsbFt232hSync245mode('FTX232H', 'HaasoscopePro USB2', ftdserial)
                if usbdevice.good:
                    # if usbdevice.serial != b"FT9M1UIT": continue
                    # if usbdevice.serial != b"FT9LYZXP": continue
                    usbs.append(usbdevice)
                    print("Connected USB device", usbdevice.serial)
            print("Connected", len(usbs), "devices")
        else:
            print("Found no devices")
    except ftd2xx.DeviceError as e:
        print(f"Failed to communicate with the FTDI device:",e)
    return usbs

def findnextboard(currentboard,firstboard,usbs):
    for board in range(len(usbs)):
        if board == currentboard: print("setting lvds spare out high for board",board)
        else: print("setting lvds spare out low for board", board)
        usbs[board].send(bytes([2, 5, board == currentboard, 0, 99, 99, 99, 99])) # get lvdsin_spare info, and set spare lvds output high for only the current board
        usbs[board].recv(4) # have to read it out, even though we don't care
    nextboard=-1
    for board in range(len(usbs)): # see which board now has seen a signal from the current board
        if board == firstboard: continue # that one has no lvds input, so is unreliable, plus we already know it's not the next board
        usbs[board].send(bytes([2, 5, board == currentboard, 0, 99, 99, 99, 99]))
        res = usbs[board].recv(4)
        spare = getbit(res[2],0)
        print("lvds spare in for board",board,"is",spare)
        if spare==1:
            if nextboard==-1:
                nextboard=board
            else:
                print("We already found the next board to be",nextboard,"for board",currentboard,"but it is also",board,"?!")
                sys.exit(0)
    if nextboard==-1:
        print("Didn't find a next board for board",currentboard,"!")
        sys.exit(0)
    return nextboard

def orderusbs(usbs):
    newusbs=[]
    for board in range(len(usbs)):
        print("Checking board",board)
        oldbytes(usbs[board])
        version(usbs[board])
        usbs[board].send(bytes([2, 5, 0, 0, 99, 99, 99, 99]))  # get clock info
        usbs[board].recv(4)
        usbs[board].send(bytes([2, 5, 0, 0, 99, 99, 99, 99]))  # get clock info again, fixes a glitch on Mac (?)
        res = usbs[board].recv(4)
        if len(res)<4:
            print("Couldn't get lvds info from board",board,"!")
            sys.exit(0)
        if getbit(res[1],3):
            print("Board",board,"has no ext clock")
            if len(newusbs)>0:
                print("Found a second device with no external clock in! Make sure there's a sync cable between all devices, from in to out.")
                sys.exit(0)
            else:
                print("Board",board,"is the first board")
                newusbs.append(board)
    if len(newusbs)==0:
        print("Didn't find a first board with no external clock!")
        #sys.exit(0)
    while len(newusbs)<len(usbs):
        nextboard = findnextboard(newusbs[-1],newusbs[0],usbs)
        print("Found next board to be board",nextboard)
        newusbs.append(nextboard)
    newusbcons=[]
    for u in range(len(newusbs)):
        newusbcons.append(usbs[newusbs[u]])
    return newusbcons

def tellfirstandlast(usbs):
    for usb in usbs:
        if usb==usbs[0]:
            firstlast = 1
            print("firstlast==1")
        elif usb==usbs[-1]:
            firstlast = 2
            print("firstlast==2")
        else:
            firstlast = 0
            print("firstlast==0")
        usb.send(bytes([2, 14, firstlast, 0, 99, 99, 99, 99]))  # tell it if it's first or last or neither
        usb.recv(4)
