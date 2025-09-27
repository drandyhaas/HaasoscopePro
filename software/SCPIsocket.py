import socket
import struct
import time
import math
import numpy as np

class hspro_socket:
    """
    Implements a TCP socket server for remote control of the Haasoscope.

    This class runs in a separate thread and listens for SCPI-like commands
    to query the oscilloscope's state and retrieve waveform data.
    """
    hspro = None  # This will be a reference to the main MainWindow instance
    HOST = '0.0.0.0'  # Listen on all available network interfaces
    PORT = 32001  # Port to listen on

    def __init__(self):
        self.issending = False

    def data_seqnum(self):
        return self.hspro.state.nevents.to_bytes(4, "little")

    def data_numchan(self):
        s = self.hspro.state
        numchan = s.num_board * s.num_chan_per_board
        return numchan.to_bytes(2, "little")

    def data_fspersample(self):
        fspersample = int(312500 * self.hspro.state.downsamplefactor)
        return fspersample.to_bytes(8, "little")

    def data_triggerpos(self):
        # Trigger position in femtoseconds
        triggerpos_fs = int(self.hspro.plot_manager.current_vline_pos * 1e6)
        return triggerpos_fs.to_bytes(8, "little")

    def data_wfms_per_s(self):
        return struct.pack('d', self.hspro.state.lastrate)

    def data_channel(self, chan_index):
        s = self.hspro.state

        # In single-channel mode, we only serve the even-numbered channels
        hspro_chan_index = chan_index
        board = hspro_chan_index // s.num_chan_per_board

        memdepth = self.hspro.xydata[hspro_chan_index][1].size
        scale = s.max_y / pow(2, 15)
        offset = 0.0
        trigphase = -s.totdistcorr[board] * 1e6 * s.nsunits  # convert to fs
        if s.dotwochannel[board]:
            trigphase /= 2.0

        res = bytearray([chan_index])
        res += memdepth.to_bytes(8, "little")
        res += struct.pack('f', scale)
        res += struct.pack('f', offset)
        res += struct.pack('f', trigphase)
        res += bytearray([0])  # Clipping

        # Package the waveform samples as 16-bit signed integers
        waveform_data = self.hspro.xydata[hspro_chan_index][1] / scale
        waveform_data = np.clip(waveform_data, -32767, 32767).astype(np.int16)
        res += waveform_data.tobytes()

        return res

    def open_socket(self, arg1):
        """The main server loop that listens for connections and commands."""
        self.runthethread = True
        while self.runthethread:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind((self.HOST, self.PORT))
                    s.listen()
                    s.settimeout(1.0)  # Timeout to check runthethread flag
                    print(f"SCPI socket listening on {self.HOST}:{self.PORT}")

                    conn = None
                    while self.runthethread and conn is None:
                        try:
                            conn, addr = s.accept()
                        except socket.timeout:
                            continue

                    if conn:
                        with conn:
                            print(f"SCPI: Connected by {addr}")
                            while self.runthethread:
                                data = conn.recv(1024)
                                if not data:
                                    break  # Client disconnected
                                self.handle_commands(conn, data)
            except (ConnectionResetError, BrokenPipeError):
                print("SCPI: Connection closed by remote host.")
            except OSError as e:
                print(f"SCPI socket error: {e}. Retrying in 5 seconds.")
                time.sleep(5)
            except Exception as e:
                print(f"An unexpected SCPI error occurred: {e}")
                time.sleep(5)
        print("SCPI socket thread has terminated.")

    def handle_commands(self, conn, data):
        """Parses and executes commands received from the client."""
        commands = data.strip().split(b'\n')
        for com in commands:
            com_str = com.decode('utf-8', errors='ignore').strip().upper()
            if not com_str: continue
            s = self.hspro.state
            #print(f"SCPI Command: {com_str}")
            if com_str == 'K':
                while s.isdrawing: time.sleep(0.001)
                self.issending = True

                num_channels_val = s.num_board * s.num_chan_per_board
                num_channels_bytes = num_channels_val.to_bytes(2, "little")

                payload = bytearray()
                payload += self.data_seqnum()
                payload += num_channels_bytes
                payload += self.data_fspersample() # TODO: adjust for two-channel mode somehow
                payload += self.data_triggerpos()
                payload += self.data_wfms_per_s()
                for c in range(num_channels_val):
                    payload += self.data_channel(c)
                conn.sendall(payload)

                self.issending = False
                s.nevents += 1

            elif com_str == '*IDN?':
                conn.sendall(b"DrAndyHaas,HaasoscopePro,v1.0,2025\n")

            elif com_str == 'RATES?':
                # CORRECTED: Added the trailing comma before the newline
                rate = f"{3.2e9 / s.downsamplefactor},{1.0e9},\n"
                conn.sendall(rate.encode('utf-8'))

            elif com_str == 'DEPTHS?':
                # This format was already correct
                depth = f"{s.expect_samples * 40},\n"
                conn.sendall(depth.encode('utf-8'))

            elif com_str == 'START':
                if s.getone: self.hspro.single_clicked()
                if s.paused: self.hspro.dostartstop()

            elif com_str == 'STOP':
                if not s.paused: self.hspro.dostartstop()

            elif com_str == 'SINGLE':
                if not s.getone: self.hspro.single_clicked()
                if s.paused: self.hspro.dostartstop()

            elif com_str == 'FORCE':
                if not s.isrolling: self.hspro.rolling_clicked()
                if not s.getone: self.hspro.single_clicked()
                if s.paused: self.hspro.dostartstop()
