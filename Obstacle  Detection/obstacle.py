"""
============================================
Module: Obstacle Detection
============================================
Filters relevant obstacles from raw YOLO detections,
determines their screen region (left/center/right),
and estimates their distance (close/medium/far).

Key Concepts:
    - Not all detected objects are obstacles
    - Screen is divided into 3 vertical regions
    - Distance is estimated from bounding box size
    - Center + close = highest danger = STOP

This module bridges raw detection → navigation decisions.
============================================
"""


class ObstacleDetector:
    """
    Filters detections into navigation-relevant obstacles
    with position and distance information.

    Usage:
        obs = ObstacleDetector(
            obstacle_classes=["chair", "person", ...],
            frame_width=640, frame_height=480
        )
        obstacles = obs.process(detections)
        # obstacles = [
        #   {"label": "chair", "region": "CENTER",
        #    "distance": "CLOSE", "danger_level": "HIGH", ...},
        #   ...
        # ]
    """

    def __init__(self, obstacle_classes, frame_width=640, frame_height=480,
                 left_boundary=0.33, right_boundary=0.66,
                 close_threshold=0.15, medium_threshold=0.05,
                 safety_stop_threshold=0.12):
        """
        Initialize obstacle detection parameters.

        Args:
            obstacle_classes (list): Object labels considered obstacles
            frame_width (int): Camera frame width in pixels
            frame_height (int): Camera frame height in pixels
            left_boundary (float): Left/center boundary (0-1)
            right_boundary (float): Center/right boundary (0-1)
            close_threshold (float): BBox area ratio for CLOSE
            medium_threshold (float): BBox area ratio for MEDIUM
            safety_stop_threshold (float): BBox area ratio to trigger STOP
        """
        self.obstacle_classes = [c.lower() for c in obstacle_classes]
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.frame_area = frame_width * frame_height

        # Region boundaries (pixel positions)
        self.left_boundary = int(frame_width * left_boundary)
        self.right_boundary = int(frame_width * right_boundary)

        # Distance thresholds (bbox area / frame area)
        self.close_threshold = close_threshold
        self.medium_threshold = medium_threshold
        self.safety_stop_threshold = safety_stop_threshold

    def update_frame_size(self, width, height):
        """Update frame dimensions (if camera resolution changes)."""
        self.frame_width = width
        self.frame_height = height
        self.frame_area = width * height

    def _is_obstacle(self, label):
        """
        Check if a detected object is a relevant obstacle.

        Args:
            label (str): Object class name from YOLO

        Returns:
            bool: True if the object should be treated as an obstacle
        """
        return label.lower() in self.obstacle_classes

    def _get_region(self, bbox):
        """
        Determine which screen region an object is in,
        based on the CENTER of its bounding box.

        The frame is divided into 3 vertical columns:
            LEFT    |  CENTER  |  RIGHT
            0-33%   |  33-66%  |  66-100%

        Args:
            bbox (tuple): (x1, y1, x2, y2) bounding box

        Returns:
            str: "LEFT", "CENTER", or "RIGHT"
        """
        x1, y1, x2, y2 = bbox

        # Calculate center x-coordinate of the bounding box
        center_x = (x1 + x2) // 2

        if center_x < self.left_boundary:
            return "LEFT"
        elif center_x > self.right_boundary:
            return "RIGHT"
        else:
            return "CENTER"

    def _estimate_distance(self, bbox):
        """
        Estimate distance using bounding box area ratio.

        Logic:
            bbox_area / frame_area = ratio
            ratio > 15% → CLOSE (object fills large part of frame)
            ratio > 5%  → MEDIUM
            ratio <= 5% → FAR

        This works because objects appear LARGER when they
        are CLOSER to the camera.

        Args:
            bbox (tuple): (x1, y1, x2, y2) bounding box

        Returns:
            tuple: (distance_label, area_ratio)
                distance_label: "CLOSE", "MEDIUM", or "FAR"
                area_ratio: float (0-1) representing bbox coverage
        """
        x1, y1, x2, y2 = bbox

        # Calculate bounding box area
        bbox_width = x2 - x1
        bbox_height = y2 - y1
        bbox_area = bbox_width * bbox_height

        # Calculate area ratio (what fraction of the frame does the bbox cover)
        area_ratio = bbox_area / self.frame_area if self.frame_area > 0 else 0

        if area_ratio >= self.close_threshold:
            return "CLOSE", area_ratio
        elif area_ratio >= self.medium_threshold:
            return "MEDIUM", area_ratio
        else:
            return "FAR", area_ratio

    def _get_danger_level(self, region, distance):
        """
        Determine danger level from region + distance.

        Danger matrix:
                    CLOSE     MEDIUM    FAR
            CENTER: HIGH      MEDIUM    LOW
            LEFT:   MEDIUM    LOW       LOW
            RIGHT:  MEDIUM    LOW       LOW

        Args:
            region (str): "LEFT", "CENTER", or "RIGHT"
            distance (str): "CLOSE", "MEDIUM", or "FAR"

        Returns:
            str: "HIGH", "MEDIUM", or "LOW"
        """
        if region == "CENTER":
            if distance == "CLOSE":
                return "HIGH"
            elif distance == "MEDIUM":
                return "MEDIUM"
            else:
                return "LOW"
        else:  # LEFT or RIGHT
            if distance == "CLOSE":
                return "MEDIUM"
            else:
                return "LOW"

    def process(self, detections):
        """
        Process raw YOLO detections into obstacle information.

        This is the main method. It:
            1. Filters only obstacle classes
            2. Determines screen region
            3. Estimates distance
            4. Assigns danger level

        Args:
            detections (list[dict]): Raw detections from ObjectDetector

        Returns:
            list[dict]: Obstacles with added fields:
                - "region": "LEFT" / "CENTER" / "RIGHT"
                - "distance": "CLOSE" / "MEDIUM" / "FAR"
                - "area_ratio": float (0-1)
                - "danger_level": "HIGH" / "MEDIUM" / "LOW"
                - "should_stop": bool (True if immediate danger)
        """
        obstacles = []

        for det in detections:
            # Step 6: Filter — skip non-obstacle objects
            if not self._is_obstacle(det["label"]):
                continue

            bbox = det["bbox"]

            # Step 5: Determine screen region
            region = self._get_region(bbox)

            # Step 7: Estimate distance
            distance, area_ratio = self._estimate_distance(bbox)

            # Danger assessment
            danger_level = self._get_danger_level(region, distance)

            # STOP condition: object is in CENTER and area >= safety threshold
            should_stop = (
                region == "CENTER" and
                area_ratio >= self.safety_stop_threshold
            )

            obstacles.append({
                "label": det["label"],
                "confidence": det["confidence"],
                "bbox": bbox,
                "class_id": det.get("class_id", -1),
                "region": region,
                "distance": distance,
                "area_ratio": area_ratio,
                "danger_level": danger_level,
                "should_stop": should_stop,
            })

        # Sort by danger level (HIGH first) for priority processing
        danger_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        obstacles.sort(key=lambda o: danger_order.get(o["danger_level"], 3))

        return obstacles

    def get_region_boundaries(self):
        """Return region boundary pixel positions (for drawing)."""
        return self.left_boundary, self.right_boundary
