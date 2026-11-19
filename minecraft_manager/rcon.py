"""Minimal client for the Minecraft RCON protocol."""

import re
import socket
import struct

AUTH = 3
EXEC_COMMAND = 2


class RCONError(Exception):
    """Raised when RCON is unreachable or rejects the password."""


class RCONClient:
    """One authenticated RCON connection. Use as a context manager."""

    def __init__(self, host, port, password, timeout=10):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._socket = None
        self._request_id = 0

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def connect(self):
        try:
            self._socket = socket.create_connection((self.host, self.port), self.timeout)
        except OSError as error:
            raise RCONError(f"cannot reach RCON on port {self.port}: {error}") from error
        request_id, _ = self._request(AUTH, self.password)
        if request_id == -1:
            self.close()
            raise RCONError("RCON rejected the password")

    def close(self):
        if self._socket:
            self._socket.close()
            self._socket = None

    def command(self, command):
        """Run a server command and return its text response."""
        if not self._socket:
            self.connect()
        _, body = self._request(EXEC_COMMAND, command)
        return body

    def _request(self, packet_type, payload):
        self._request_id += 1
        body = struct.pack("<ii", self._request_id, packet_type) + payload.encode() + b"\x00\x00"
        try:
            self._socket.sendall(struct.pack("<i", len(body)) + body)
            (length,) = struct.unpack("<i", self._recv_exact(4))
            data = self._recv_exact(length)
        except OSError as error:
            self.close()
            raise RCONError(f"RCON connection failed: {error}") from error
        (request_id,) = struct.unpack("<i", data[:4])
        return request_id, data[8:-2].decode("utf-8", errors="replace")

    def _recv_exact(self, size):
        data = b""
        while len(data) < size:
            chunk = self._socket.recv(size - len(data))
            if not chunk:
                raise ConnectionError("RCON connection closed")
            data += chunk
        return data


def strip_formatting(text):
    """Remove Minecraft section-sign formatting codes."""
    return re.sub(r"§.", "", text)
