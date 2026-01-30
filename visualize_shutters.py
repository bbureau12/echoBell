#!/usr/bin/env python3
"""Visualize shutters overlaid on test image"""
import cv2
import numpy as np
import json

# Load the test image
img = cv2.imread('tests/fixtures/shutter/shutter_test.png')
if img is None:
    print('Error: Could not load image')
    exit(1)

h, w = img.shape[:2]
print(f'Image size: {w}x{h}')

# Load the shutters JSON
with open('tests/fixtures/shutter/shutters.json', 'r') as f:
    shutters = json.load(f)

print(f'Found {len(shutters)} shutter(s)')

# Draw shutters on image
overlay = img.copy()
for idx, shutter in enumerate(shutters):
    # Convert normalized to pixel coordinates
    pts = [(int(x * w), int(y * h)) for x, y in shutter['points_norm']]
    pts_array = np.array(pts, dtype=np.int32)
    
    # Draw filled polygon (semi-transparent red for ignore, green for allow)
    color = (0, 0, 255) if shutter['mode'] == 'ignore' else (0, 255, 0)
    cv2.fillPoly(overlay, [pts_array], color)
    cv2.polylines(overlay, [pts_array], True, (255, 255, 255), 2)
    
    # Add label
    cx = int(np.mean([p[0] for p in pts]))
    cy = int(np.mean([p[1] for p in pts]))
    name = shutter.get('name', f'Shutter {idx+1}')
    label = f"{name} ({shutter['mode']})"
    cv2.putText(overlay, label, (cx-100, cy), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    
    print(f'  {idx+1}. {name} - {shutter["mode"]} mode - {len(pts)} points')

# Blend with original (40% overlay, 60% original)
result = cv2.addWeighted(overlay, 0.4, img, 0.6, 0)

# Save visualization
output_path = 'tests/fixtures/shutter/shutter_visualization.png'
cv2.imwrite(output_path, result)
print(f'\nSaved visualization to {output_path}')
print('Red regions = IGNORE (detections will be filtered)')
print('Green regions = ALLOW (detections will be kept)')
