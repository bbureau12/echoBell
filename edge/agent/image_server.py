#!/usr/bin/env python3
"""
Simple HTTP Image Server for Edge Devices

Serves images saved by the camera agent so the policy server can fetch them.

Usage:
    python edge_image_server.py --port 8080 --dir /var/echoBell/images

This runs a lightweight HTTP server that:
1. Serves images from the specified directory
2. Supports CORS for cross-origin requests
3. Logs all requests
4. Auto-cleans old images (optional)
"""

import os
import sys
import argparse
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import threading


class ImageServerHandler(SimpleHTTPRequestHandler):
    """Custom handler with CORS and logging"""
    
    def __init__(self, *args, directory=None, **kwargs):
        self.directory = directory
        super().__init__(*args, directory=directory, **kwargs)
    
    def end_headers(self):
        """Add CORS headers"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()
    
    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.end_headers()
    
    def log_message(self, format, *args):
        """Log requests with timestamp"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} - {format % args}")


class ImageServer:
    """HTTP server for serving edge device images"""
    
    def __init__(self, port=8080, directory="/var/echoBell/images"):
        self.port = port
        self.directory = directory
        self.server = None
        self.thread = None
        
        # Create directory if it doesn't exist
        Path(directory).mkdir(parents=True, exist_ok=True)
        
        print(f"[IMAGE_SERVER] Configured:")
        print(f"  Port: {port}")
        print(f"  Directory: {directory}")
    
    def start(self):
        """Start the HTTP server in a background thread"""
        handler = lambda *args, **kwargs: ImageServerHandler(
            *args, directory=self.directory, **kwargs
        )
        
        self.server = HTTPServer(('0.0.0.0', self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        
        print(f"[IMAGE_SERVER] Started on http://0.0.0.0:{self.port}")
        print(f"[IMAGE_SERVER] Serving files from: {self.directory}")
        print(f"[IMAGE_SERVER] Press Ctrl+C to stop")
    
    def stop(self):
        """Stop the HTTP server"""
        if self.server:
            self.server.shutdown()
            print("[IMAGE_SERVER] Stopped")
    
    def cleanup_old_images(self, max_age_hours=24):
        """Remove images older than max_age_hours"""
        cutoff = time.time() - (max_age_hours * 3600)
        removed = 0
        
        for filepath in Path(self.directory).glob("*.jpg"):
            if filepath.stat().st_mtime < cutoff:
                filepath.unlink()
                removed += 1
        
        if removed > 0:
            print(f"[IMAGE_SERVER] Cleaned up {removed} old images")
        
        return removed


def auto_cleanup(server, interval_minutes=60, max_age_hours=24):
    """Periodically clean up old images"""
    while True:
        time.sleep(interval_minutes * 60)
        server.cleanup_old_images(max_age_hours)


def main():
    parser = argparse.ArgumentParser(
        description="Simple HTTP server for edge device images"
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8080,
        help='Port to listen on (default: 8080)'
    )
    parser.add_argument(
        '--dir',
        type=str,
        default='/var/echoBell/images',
        help='Directory containing images (default: /var/echoBell/images)'
    )
    parser.add_argument(
        '--cleanup',
        action='store_true',
        help='Enable automatic cleanup of old images'
    )
    parser.add_argument(
        '--max-age',
        type=int,
        default=24,
        help='Max age of images in hours before cleanup (default: 24)'
    )
    
    args = parser.parse_args()
    
    # Create and start server
    server = ImageServer(port=args.port, directory=args.dir)
    server.start()
    
    # Start auto-cleanup if enabled
    if args.cleanup:
        cleanup_thread = threading.Thread(
            target=auto_cleanup,
            args=(server, 60, args.max_age),
            daemon=True
        )
        cleanup_thread.start()
        print(f"[IMAGE_SERVER] Auto-cleanup enabled (max age: {args.max_age}h)")
    
    # Keep running until Ctrl+C
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[IMAGE_SERVER] Shutting down...")
        server.stop()
        return 0


if __name__ == '__main__':
    sys.exit(main())
