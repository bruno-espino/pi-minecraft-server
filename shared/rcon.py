#!/usr/bin/env python3
"""
RCON Client for Minecraft Servers

A simple implementation of the Source RCON protocol used by Minecraft
servers for remote administration.
"""

import re
import socket
import struct


class RCONClient:
    """Simple RCON client for Minecraft servers."""
    
    SERVERDATA_AUTH = 3
    SERVERDATA_AUTH_RESPONSE = 2
    SERVERDATA_EXECCOMMAND = 2
    SERVERDATA_RESPONSE_VALUE = 0
    
    def __init__(self, host, port, password):
        """Initialize RCON client.
        
        Args:
            host: RCON server hostname or IP
            port: RCON port (default Minecraft: 25575)
            password: RCON password from server.properties
        """
        self.host = host
        self.port = port
        self.password = password
        self.socket = None
        self.request_id = 0
    
    def connect(self):
        """Connect and authenticate to the RCON server."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(10)
        self.socket.connect((self.host, self.port))
        
        # Authenticate
        response = self._send_packet(self.SERVERDATA_AUTH, self.password)
        if response is None:
            raise ConnectionError("RCON authentication failed")
        return True
    
    def disconnect(self):
        """Close the RCON connection."""
        if self.socket:
            self.socket.close()
            self.socket = None
    
    def close(self):
        """Alias for disconnect() for compatibility."""
        self.disconnect()
    
    def command(self, cmd):
        """Send a command and return the response.
        
        Args:
            cmd: The Minecraft command to execute (without leading /)
            
        Returns:
            Server response as string
        """
        if not self.socket:
            self.connect()
        return self._send_packet(self.SERVERDATA_EXECCOMMAND, cmd)
    
    def _send_packet(self, packet_type, payload):
        """Send a packet and receive the response."""
        self.request_id += 1
        
        # Build packet: length + request_id + type + payload + padding
        payload_bytes = payload.encode('utf-8') + b'\x00\x00'
        packet = struct.pack('<ii', self.request_id, packet_type) + payload_bytes
        packet = struct.pack('<i', len(packet)) + packet
        
        self.socket.send(packet)
        
        # Receive response
        response_length = struct.unpack('<i', self._recv_exact(4))[0]
        response_data = self._recv_exact(response_length)
        
        response_id = struct.unpack('<i', response_data[:4])[0]
        response_body = response_data[8:-2].decode('utf-8')
        
        if response_id == -1:
            return None  # Auth failed
        
        return response_body
    
    def _recv_exact(self, num_bytes):
        """Receive exactly num_bytes from the socket."""
        data = b''
        while len(data) < num_bytes:
            chunk = self.socket.recv(num_bytes - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data


def strip_color_codes(text):
    """Remove Minecraft color/formatting codes.
    
    Minecraft uses section signs (§) followed by a character for formatting.
    This function removes all such codes from the text.
    
    Args:
        text: String potentially containing Minecraft color codes
        
    Returns:
        Clean string with color codes removed
    """
    return re.sub(r'§.', '', text)
