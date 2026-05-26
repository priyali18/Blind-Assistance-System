"""
============================================
Module: Object Detector (YOLOv8)
============================================
Wraps Ultralytics YOLOv8 for real-time object
detection on camera frames.

Key Concepts:
    - YOLO = "You Only Look Once"
    - Processes entire image in one pass (fast!)
    - Returns bounding boxes, class labels, and
      confidence scores for every detected object
    - YOLOv8n (nano) is the fastest variant

COCO classes relevant to our project:
    person(0), chair(56), couch(57), bed(59),
    dining table(60), tv(62), laptop(63),
    bottle(39), backpack(24), suitcase(28),
    potted plant(58), dog(16), cat(15),
    cell phone(67), book(73)
============================================
"""

from ultralytics import YOLO
import time


class ObjectDetector:
    """
    YOLOv8-based object detector.

    Usage:
        detector = ObjectDetector(model_path="yolov8n.pt", confidence=0.5)
        detections = detector.detect(frame)
        # detections = [
        #   {"label": "chair", "confidence": 0.87,
        #    "bbox": (x1, y1, x2, y2)},
        #   ...
        # ]
    """

    def __init__(self, model_path="yolov8n.pt", confidence=0.5):
        """
        Load the YOLOv8 model.

        Args:
            model_path (str): Path to YOLO model weights file.
                              "yolov8n.pt" = nano (fastest)
                              "yolov8s.pt" = small (balanced)
                              "yolov8m.pt" = medium (more accurate)
            confidence (float): Minimum confidence threshold (0.0 - 1.0).
                                Detections below this are discarded.
        """
        print(f"[Detector] Loading YOLOv8 model: {model_path}")
        self.model = YOLO(model_path)
        self.confidence = confidence

        # Store class names from the model (COCO 80 classes)
        self.class_names = self.model.names  # dict {0: 'person', 1: 'bicycle', ...}
        print(f"[Detector] Model loaded ({len(self.class_names)} classes)")

    def detect(self, frame):
        """
        Run object detection on a single frame.

        Args:
            frame (numpy.ndarray): BGR image from camera (H, W, 3)

        Returns:
            list[dict]: List of detections, each containing:
                - "label" (str): Class name (e.g., "chair")
                - "confidence" (float): Detection confidence (0-1)
                - "bbox" (tuple): Bounding box as (x1, y1, x2, y2)
                    where (x1,y1) = top-left, (x2,y2) = bottom-right
                - "class_id" (int): COCO class ID number
        """
        # Run YOLOv8 inference
        # verbose=False suppresses per-frame console output
        results = self.model(frame, conf=self.confidence, verbose=False)

        detections = []

        # results[0] contains detections for the first (only) image
        if results and len(results) > 0:
            result = results[0]

            # result.boxes contains all detected bounding boxes
            if result.boxes is not None:
                for box in result.boxes:
                    # Extract bounding box coordinates (x1, y1, x2, y2)
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()

                    # Extract confidence score
                    conf = float(box.conf[0].cpu().numpy())

                    # Extract class ID and name
                    class_id = int(box.cls[0].cpu().numpy())
                    label = self.class_names.get(class_id, f"class_{class_id}")

                    detections.append({
                        "label": label,
                        "confidence": conf,
                        "bbox": (int(x1), int(y1), int(x2), int(y2)),
                        "class_id": class_id
                    })

        return detections

    def get_class_names(self):
        """Return all class names the model can detect."""
        return list(self.class_names.values())
