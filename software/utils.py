import time
import numpy as np
from scipy.signal import find_peaks
from scipy.fft import fft, fftfreq
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets

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
        if num < 10:
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
    rw = 0.3
    gw = 0.4
    bw = 0.2
    r1 = reverse_bits(int(r1*rw))
    g1 = reverse_bits(int(g1*gw))
    b1 = reverse_bits(int(b1*bw))
    r2 = reverse_bits(int(r2*rw))
    g2 = reverse_bits(int(g2*gw))
    b2 = reverse_bits(int(b2*bw))
    for i in range(2):
        usb.send(bytes([11, 1, g1, r1, b1, g2, r2, b2]))  # send
        usb.recv(4)
        time.sleep(.001)
        usb.send(bytes([11, 0, g1, r1, b1, g2, r2, b2]))  # stop sending
        usb.recv(4)
        time.sleep(.001)

def auxoutselector(usb, val, doprint=False):
    usb.send(bytes([2, 10, val, 0, 99, 99, 99, 99])) # set aux out SMA on back panel
    res = usb.recv(4)
    if doprint: print("auxoutselector now",val,"and was",res[0])

def clkout_ena(usb, en, doprint=True):
    usb.send(bytes([2, 9, en, 0, 99, 99, 99, 99])) # turn on/off lvdsout_clk
    res = usb.recv(4)
    if doprint: print("clkout_ena now",en,"and was",res[0])

def flash_erase(usb, doprint=False):
    usb.send(bytes([17, 0, 0, 0, 99, 100, 101, 102])) # erase
    res = usb.recv(4)
    if doprint: print("bulk erase got", res[0])

def flash_busy(usb, doprint=False):
    usb.send(bytes([14, 13, 0, 0, 99, 99, 99, 99])) # get flash busy status
    res = usb.recv(4)
    if doprint: print("flash busy got", res[0])
    return res[0]

def flash_write(usb, byte3, byte2, byte1, valuetowrite, dorecieve=True):
    usb.send(bytes([16, byte3, byte2, byte1, reverse_bits(valuetowrite), 100, 101, 102])) # write to address
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
    lengthsent = usb.send(bytes([15, byte3, byte2, byte1, 99, 99, 99, 99]))  # read from address
    if lengthsent!=8:
        print("flash_read sent",lengthsent,"bytes?!")
    if dorecieve:
        res = usb.recv(4)
        if len(res)==4:
            print(byte3*256*256+byte2*256+byte1, "", reverse_bits(res[0]), "and timeoutcounter",res[3]*256*256+res[2]*256+res[3])
        else:
            print("flash_read timeout?")

def flash_readall(usb):
    readbytes = bytearray([])
    for k in range(20):
        print("reading block", k+1, "of 20")
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
        else: print("flash_readall timeout?")
    return readbytes

def reload_firmware(usb):
    print("New firmware is being loaded into the FPGA")
    usb.send(bytes([2, 19, 1, 0, 100, 100, 100, 100]))
    usb.recv(4)

def find_fundamental_frequency_scipy(signal, sampling_rate):
    """
    Finds the fundamental frequency using SciPy's find_peaks for robustness.

    Args:
        signal (np.ndarray): The input signal.
        sampling_rate (float): The sampling rate in Hz.

    Returns:
        float: The fundamental frequency in Hz.
    """
    n = len(signal)

    # Use scipy.fft for consistency, though np.fft.fft works identically
    fft_values = fft(signal)
    frequencies = fftfreq(n, 1 / sampling_rate)

    # We only care about the positive frequencies
    positive_mask = frequencies > 0
    positive_freqs = frequencies[positive_mask]
    positive_mags = np.abs(fft_values[positive_mask])

    # Find peaks in the magnitude spectrum
    # 'height=...' is a great way to filter out noise!
    # It requires a peak to have at least this magnitude.
    peak_indices, _ = find_peaks(positive_mags, height=np.max(positive_mags) / 4)

    if not peak_indices.any():
        return None  # No peak found

    # Assume the fundamental is the lowest frequency peak found
    # (Often the strongest, but not always if harmonics are stronger)
    fundamental_freq_index = peak_indices[0]
    fundamental_freq = positive_freqs[fundamental_freq_index]

    return fundamental_freq


