from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import time

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return

        payload = {
            "status": "ok",
            "timestamp": time.time()
        }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

def run():
    HTTPServer(("0.0.0.0", 8081), HealthHandler).serve_forever()
