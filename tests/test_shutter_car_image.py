"""Test shutter filtering on actual car image with YOLO detections"""
import pytest
import json
import cv2
import numpy as np
from pathlib import Path
from packages.data.shutter_service import ShutterService


def test_shutter_filters_car_keeps_person():
    """
    Test that:
    - Car inside shutter region is FILTERED OUT (ignored)
    - Person outside shutter region is KEPT
    """
    # 1. Load test image
    img_path = 'tests/fixtures/shutter/shutter_test.png'
    img = cv2.imread(img_path)
    assert img is not None, f"Could not load {img_path}"
    h, w = img.shape[:2]
    print(f"\n📷 Image: {w}x{h}")
    
    # 2. Load shutters from JSON
    with open('tests/fixtures/shutter/shutters.json', 'r') as f:
        shutters_data = json.load(f)
    
    print(f"🚧 Loaded {len(shutters_data)} shutter(s)")
    for idx, s in enumerate(shutters_data):
        print(f"   {idx+1}. Mode: {s['mode']}, Points: {len(s['points_norm'])}")
    
    # 3. Run YOLO detection
    import torch
    
    # Patch torch.load to use weights_only=False for YOLO models (trusted source)
    original_load = torch.load
    def patched_load(*args, **kwargs):
        kwargs['weights_only'] = False
        return original_load(*args, **kwargs)
    torch.load = patched_load
    
    from ultralytics import YOLO
    model = YOLO('yolov8n.pt')  # Using nano model for speed
    results = model(img, verbose=False)
    
    # Restore original
    torch.load = original_load
    
    # Extract detections
    detections = []
    for result in results:
        boxes = result.boxes
        for box in boxes:
            cls = int(box.cls[0])
            conf = float(box.conf[0])
            xyxy = box.xyxy[0].cpu().numpy()
            label = model.names[cls]
            
            # Only keep car and person detections
            if label in ['car', 'person'] and conf > 0.3:
                detections.append({
                    'label': label,
                    'box': tuple(xyxy),
                    'confidence': conf
                })
    
    print(f"\n🔍 YOLO Raw Detections ({len(detections)} total):")
    for det in detections:
        x1, y1, x2, y2 = det['box']
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        print(f"   {det['label']:8s} @ ({int(cx):4d}, {int(cy):4d}) "
              f"conf={det['confidence']:.2f} "
              f"norm=({cx/w:.3f}, {cy/h:.3f})")
    
    # 4. Convert shutters to Shutter objects
    from dataclasses import dataclass
    
    @dataclass
    class Shutter:
        id: int
        camera_id: int
        name: str
        mode: str
        polygon: list
        enabled: bool
    
    shutters = []
    for idx, s in enumerate(shutters_data):
        shutters.append(Shutter(
            id=idx + 1,
            camera_id=1,
            name=s.get('name', f'Shutter {idx+1}'),
            mode=s['mode'],
            polygon=[(x, y) for x, y in s['points_norm']],
            enabled=True
        ))
    
    # 5. Convert detections to objects with .box attribute
    @dataclass
    class Detection:
        label: str
        box: tuple
        confidence: float
    
    detection_objects = [
        Detection(d['label'], d['box'], d['confidence'])
        for d in detections
    ]
    
    # 6. Apply shutter filtering
    filtered = ShutterService.filter_detections(
        detection_objects, 
        shutters, 
        w, h, 
        threshold=0.5
    )
    
    print(f"\n✂️  Shutter Filtering (threshold=0.5):")
    print(f"   Before: {len(detection_objects)} detections")
    print(f"   After:  {len(filtered)} detections")
    print(f"   Filtered out: {len(detection_objects) - len(filtered)}")
    
    # 7. Show what was kept vs filtered
    filtered_labels = {det.label for det in filtered}
    original_labels = {det.label for det in detection_objects}
    
    print(f"\n📊 Results:")
    for label in ['car', 'person']:
        was_detected = label in original_labels
        was_kept = label in filtered_labels
        
        if was_detected and was_kept:
            status = "✅ KEPT (outside shutter)"
        elif was_detected and not was_kept:
            status = "🚫 FILTERED (inside shutter)"
        elif not was_detected:
            status = "❌ NOT DETECTED by YOLO"
        else:
            status = "?"
        
        print(f"   {label:8s}: {status}")
    
    # 8. Create visualization with detections
    vis_img = img.copy()
    
    # Draw shutter region (red)
    for shutter in shutters:
        pts = [(int(x * w), int(y * h)) for x, y in shutter.polygon]
        pts_array = np.array(pts, dtype=np.int32)
        overlay = vis_img.copy()
        cv2.fillPoly(overlay, [pts_array], (0, 0, 255))
        vis_img = cv2.addWeighted(overlay, 0.3, vis_img, 0.7, 0)
        cv2.polylines(vis_img, [pts_array], True, (0, 0, 255), 2)
    
    # Draw filtered detections (green = kept)
    for det in filtered:
        x1, y1, x2, y2 = [int(v) for v in det.box]
        cv2.rectangle(vis_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label_text = f"{det.label} {det.confidence:.2f}"
        cv2.putText(vis_img, label_text, (x1, y1-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    
    # Draw filtered-out detections (red = removed)
    removed = [d for d in detection_objects if d not in filtered]
    for det in removed:
        x1, y1, x2, y2 = [int(v) for v in det.box]
        cv2.rectangle(vis_img, (x1, y1), (x2, y2), (0, 0, 255), 2)
        label_text = f"{det.label} {det.confidence:.2f} [FILTERED]"
        cv2.putText(vis_img, label_text, (x1, y1-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    
    # Save visualization
    output_path = 'tests/fixtures/shutter/detection_results.png'
    cv2.imwrite(output_path, vis_img)
    print(f"\n💾 Saved visualization to {output_path}")
    print(f"   Red boxes = Filtered out (inside shutter)")
    print(f"   Green boxes = Kept (outside shutter)")
    
    # 9. Assertions - Verify expected behavior
    assert len(detections) > 0, "YOLO should detect something in the image"
    
    # Car should be detected by YOLO but filtered out by shutter
    car_detections = [d for d in detection_objects if d.label == 'car']
    car_kept = [d for d in filtered if d.label == 'car']
    
    assert len(car_detections) > 0, "Expected YOLO to detect car in image"
    assert len(car_kept) == 0, "Expected car to be FILTERED OUT (inside shutter region)"
    print(f"\n✅ Car test PASSED: {len(car_detections)} detected, {len(car_kept)} kept (filtered out correctly)")
    
    # Person should be detected by YOLO and kept (outside shutter region)
    person_detections = [d for d in detection_objects if d.label == 'person']
    person_kept = [d for d in filtered if d.label == 'person']
    
    assert len(person_detections) > 0, "Expected YOLO to detect person in image"
    assert len(person_kept) == len(person_detections), "Expected ALL people to be KEPT (outside shutter region)"
    print(f"✅ Person test PASSED: {len(person_detections)} detected, {len(person_kept)} kept (all kept correctly)")
    
    print("\n✅ Test complete! Shutter correctly filters car but keeps people.")


if __name__ == '__main__':
    # Run test directly
    test_shutter_filters_car_keeps_person()
