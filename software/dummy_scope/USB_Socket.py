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
        Receive data from the server.

        Args:
            recv_len (int): Number of bytes to receive

        Returns:
            bytes: Received data
        """
        if not self.good or not self._socket:
            return b""

        try:
            data = self._socket.recv(recv_len)
            return data
        except socket.timeout:
            print(f"Receive timeout after {self._recv_timeout}ms")
            return b""
        except Exception as e:
            print(f"Receive error: {e}")
            self.good = False
            return b""
