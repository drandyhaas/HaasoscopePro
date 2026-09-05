#!/usr/bin/env python3
"""
Test client for the HaasoscopePro SCPI socket interface.

Connects to the SCPI server (default localhost:32001) and demonstrates
querying identity, rates, depths, and retrieving waveform data.

Usage:
    python test_scpi_client.py [host] [port]

The Haasoscope software must be running with the SCPI socket enabled.
"""

import socket
import struct
import sys
import numpy as np


def send_command(sock, command):
    """Send a text command and return the text response."""
    sock.sendall((command + '\n').encode('utf-8'))
    return sock.recv(4096).decode('utf-8', errors='ignore')


def recv_all(sock, nbytes):
    """Receive exactly nbytes from the socket."""
    data = bytearray()
    while len(data) < nbytes:
        chunk = sock.recv(nbytes - len(data))
        if not chunk:
            raise ConnectionError("Connection closed while receiving data")
        data += chunk
    return bytes(data)


def parse_waveform_payload(data):
    """Parse the binary payload returned by the 'K' command."""
    offset = 0

    seqnum = int.from_bytes(data[offset:offset+4], 'little')
    offset += 4

    num_channels = int.from_bytes(data[offset:offset+2], 'little')
    offset += 2

    fs_per_sample = int.from_bytes(data[offset:offset+8], 'little')
    offset += 8

    trigger_pos_fs = int.from_bytes(data[offset:offset+8], 'little')
    offset += 8

    wfms_per_s = struct.unpack_from('d', data, offset)[0]
    offset += 8

    print(f"  Sequence number:   {seqnum}")
    print(f"  Number of channels: {num_channels}")
    print(f"  fs/sample:         {fs_per_sample}  ({fs_per_sample/1e3:.1f} ps/sample, {1e15/fs_per_sample/1e9:.3f} GS/s)")
    print(f"  Trigger position:  {trigger_pos_fs} fs")
    print(f"  Waveforms/sec:     {wfms_per_s:.1f}")

    channels = []
    for i in range(num_channels):
        chan_index = data[offset]
        offset += 1

        memdepth = int.from_bytes(data[offset:offset+8], 'little')
        offset += 8

        scale = struct.unpack_from('f', data, offset)[0]
        offset += 4

        ch_offset = struct.unpack_from('f', data, offset)[0]
        offset += 4

        trigphase = struct.unpack_from('f', data, offset)[0]
        offset += 4

        clipping = data[offset]
        offset += 1

        # Waveform samples are 16-bit signed integers
        num_bytes = memdepth * 2
        raw_samples = np.frombuffer(data[offset:offset+num_bytes], dtype=np.int16)
        offset += num_bytes

        waveform_volts = raw_samples.astype(np.float64) * scale

        print(f"\n  Channel {chan_index}:")
        print(f"    Memory depth: {memdepth} samples")
        print(f"    Scale:        {scale:.6f} V/count")
        print(f"    Offset:       {ch_offset:.6f} V")
        print(f"    Trig phase:   {trigphase:.2f} fs")
        print(f"    Clipping:     {clipping}")
        print(f"    Waveform min: {waveform_volts.min():.4f} V")
        print(f"    Waveform max: {waveform_volts.max():.4f} V")
        print(f"    Waveform rms: {np.sqrt(np.mean(waveform_volts**2)):.4f} V")

        channels.append({
            'index': chan_index,
            'memdepth': memdepth,
            'scale': scale,
            'offset': ch_offset,
            'trigphase': trigphase,
            'clipping': clipping,
            'samples_raw': raw_samples,
            'samples_volts': waveform_volts,
        })

    return {
        'seqnum': seqnum,
        'num_channels': num_channels,
        'fs_per_sample': fs_per_sample,
        'trigger_pos_fs': trigger_pos_fs,
        'wfms_per_s': wfms_per_s,
        'channels': channels,
    }


def get_waveform(sock):
    """Send the 'K' command and receive the binary waveform payload."""
    sock.sendall(b'K\n')

    # Read the fixed-size header first: seqnum(4) + numchan(2) + fs/sample(8) + trigpos(8) + wfms/s(8) = 30 bytes
    header = recv_all(sock, 30)
    num_channels = int.from_bytes(header[4:6], 'little')

    # For each channel, read the per-channel header to get memdepth, then read sample data
    channel_data = bytearray()
    for _ in range(num_channels):
        # chan_index(1) + memdepth(8) + scale(4) + offset(4) + trigphase(4) + clipping(1) = 22 bytes
        ch_header = recv_all(sock, 22)
        memdepth = int.from_bytes(ch_header[1:9], 'little')
        samples = recv_all(sock, memdepth * 2)
        channel_data += ch_header + samples

    full_payload = header + bytes(channel_data)
    return full_payload


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 32001

    print(f"Connecting to SCPI server at {host}:{port} ...")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5.0)
        sock.connect((host, port))
        print("Connected!\n")

        # Query identity
        print("--- *IDN? ---")
        idn = send_command(sock, '*IDN?')
        print(f"  {idn.strip()}\n")

        # Query sample rates
        print("--- RATES? ---")
        rates = send_command(sock, 'RATES?')
        print(f"  {rates.strip()}\n")

        # Query memory depths
        print("--- DEPTHS? ---")
        depths = send_command(sock, 'DEPTHS?')
        print(f"  {depths.strip()}\n")

        # Get waveform data
        print("--- Waveform (K command) ---")
        payload = get_waveform(sock)
        parse_waveform_payload(payload)

        print("\nDone.")


if __name__ == '__main__':
    main()
