# network.py
"""
Manages the network socket for remote control in a separate thread.
"""
import threading
import time
from SCPIsocket import hspro_socket # Use the actual socket class

class SocketManager:
    def __init__(self, main_window):
        self.socket_handler = hspro_socket()
        self.socket_handler.hspro = main_window
        self.socket_handler.runthethread = False
        self.thread = None

    def start(self):
        """Starts the socket listening thread."""
        if self.thread is None:
            self.socket_handler.runthethread = True
            self.thread = threading.Thread(target=self.socket_handler.open_socket, args=(10,))
            self.thread.start()
            print("Socket thread started.")

    def stop(self):
        """Stops the socket listening thread and waits for it to join."""
        if self.thread and self.thread.is_alive():
            self.socket_handler.runthethread = False
            self.thread.join()
            print("Socket thread joined.")
        self.thread = None

    def is_sending(self):
        """Checks if the socket is currently in a sending state."""
        return self.socket_handler.issending
