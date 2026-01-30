"""
Camera Shutter Editor

Visual tool for drawing polygon ignore regions on camera frames.
Saves to JSON file that can be imported to database via ShutterService.

Usage:
    python shutter_editor.py <frame_image.jpg> <out_shutters.json>

Controls:
    - Left click: Add point to current polygon
    - Right click: Undo last point
    - Enter: Commit current polygon
    - Backspace: Delete last committed polygon
    - M: Toggle mode (ignore/allow)
    - S: Save to JSON
    - Q/Esc: Quit
"""

import json
import os
import sys
from dataclasses import dataclass, asdict
from typing import List, Tuple

import numpy as np
import cv2

Point = Tuple[int, int]


@dataclass
class ShutterPoly:
    mode: str
    points_norm: List[Tuple[float, float]]


def to_norm(points_px: List[Point], w: int, h: int) -> List[Tuple[float, float]]:
    return [(x / w, y / h) for (x, y) in points_px]


def to_px(points_norm: List[Tuple[float, float]], w: int, h: int) -> List[Point]:
    return [(int(x * w), int(y * h)) for (x, y) in points_norm]


def render_frame(img, shutters: List[ShutterPoly], cur_points_px: List[Point], mode: str):
    h, w = img.shape[:2]
    overlay = img.copy()
    
    for sh in shutters:
        pts = to_px(sh.points_norm, w, h)
        if len(pts) < 3:
            continue
        pts_array = np.array(pts, dtype=np.int32)
        color = (0, 0, 0) if sh.mode == "ignore" else (0, 255, 0)
        cv2.fillPoly(overlay, [pts_array], color)
        cv2.polylines(overlay, [pts_array], True, (255, 255, 255), 2)
    
    if cur_points_px:
        if len(cur_points_px) >= 2:
            pts_array = np.array(cur_points_px, dtype=np.int32)
            color = (0, 0, 255) if mode == "ignore" else (0, 255, 255)
            cv2.polylines(overlay, [pts_array], False, color, 2)
        
        for pt in cur_points_px:
            cv2.circle(overlay, pt, 5, (255, 0, 0), -1)
    
    preview = cv2.addWeighted(overlay, 0.35, img, 0.65, 0)
    
    instructions = [
        f"Mode: {mode.upper()}",
        f"Points: {len(cur_points_px)}",
        f"Shutters: {len(shutters)}",
        "",
        "Left click: Add point",
        "Right click: Undo point",
        "Enter: Commit polygon",
        "Backspace: Delete last",
        "M: Toggle mode",
        "S: Save",
        "Q/Esc: Quit"
    ]
    
    y_offset = 30
    for line in instructions:
        cv2.putText(preview, line, (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 
                    0.5, (255, 255, 255), 1, cv2.LINE_AA)
        y_offset += 20
    
    return preview


def save_to_json(shutters: List[ShutterPoly], filepath: str):
    data = [asdict(sh) for sh in shutters]
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(shutters)} shutters to {filepath}")


def main():
    if len(sys.argv) != 3:
        print("Usage: python shutter_editor.py <frame_image.jpg> <out_shutters.json>")
        sys.exit(1)
    
    img_path = sys.argv[1]
    out_path = sys.argv[2]
    
    if not os.path.exists(img_path):
        print(f"Error: Image file not found: {img_path}")
        sys.exit(1)
    
    img = cv2.imread(img_path)
    if img is None:
        print(f"Error: Could not load image: {img_path}")
        sys.exit(1)
    
    h, w = img.shape[:2]
    print(f"Loaded image: {w}x{h}")
    
    shutters: List[ShutterPoly] = []
    current_points: List[Point] = []
    current_mode = "ignore"
    
    def mouse_callback(event, x, y, flags, param):
        nonlocal current_points
        
        if event == cv2.EVENT_LBUTTONDOWN:
            current_points.append((x, y))
            print(f"Added point {len(current_points)}: ({x}, {y})")
        
        elif event == cv2.EVENT_RBUTTONDOWN:
            if current_points:
                removed = current_points.pop()
                print(f"Removed point: {removed}")
    
    window_name = "Shutter Editor"
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, mouse_callback)
    
    print("\nControls:")
    print("  Left click: Add point to polygon")
    print("  Right click: Undo last point")
    print("  Enter: Commit current polygon")
    print("  Backspace: Delete last committed polygon")
    print("  M: Toggle mode (ignore/allow)")
    print("  S: Save to JSON")
    print("  Q/Esc: Quit")
    print()
    
    while True:
        frame = render_frame(img, shutters, current_points, current_mode)
        cv2.imshow(window_name, frame)
        
        key = cv2.waitKey(1) & 0xFF
        
        if key == ord('q') or key == 27:
            break
        
        elif key == 13:
            if len(current_points) >= 3:
                normalized = to_norm(current_points, w, h)
                shutter = ShutterPoly(mode=current_mode, points_norm=normalized)
                shutters.append(shutter)
                print(f"Committed {current_mode} polygon with {len(current_points)} points")
                current_points = []
            else:
                print("Need at least 3 points to create a polygon")
        
        elif key == 8:
            if shutters:
                removed = shutters.pop()
                print(f"Deleted last shutter ({removed.mode})")
        
        elif key == ord('m'):
            current_mode = "allow" if current_mode == "ignore" else "ignore"
            print(f"Mode: {current_mode}")
        
        elif key == ord('s'):
            if shutters:
                save_to_json(shutters, out_path)
            else:
                print("No shutters to save")
    
    cv2.destroyAllWindows()
    
    if shutters:
        save_to_json(shutters, out_path)
    
    print("Editor closed")


if __name__ == "__main__":
    main()
