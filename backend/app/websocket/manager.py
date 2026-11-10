import json
from typing import Dict, List
from fastapi import WebSocket
from starlette.websockets import WebSocketState

class ConnectionManager:
    """Manages active WebSockets for Shopper phones, Cart simulators, and Admin portals."""

    def __init__(self):
        # Maps cart_id -> list of active WebSockets (Shopper app + Cart camera agent)
        self.cart_connections: Dict[str, List[WebSocket]] = {}
        # Active staff admin portal connections
        self.admin_connections: List[WebSocket] = []
        # Dedicated cart camera hardware/laptop connections (single connection per cart_id)
        self.device_connections: Dict[str, WebSocket] = {}

    async def connect_device(self, cart_id: str, websocket: WebSocket) -> None:
        """Register a cart device WebSocket, disconnecting any previous device on this cart."""
        if cart_id in self.device_connections:
            old_ws = self.device_connections[cart_id]
            if old_ws != websocket:
                try:
                    await old_ws.close(code=4009, reason="Replaced by new device connection")
                except Exception:
                    pass
        self.device_connections[cart_id] = websocket

    def disconnect_device(self, cart_id: str, websocket: WebSocket = None):
        """Unregister a cart device WebSocket."""
        if cart_id in self.device_connections:
            if websocket is None or self.device_connections[cart_id] == websocket:
                del self.device_connections[cart_id]

    async def close_device_connection(self, cart_id: str, code: int = 4005, reason: str = "Device disconnected"):
        """Explicitly disconnect active camera device for a cart (e.g. on token regeneration or disable)."""
        if cart_id in self.device_connections:
            ws = self.device_connections.pop(cart_id, None)
            if ws:
                try:
                    await ws.close(code=code, reason=reason)
                except Exception:
                    pass

    async def connect_cart(self, websocket: WebSocket, cart_id: str):
        if websocket.client_state == WebSocketState.CONNECTING:
            await websocket.accept()
        if cart_id not in self.cart_connections:
            self.cart_connections[cart_id] = []
        if websocket not in self.cart_connections[cart_id]:
            self.cart_connections[cart_id].append(websocket)

    def disconnect_cart(self, websocket: WebSocket, cart_id: str):
        if cart_id in self.cart_connections:
            if websocket in self.cart_connections[cart_id]:
                self.cart_connections[cart_id].remove(websocket)
            if not self.cart_connections[cart_id]:
                del self.cart_connections[cart_id]

    async def connect_admin(self, websocket: WebSocket):
        if websocket.client_state == WebSocketState.CONNECTING:
            await websocket.accept()
        if websocket not in self.admin_connections:
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