def format_freq(freq_hz):
    """Formats a frequency in Hz to a string with appropriate units."""
    if freq_hz is None:
        return "N/A"

    if freq_hz < 1000:
        # Keep as Hz
        return f"{freq_hz:.3f} Hz"
    elif freq_hz < 1_000_000:
        # Convert to kHz
        return f"{freq_hz / 1000:.3f} kHz"
    elif freq_hz < 1_000_000_000:
        # Convert to MHz
        return f"{freq_hz / 1_000_000:.3f} MHz"
    else:
        # Convert to GHz
        return f"{freq_hz / 1_000_000_000:.3f} GHz"

def find_crossing_distance(y_data, y_threshold, x_start, x0=0.0, dx=1.0):
    """
    Calculates the horizontal distance from a starting x-position to the
    crossing point that is CLOSEST to that position.

    Args:
        y_data (np.ndarray): An array of y-values, assumed to be evenly spaced in x.
        y_threshold (float): The y-value to find the crossing for.
        x_start (float): The reference x-position to find the closest crossing to.
        x0 (float, optional): The x-coordinate of the first data point. Defaults to 0.0.
        dx (float, optional): The spacing between x-coordinates. Defaults to 1.0.

    Returns:
        float: The signed distance along x from x_start to the closest
               intersection point. Returns None if no crossing is found.
    """
    # Find all indices where y_data goes from below to at or above the threshold
    crossover_indices = np.where((y_data[:-1] < y_threshold) & (y_data[1:] >= y_threshold))[0]

    if crossover_indices.size == 0: return None

    # Calculate the x-intersection point for ALL crossovers
    y1 = y_data[crossover_indices]
    y2 = y_data[crossover_indices + 1]
    x1 = x0 + crossover_indices * dx

    fraction = (y_threshold - y1) / (y2 - y1)
    all_x_intersects = x1 + fraction * dx

    # Find the intersection point that is closest to x_start
    # We calculate the absolute difference to find the minimum distance,
    # then select the corresponding x_intersect value.
    closest_idx = np.argmin(np.abs(all_x_intersects - x_start))
    closest_x_intersect = all_x_intersects[closest_idx]

    return closest_x_intersect - x_start

def add_secondary_axis(plot_item, conversion_func, **axis_args):
    """
    Adds a secondary y-axis that is dynamically linked by a conversion function.

    The conversion function and update logic are attached to the returned
    AxisItem, allowing them to be modified later.
    """
    # Create and add the proxy ViewBox
    proxy_view = pg.ViewBox()
    proxy_view.setMenuEnabled(False)  # disables the right-click menu
    plot_item.scene().addItem(proxy_view)

    # Get the right axis and link it
    axis = plot_item.getAxis('right')
    axis.linkToView(proxy_view)
    axis.setLabel(**axis_args)
    plot_item.showAxis('right')

    # Attach the key components to the axis object
    axis.proxy_view = proxy_view
    axis.conversion_func = conversion_func  # Attach the function itself

    # Define the update function
    def update_proxy_range():
        # Use the conversion_func attached to this axis object
        main_yrange = plot_item.getViewBox().viewRange()[1]
        proxy_range = [axis.conversion_func(y) for y in main_yrange]
        axis.proxy_view.setYRange(*proxy_range, padding=0.01, update=False)

    # Attach the update function so we can call it manually
    axis.update_function = update_proxy_range

    # Connect signals
    plot_item.getViewBox().sigYRangeChanged.connect(axis.update_function)

    def update_geometry():
        axis.proxy_view.setGeometry(plot_item.getViewBox().sceneBoundingRect())

    plot_item.getViewBox().sigResized.connect(update_geometry)

    # Trigger initial updates
    axis.update_function()
    update_geometry()

    return axis
