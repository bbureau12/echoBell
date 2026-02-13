#!/usr/bin/env python3
"""
Test Edge Image Server

Simulates an edge device's HTTP image server for testing photo download functionality.
This is a lightweight HTTP server that serves test images, similar to what runs on
actual edge devices.

Usage:
    # Start server on port 8080
    python tests/test_edge_image_server.py
    
    # Start on custom port
    python tests/test_edge_image_server.py --port 9000
    
    # Use custom image directory
    python tests/test_edge_image_server.py --dir data/test_images

The server will:
1. Serve images from the specified directory
2. Support CORS for cross-origin requests
3. Log all requests
4. Run on localhost (127.0.0.1)

Once running, you can test with:
    curl http://localhost:8080/test_image.jpg
"""

import argparse
import os
import sys
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import threading


class TestImageServerHandler(SimpleHTTPRequestHandler):
    """Custom handler with CORS, API key auth, and logging"""
    
    # Default API key for dev/test (same as used in other endpoints)
    API_KEY = "dontgiveitupluffy"
    
    def __init__(self, *args, directory=None, require_auth=True, **kwargs):
        self.directory = directory
        self.require_auth = require_auth
        super().__init__(*args, directory=directory, **kwargs)
    
    def _check_auth(self):
        """Check X-API-Key header"""
        if not self.require_auth:
            return True
            
        api_key = self.headers.get('X-API-Key', '')
        if api_key == self.API_KEY:
            return True
        
        self.send_response(401)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"error": "Invalid or missing X-API-Key header"}')
        return False
    
    def do_GET(self):
        """Handle GET requests with auth check"""
        if not self._check_auth():
            return
        super().do_GET()
    
    def end_headers(self):
        """Add CORS headers"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')
        super().end_headers()
    
    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.end_headers()
    
    def log_message(self, format, *args):
        """Log requests with timestamp"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        auth_status = "✓" if not self.require_auth or self.headers.get('X-API-Key') == self.API_KEY else "✗"
        print(f"[{timestamp}] {auth_status} {self.address_string()} - {format % args}")


def create_test_image(directory: Path, filename: str = "test_image.jpg"):
    """Create a simple test image if none exists"""
    filepath = directory / filename
    
    if filepath.exists():
        print(f"  ✓ Test image already exists: {filepath}")
        return filepath
    
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        # Create a simple test image
        img = Image.new('RGB', (640, 480), color='lightblue')
        draw = ImageDraw.Draw(img)
        
        # Add text
        text = f"Test Image\n{filename}\n{time.strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Draw rectangle border
        draw.rectangle([10, 10, 630, 470], outline='darkblue', width=5)
        
        # Draw text (use default font)
        draw.text((320, 240), text, fill='darkblue', anchor='mm')
        
        # Save image
        img.save(filepath, 'JPEG')
        print(f"  ✓ Created test image: {filepath}")
        
    except ImportError:
        print("  ⚠️  PIL not installed, creating blank file")
        # Create a minimal valid JPEG file
        with open(filepath, 'wb') as f:
            # Minimal JPEG header
            f.write(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00')
            f.write(b'\xff\xd9')  # End of image
    
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Test HTTP server simulating edge device image server"
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
        default='data/edge_images',
        help='Directory containing images (default: data/edge_images)'
    )
    parser.add_argument(
        '--create-test-image',
        action='store_true',
        help='Create a test image if none exists'
    )
    parser.add_argument(
        '--no-auth',
        action='store_true',
        help='Disable API key authentication (not recommended for production)'
    )
    
    args = parser.parse_args()
    
    # Create directory if it doesn't exist
    directory = Path(args.dir)
    directory.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("🖼️  Test Edge Image Server")
    print("=" * 60)
    print(f"Port: {args.port}")
    print(f"Directory: {directory.absolute()}")
    print("=" * 60)
    print()
    
    # Create test image if requested
    if args.create_test_image:
        print("Creating test image...")
        create_test_image(directory)
        print()
    
    # List available images
    image_files = list(directory.glob("*.jpg")) + list(directory.glob("*.png"))
    if image_files:
        print(f"Available images ({len(image_files)}):")
        for img in image_files[:10]:  # Show first 10
            size_kb = img.stat().st_size / 1024
            print(f"  • {img.name} ({size_kb:.1f} KB)")
            print(f"    URL: http://localhost:{args.port}/{img.name}")
        if len(image_files) > 10:
            print(f"  ... and {len(image_files) - 10} more")
    else:
        print("⚠️  No images found in directory")
        print("   Use --create-test-image to generate a test image")
    
    print()
    print("=" * 60)
    print("Server starting...")
    print(f"Access images at: http://localhost:{args.port}/")
    if not args.no_auth:
        print(f"API Key required: X-API-Key: dontgiveitupluffy")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    print()
    
    # Create and start server
    require_auth = not args.no_auth
    handler = lambda *args, **kwargs: TestImageServerHandler(
        *args, directory=str(directory.absolute()), require_auth=require_auth, **kwargs
    )
    
    server = HTTPServer(('127.0.0.1', args.port), handler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n" + "=" * 60)
        print("Server stopped")
        print("=" * 60)
        return 0


if __name__ == '__main__':
    sys.exit(main())
