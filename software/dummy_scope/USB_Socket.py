"""
Socket-based USB device adapter for testing with dummy_server.py
Implements the same interface as UsbFt232hSync245mode but communicates via TCP socket.
"""

import socket
import time
from typing import Optional


class UsbSocketAdapter:
    """
    A socket-based adapter that implements the same interface as UsbFt232hSync245mode.
    Used for testing HaasoscopePro software without physical hardware.
    """

    def __init__(self, device_name: str, socket_addr: str):
        """
        Initialize socket connection to dummy server.

        Args:
            device_name (str): Device name (unused for socket, but kept for API compatibility)
            socket_addr (str): Socket address in format "host:port" (e.g., "localhost:9999")
        """
        self.device_name = device_name
        self.serial = socket_addr.encode()  # Store address as "serial"
        self.socket_addr = socket_addr
        self.beta = None
        self._socket: Optional[socket.socket] = None
        self._recv_timeout = 250  # ms
        self._send_timeout = 2000  # ms
        self.good = False
        self._buffer = b""  # Internal buffer for any excess data from recv

        # Try to connect
        self._connect()

    def _connect(self):
        """Establish socket connection to dummy server."""
        try:
            host, port_str = self.socket_addr.split(":")
            port = int(port_str)

            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.connect((host, port))

            # Set socket timeouts
            self._socket.settimeout(self._recv_timeout / 1000.0)

            self.good = True
            print(f"Connected to socket device at {self.socket_addr}")

        except Exception as e:
            self.good = False
            print(f"Failed to connect to {self.socket_addr}: {e}")
            self._socket = None

    def close(self):
        """Close the socket connection."""
        if self._socket:
            try:
                self._socket.close()
            except:
                pass
            self._socket = None

    def reopen(self):
        """Reopen the socket connection."""
        self.close()
        self._connect()

    def set_latency_timer(self, latency_ms: int):
        """No-op for socket adapter (compatibility method)."""
        pass

    def set_recv_timeout(self, timeout_ms: int):
        """Set receive timeout."""
        self._recv_timeout = timeout_ms
        if self._socket:
            self._socket.settimeout(timeout_ms / 1000.0)

    def set_send_timeout(self, timeout_ms: int):
        """Set send timeout."""
        self._send_timeout = timeout_ms

    def flush_buffer(self):
        """Clear the internal buffer AND drain any data from the socket. Used when expect_samples changes (e.g., during pllreset)."""
        self._buffer = b""
        # Try to drain any pending data from the socket without blocking
        if self._socket:
            old_timeout = self._socket.gettimeout()
            try:
                self._socket.settimeout(0.1)  # Longer timeout to ensure we drain all pending data
                drained_bytes = 0
                while True:
                    chunk = self._socket.recv(4096)
                    if not chunk:
                        break
                    drained_bytes += len(chunk)
            except socket.timeout:
                pass  # Expected - no more data
            except Exception:
                pass
            finally:
                self._socket.settimeout(old_timeout)
        if drained_bytes > 0:
            print(f"USB Socket buffer flushed (drained {drained_bytes} bytes)")
        else:
            print("USB Socket buffer flushed")

    def send(self, data: bytes) -> int:
        """
        Send data to the server.

        Args:
            data (bytes): Data to send (typically 8-byte command)

        Returns:
            int: Number of bytes sent
        """
        if not self.good or not self._socket:
            return 0

        try:
            self._socket.sendall(data)
            return len(data)
        except Exception as e:
            print(f"Send error: {e}")
            self.good = False
            return 0

    def recv(self, recv_len: int) -> bytes:
        """
        Receive data from the server, looping until all data is received or timeout.
        This function handles buffering to ensure exact byte counts are returned.
        For large data reads (>1000 bytes), we use a longer timeout to ensure we get all data.

        Args:
            recv_len (int): Number of bytes to receive

        Returns:
            bytes: Received data (exactly recv_len bytes if available, or less if timeout/error)
        """
        if not self.good or not self._socket:
            return b""

        try:
            data = self._buffer  # Start with any leftover data from previous recv
            self._buffer = b""  # Clear the buffer

            # For large data reads, use a longer timeout to ensure we get all data
            # This is critical for data transfers during PLL calibration
            if recv_len > 1000:
                old_timeout = self._socket.gettimeout()
                self._socket.settimeout(1.0)  # 1 second for large transfers

            # Read data until we have enough
            while len(data) < recv_len:
                remaining = recv_len - len(data)
                chunk = self._socket.recv(min(remaining, 65536))  # Recv in 64KB chunks
                if not chunk:
                    # Socket closed
                    break
                data += chunk

            # Restore original timeout for large reads
            if recv_len > 1000:
                self._socket.settimeout(old_timeout)

            # Return exactly recv_len bytes, save any excess for next call
            if len(data) > recv_len:
                self._buffer = data[recv_len:]
                return data[:recv_len]
            else:
                return data

        except socket.timeout:
            # Timeout - for small reads this is ok, but for large reads it's a problem
            # Just return what we have
            if len(self._buffer) > 0:
                data = self._buffer[:recv_len]
                self._buffer = self._buffer[recv_len:]
                return data
            return b""
        except Exception as e:
            print(f"Receive error: {e}")
            self.good = False
            if len(self._buffer) > 0:
                data = self._buffer[:recv_len]
                self._buffer = self._buffer[recv_len:]
                return data
            return b""
