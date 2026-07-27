import socket
import time


class NicTriggerSender:

    def __init__(self, host="127.0.0.1", port=1234):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self):
        """Establishes connection to local NIC2 instance."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))

    def send_trigger(self, code: int):
        """Sends an instantaneous trigger marker."""
        if not self.sock:
            raise RuntimeError("Socket not connected. Call connect() first.")
        message = f"<TRIGGER>{code}</TRIGGER>"
        self.sock.sendall(message.encode())

    def send_timed_trigger(self, code: int, duration_ms: int):
        """Sends a trigger, holds it, then sends a 0 clear code."""
        self.send_trigger(code)
        time.sleep(duration_ms / 1000.0)
        self.send_trigger(0)  # Reset trigger state in NIC2

    def close(self):
        """Closes the socket connection safely."""
        if self.sock:
            self.sock.close()
