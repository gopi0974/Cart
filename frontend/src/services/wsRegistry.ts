/**
 * Global WebSocket Registry
 * Tracks active WebSockets across the frontend application so they can be
 * forcefully closed on logout or session expiry.
 */
class WebSocketRegistry {
  private sockets = new Set<WebSocket>();

  register(ws: WebSocket): () => void {
    this.sockets.add(ws);
    return () => {
      this.sockets.delete(ws);
    };
  }

  closeAll(): void {
    this.sockets.forEach((ws) => {
      try {
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close(1000, 'Logout');
        }
      } catch (err) {
        console.warn('Error closing websocket on logout:', err);
      }
    });
    this.sockets.clear();
  }
}

export const wsRegistry = new WebSocketRegistry();
