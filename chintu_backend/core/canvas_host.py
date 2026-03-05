"""Canvas Host - HTTP file server for canvas assets.

Provides:
- Static file serving for canvas webviews
- Canvas API endpoints (present, update, snapshot, close)
- Integration with A2UI service
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional, Dict, Any
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_PORT = 8780
CANVAS_URL_PREFIX = "/__chintu__/canvas"


class CanvasHostHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for canvas file serving and API."""
    
    # Class-level attributes (set by CanvasHost)
    canvas_dir: Path = None
    canvas_manager: Any = None
    
    def __init__(self, *args, **kwargs):
        # Set directory before parent init
        if self.canvas_dir:
            kwargs.setdefault('directory', str(self.canvas_dir))
        super().__init__(*args, **kwargs)
    
    def log_message(self, format: str, *args):
        """Override to use Python logging."""
        logger.debug(f"CanvasHost: {format % args}")
    
    def do_GET(self):
        """Handle GET requests."""
        path = self.path
        
        # Health check
        if path == "/__chintu__/health":
            self._send_json({"status": "ok"})
            return
        
        # Canvas API - get current state
        if path == f"{CANVAS_URL_PREFIX}/state":
            if self.canvas_manager:
                state = self.canvas_manager.get_state()
                self._send_json(state)
            else:
                self._send_json({"error": "Canvas manager not available"}, status=503)
            return
        
        # Canvas API - list canvases
        if path == f"{CANVAS_URL_PREFIX}/list":
            if self.canvas_manager:
                canvases = self.canvas_manager.list_canvases()
                self._send_json({"canvases": canvases})
            else:
                self._send_json({"canvases": []})
            return
        
        # Static file serving from canvas directory
        if path.startswith(CANVAS_URL_PREFIX + "/files/"):
            # Strip prefix and serve file
            file_path = path[len(CANVAS_URL_PREFIX + "/files/"):]
            self._serve_file(file_path)
            return
        
        # Default: 404
        self.send_error(404, "Not Found")
    
    def do_POST(self):
        """Handle POST requests for canvas actions."""
        path = self.path
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"
        
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, status=400)
            return
        
        # Canvas API endpoints
        if path == f"{CANVAS_URL_PREFIX}/present":
            if not self.canvas_manager:
                self._send_json({"error": "Canvas manager not available"}, status=503)
                return
            canvas_id = data.get("canvas_id")
            content = data.get("content")
            result = self.canvas_manager.present(canvas_id, content)
            self._send_json({"success": result})
            return
        
        if path == f"{CANVAS_URL_PREFIX}/update":
            if not self.canvas_manager:
                self._send_json({"error": "Canvas manager not available"}, status=503)
                return
            canvas_id = data.get("canvas_id")
            updates = data.get("updates", {})
            result = self.canvas_manager.update(canvas_id, updates)
            self._send_json({"success": result})
            return
        
        if path == f"{CANVAS_URL_PREFIX}/close":
            if not self.canvas_manager:
                self._send_json({"error": "Canvas manager not available"}, status=503)
                return
            canvas_id = data.get("canvas_id")
            result = self.canvas_manager.close(canvas_id)
            self._send_json({"success": result})
            return
        
        if path == f"{CANVAS_URL_PREFIX}/snapshot":
            if not self.canvas_manager:
                self._send_json({"error": "Canvas manager not available"}, status=503)
                return
            canvas_id = data.get("canvas_id")
            snapshot = self.canvas_manager.snapshot(canvas_id)
            self._send_json({"snapshot": snapshot})
            return
        
        if path == f"{CANVAS_URL_PREFIX}/eval":
            if not self.canvas_manager:
                self._send_json({"error": "Canvas manager not available"}, status=503)
                return
            canvas_id = data.get("canvas_id")
            script = data.get("script", "")
            result = self.canvas_manager.eval_script(canvas_id, script)
            self._send_json({"result": result})
            return
        
        self.send_error(404, "Not Found")
    
    def _send_json(self, data: Dict, status: int = 200):
        """Send a JSON response."""
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')  # CORS
        self.end_headers()
        self.wfile.write(body)
    
    def _serve_file(self, file_path: str):
        """Serve a static file from canvas directory."""
        if not self.canvas_dir:
            self.send_error(503, "Canvas directory not configured")
            return
        
        # Security: prevent path traversal
        safe_path = Path(self.canvas_dir) / file_path
        try:
            safe_path = safe_path.resolve()
            if not str(safe_path).startswith(str(self.canvas_dir.resolve())):
                self.send_error(403, "Forbidden")
                return
        except Exception:
            self.send_error(400, "Invalid path")
            return
        
        if not safe_path.exists():
            self.send_error(404, "File not found")
            return
        
        if not safe_path.is_file():
            self.send_error(403, "Not a file")
            return
        
        # Determine content type
        content_type, _ = mimetypes.guess_type(str(safe_path))
        if not content_type:
            content_type = 'application/octet-stream'
        
        # Serve file
        try:
            with open(safe_path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', len(content))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            logger.error(f"Error serving file: {e}")
            self.send_error(500, "Internal Server Error")


class CanvasHost:
    """Canvas host service - HTTP server for canvas assets and API."""
    
    def __init__(
        self,
        port: int = DEFAULT_PORT,
        canvas_dir: Optional[Path] = None,
        canvas_manager: Any = None
    ):
        self.port = port
        self.canvas_dir = canvas_dir or self._default_canvas_dir()
        self.canvas_manager = canvas_manager
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        
        # Ensure canvas directory exists
        self.canvas_dir.mkdir(parents=True, exist_ok=True)
    
    def _default_canvas_dir(self) -> Path:
        """Get default canvas directory."""
        from chintu_backend.core.config import get_config
        config = get_config()
        return config.data_dir / "canvas"
    
    def start(self) -> tuple[bool, str]:
        """Start the canvas host server."""
        if self._running:
            return True, f"Already running on port {self.port}"
        
        try:
            # Configure handler
            CanvasHostHandler.canvas_dir = self.canvas_dir
            CanvasHostHandler.canvas_manager = self.canvas_manager
            
            # Create server
            self._server = HTTPServer(("127.0.0.1", self.port), CanvasHostHandler)
            
            # Start in background thread
            self._thread = threading.Thread(target=self._serve, daemon=True)
            self._thread.start()
            
            self._running = True
            logger.info(f"Canvas host started on http://127.0.0.1:{self.port}")
            return True, f"Started on port {self.port}"
            
        except OSError as e:
            if e.errno == 10048:  # Port in use
                logger.warning(f"Canvas host port {self.port} in use")
                return False, f"Port {self.port} already in use"
            logger.error(f"Failed to start canvas host: {e}")
            return False, str(e)
        except Exception as e:
            logger.error(f"Failed to start canvas host: {e}")
            return False, str(e)
    
    def _serve(self):
        """Serve requests in background thread."""
        try:
            self._server.serve_forever()
        except Exception as e:
            logger.error(f"Canvas host error: {e}")
        finally:
            self._running = False
    
    def stop(self):
        """Stop the canvas host server."""
        if self._server:
            self._server.shutdown()
            self._server = None
        self._running = False
        logger.info("Canvas host stopped")
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"
    
    @property
    def files_url(self) -> str:
        return f"{self.base_url}{CANVAS_URL_PREFIX}/files"


# Singleton instance
_canvas_host: Optional[CanvasHost] = None


def get_canvas_host(
    port: int = DEFAULT_PORT,
    canvas_dir: Optional[Path] = None,
    canvas_manager: Any = None
) -> CanvasHost:
    """Get or create canvas host singleton."""
    global _canvas_host
    if _canvas_host is None:
        _canvas_host = CanvasHost(port=port, canvas_dir=canvas_dir, canvas_manager=canvas_manager)
    return _canvas_host
