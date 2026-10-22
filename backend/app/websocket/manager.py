import json
from typing import Dict, List
from fastapi import WebSocket

class ConnectionManager:
    """Manages active WebSockets for Shopper phones, Cart simulators, and Admin portals."""

    def __init__(self):
        # Maps cart_id -> list of active WebSockets (Shopper app + Cart camera agent)
        self.cart_connections: Dict[str, List[WebSocket]] = {}
        # Active staff admin portal connections
        self.admin_connections: List[WebSocket] = []

    async def connect_cart(self, websocket: WebSocket, cart_id: str):
        await websocket.accept()
        if cart_id not in self.cart_connections:
            self.cart_connections[cart_id] = []
        self.cart_connections[cart_id].append(websocket)

    def disconnect_cart(self, websocket: WebSocket, cart_id: str):
        if cart_id in self.cart_connections:
            if websocket in self.cart_connections[cart_id]:
                self.cart_connections[cart_id].remove(websocket)
            if not self.cart_connections[cart_id]:
                del self.cart_connections[cart_id]

    async def connect_admin(self, websocket: WebSocket):
        await websocket.accept()
        self.admin_connections.append(websocket)

    def disconnect_admin(self, websocket: WebSocket):
        if websocket in self.admin_connections:
            self.admin_connections.remove(websocket)

    async def broadcast_to_cart(self, cart_id: str, event_type: str, data: dict):
        """Send event to all devices connected to a specific cart session."""
        message = json.dumps({"event": event_type, "data": data})
        if cart_id in self.cart_connections:
            for connection in list(self.cart_connections[cart_id]):
                try:
                    await connection.send_text(message)
                except Exception:
                    self.disconnect_cart(connection, cart_id)

    async def broadcast_to_admin(self, event_type: str, data: dict):
        """Send real-time alert or status event to all admin portal sessions."""
        message = json.dumps({"event": event_type, "data": data})
        for connection in list(self.admin_connections):
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect_admin(connection)

    async def broadcast_all(self, event_type: str, data: dict):
        """Broadcast universally across all active websockets."""
        message = json.dumps({"event": event_type, "data": data})
        for cart_id in list(self.cart_connections.keys()):
            for connection in list(self.cart_connections[cart_id]):
                try:
                    await connection.send_text(message)
                except Exception:
                    self.disconnect_cart(connection, cart_id)
        for connection in list(self.admin_connections):
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect_admin(connection)

ws_manager = ConnectionManager()
