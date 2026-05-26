"""
============================================
Module: Visual + Geospatial Sensor Fusion
         Navigation System
============================================
Combines two navigation layers in real-time:

  GLOBAL LAYER (GPS + Maps):
    - Route planning via Directions API
    - Turn-by-turn step tracking
    - Off-route detection & recalculation

  LOCAL LAYER (Camera + YOLO):
    - Real-time obstacle detection
    - Walkable path assessment
    - Immediate safety decisions

FUSION LOGIC:
    1. If obstacle detected → OVERRIDE map instruction
       Speak obstacle warning (highest priority)
    2. After obstacle cleared → RESUME map direction
       "Now continue: [next map instruction]"
    3. If path is clear → follow map direction
       "Walk straight for 50 meters"
    4. If no GPS nav active → camera-only mode
       Standard indoor obstacle navigation

PRIORITY SYSTEM:
    Priority 0: EMERGENCY (Stop! Vehicle ahead)
    Priority 1: OBSTACLE (Move left/right)
    Priority 2: DIRECTION (Turn right in 20 meters)
    Priority 3: INFO (Path is clear / Arrived)

This implements a "Visual + Geospatial Sensor Fusion
Navigation System" — the camera acts as the local
safety layer while GPS provides global route guidance.
============================================
"""

import time
import threading


class NavigationFusion:
    """
    Fuses camera-based obstacle detection with GPS navigation.

    Acts as the central brain that decides what to tell the user
    at any given moment, combining both safety (camera) and
    direction (GPS) information.

    The system behaves like a human guide walking with the user:
    - Keeps them safe from obstacles (camera)
    - Guides them to their destination (GPS)
    - Speaks only the most important information
    """

    # Message priorities (lower = more urgent)
    PRIORITY_EMERGENCY = 0    # STOP - immediate danger
    PRIORITY_OBSTACLE = 1     # Move left/right - obstacle avoidance
    PRIORITY_DIRECTION = 2    # Map turn instructions
    PRIORITY_INFO = 3         # Path clear, general info

    # Fusion states
    STATE_IDLE = "IDLE"
    STATE_CAMERA_ONLY = "CAMERA_ONLY"       # Indoor nav, no GPS
    STATE_GPS_ONLY = "GPS_ONLY"             # GPS nav, no obstacles
    STATE_FUSED = "FUSED"                   # Both active, fusing

    # Obstacle states for fusion logic
    OBS_CLEAR = "CLEAR"
    OBS_DETECTED = "DETECTED"
    OBS_AVOIDING = "AVOIDING"
    OBS_RESUMED = "RESUMED"

    def __init__(self, navigator, outdoor_navigator, voice_output,
                 obstacle_cooldown=2.0, direction_cooldown=8.0,
                 resume_cooldown=3.0):
        """
        Initialize sensor fusion engine.

        Args:
            navigator: Indoor Navigator (camera obstacle decisions)
            outdoor_navigator: OutdoorNavigator (GPS route tracking)
            voice_output: VoiceOutput instance for speaking
            obstacle_cooldown (float): Min seconds between obstacle warnings
            direction_cooldown (float): Min seconds between direction reminders
            resume_cooldown (float): Seconds after obstacle clear to resume direction
        """
        self.navigator = navigator
        self.outdoor_nav = outdoor_navigator
        self.voice = voice_output

        # Timing controls
        self.obstacle_cooldown = obstacle_cooldown
        self.direction_cooldown = direction_cooldown
        self.resume_cooldown = resume_cooldown

        # State tracking
        self.state = self.STATE_IDLE
        self._obstacle_state = self.OBS_CLEAR
        self._last_obstacle_time = 0
        self._last_direction_time = 0
        self._last_resume_time = 0
        self._last_clear_time = 0
        self._obstacle_override_active = False

        # Current instructions from each layer
        self._current_map_instruction = None   # Latest GPS step instruction
        self._current_camera_instruction = None # Latest camera decision
        self._last_spoken_message = ""
        self._last_spoken_time = 0

        # Thread safety
        self._lock = threading.Lock()

        # Stats for display
        self.stats = {
            "obstacle_overrides": 0,
            "direction_announcements": 0,
            "resumes_after_obstacle": 0,
            "total_fused_decisions": 0,
        }

    def update_state(self):
        """Update fusion state based on what's currently active."""
        gps_active = (self.outdoor_nav.state ==
                      self.outdoor_nav.STATE_NAVIGATING)
        # Camera is always active when system is running

        if gps_active:
            if self._obstacle_override_active:
                self.state = self.STATE_FUSED
            else:
                self.state = self.STATE_GPS_ONLY
        else:
            self.state = self.STATE_CAMERA_ONLY

    def fuse(self, obstacles):
        """
        CORE FUSION LOGIC: Combine camera obstacles with GPS direction.

        This is called every frame (or every N frames) with the current
        obstacle detections from the camera.

        Decision Matrix:
        ┌────────────────────┬──────────────┬────────────────────────────┐
        │ Camera Status      │ GPS Active?  │ Action                     │
        ├────────────────────┼──────────────┼────────────────────────────┤
        │ STOP (emergency)   │ Yes/No       │ Speak STOP immediately     │
        │ OBSTACLE detected  │ Yes          │ Override GPS, speak avoid  │
        │ OBSTACLE detected  │ No           │ Speak camera instruction   │
        │ CLEAR              │ Yes          │ Resume/speak GPS direction │
        │ CLEAR              │ No           │ Speak "path clear"         │
        └────────────────────┴──────────────┴────────────────────────────┘

        Args:
            obstacles (list[dict]): Processed obstacles from ObstacleDetector

        Returns:
            dict or None: Fused instruction to speak, with keys:
                - "type": Instruction type
                - "message": What to say
                - "priority": Priority level
                - "source": "camera", "gps", "fused"
                - "obstacle": Triggering obstacle (or None)
        """
        with self._lock:
            self.update_state()
            self.stats["total_fused_decisions"] += 1
            now = time.time()

            gps_active = (self.outdoor_nav.state ==
                          self.outdoor_nav.STATE_NAVIGATING)

            # Get camera decision
            camera_decision = self._get_camera_decision(obstacles)

            # ============================
            # CASE 1: EMERGENCY (STOP)
            # ============================
            if camera_decision and camera_decision["type"] == "STOP":
                if now - self._last_obstacle_time >= 1.5:  # Short cooldown for safety
                    self._obstacle_override_active = True
                    self._obstacle_state = self.OBS_DETECTED
                    self._last_obstacle_time = now
                    self.stats["obstacle_overrides"] += 1
                    return self._make_fused_instruction(
                        "STOP",
                        camera_decision["message"],
                        self.PRIORITY_EMERGENCY,
                        source="camera",
                        obstacle=camera_decision.get("obstacle")
                    )

            # ============================
            # CASE 2: OBSTACLE AVOIDANCE
            # ============================
            if camera_decision and camera_decision["type"] in ("MOVE_LEFT", "MOVE_RIGHT", "CAUTION"):
                if now - self._last_obstacle_time >= self.obstacle_cooldown:
                    self._obstacle_override_active = True
                    self._obstacle_state = self.OBS_AVOIDING
                    self._last_obstacle_time = now
                    self.stats["obstacle_overrides"] += 1

                    # If GPS is active, combine with context
                    if gps_active:
                        msg = camera_decision["message"]
                        return self._make_fused_instruction(
                            camera_decision["type"],
                            msg,
                            self.PRIORITY_OBSTACLE,
                            source="fused",
                            obstacle=camera_decision.get("obstacle")
                        )
                    else:
                        return self._make_fused_instruction(
                            camera_decision["type"],
                            camera_decision["message"],
                            self.PRIORITY_OBSTACLE,
                            source="camera",
                            obstacle=camera_decision.get("obstacle")
                        )

            # ============================
            # CASE 3: PATH CLEAR
            # ============================
            if camera_decision and camera_decision["type"] == "CLEAR":
                self._last_clear_time = now

                # Was an obstacle being avoided? → RESUME map direction
                if self._obstacle_override_active and gps_active:
                    if now - self._last_resume_time >= self.resume_cooldown:
                        self._obstacle_override_active = False
                        self._obstacle_state = self.OBS_RESUMED
                        self._last_resume_time = now
                        self.stats["resumes_after_obstacle"] += 1

                        # Get current GPS step and resume
                        gps_msg = self._get_current_gps_instruction()
                        if gps_msg:
                            resume_msg = f"Path clear. Now continue: {gps_msg}"
                            return self._make_fused_instruction(
                                "RESUME",
                                resume_msg,
                                self.PRIORITY_DIRECTION,
                                source="fused"
                            )
                        else:
                            return self._make_fused_instruction(
                                "CLEAR",
                                "Path is clear. Continue walking.",
                                self.PRIORITY_INFO,
                                source="camera"
                            )

                # GPS active, no obstacle override → give direction reminder
                elif gps_active:
                    if now - self._last_direction_time >= self.direction_cooldown:
                        gps_msg = self._get_current_gps_instruction()
                        if gps_msg:
                            self._last_direction_time = now
                            self.stats["direction_announcements"] += 1
                            return self._make_fused_instruction(
                                "DIRECTION",
                                gps_msg,
                                self.PRIORITY_DIRECTION,
                                source="gps"
                            )

                # No GPS active → standard camera-only "path clear"
                else:
                    if now - self._last_direction_time >= self.obstacle_cooldown:
                        self._obstacle_override_active = False
                        self._obstacle_state = self.OBS_CLEAR
                        self._last_direction_time = now
                        return self._make_fused_instruction(
                            "CLEAR",
                            "Path is clear. Move forward.",
                            self.PRIORITY_INFO,
                            source="camera"
                        )

            return None  # Nothing to say right now

    def _get_camera_decision(self, obstacles):
        """
        Get raw camera navigation decision without cooldown
        (we manage cooldown ourselves in the fusion logic).
        """
        if not obstacles:
            return {
                "type": "CLEAR",
                "message": "Path is clear. Move forward.",
                "priority": 4,
                "obstacle": None
            }

        # Find highest priority obstacle situation
        candidates = []

        for obs in obstacles:
            region = obs["region"]
            distance = obs["distance"]
            label = obs["label"]

            if obs["should_stop"] or (region == "CENTER" and distance == "CLOSE"):
                candidates.append({
                    "type": "STOP",
                    "message": f"Stop! {label} directly ahead.",
                    "priority": 0,
                    "obstacle": obs
                })
            elif region == "CENTER" and distance == "MEDIUM":
                candidates.append({
                    "type": "CAUTION",
                    "message": f"Caution. {label} ahead. Slow down.",
                    "priority": 1,
                    "obstacle": obs
                })
            elif region == "LEFT" and distance in ("CLOSE", "MEDIUM"):
                candidates.append({
                    "type": "MOVE_RIGHT",
                    "message": f"{label} on your left. Move right.",
                    "priority": 2,
                    "obstacle": obs
                })
            elif region == "RIGHT" and distance in ("CLOSE", "MEDIUM"):
                candidates.append({
                    "type": "MOVE_LEFT",
                    "message": f"{label} on your right. Move left.",
                    "priority": 2,
                    "obstacle": obs
                })

        if not candidates:
            return {
                "type": "CLEAR",
                "message": "Path is clear. Move forward.",
                "priority": 4,
                "obstacle": None
            }

        candidates.sort(key=lambda c: c["priority"])
        return candidates[0]

    def _get_current_gps_instruction(self):
        """
        Get the current GPS map instruction as a voice message.

        Returns:
            str or None: Current step instruction
        """
        if self.outdoor_nav.state != self.outdoor_nav.STATE_NAVIGATING:
            return None
        if not self.outdoor_nav._route or not self.outdoor_nav._route.get("steps"):
            return None

        steps = self.outdoor_nav._route["steps"]
        step_idx = self.outdoor_nav._current_step

        if step_idx >= len(steps):
            return None

        step = steps[step_idx]
        instruction = step.get("instruction", "")
        distance = step.get("distance", "")

        if distance:
            return f"{instruction} for {distance}."
        return f"{instruction}."

    def _make_fused_instruction(self, inst_type, message, priority,
                                source="fused", obstacle=None):
        """Create a fused navigation instruction."""
        self._last_spoken_message = message
        self._last_spoken_time = time.time()

        return {
            "type": inst_type,
            "message": message,
            "priority": priority,
            "source": source,
            "obstacle": obstacle,
        }

    def get_fusion_status(self):
        """
        Get human-readable fusion status for display/debugging.

        Returns:
            dict: Current fusion state info
        """
        return {
            "state": self.state,
            "obstacle_state": self._obstacle_state,
            "override_active": self._obstacle_override_active,
            "gps_active": (self.outdoor_nav.state ==
                           self.outdoor_nav.STATE_NAVIGATING),
            "stats": self.stats.copy(),
        }

    def get_fusion_status_voice(self):
        """Get voice-ready status of the fusion system."""
        if self.state == self.STATE_FUSED:
            return (
                "Sensor fusion active. Camera and GPS working together. "
                f"Obstacle overrides: {self.stats['obstacle_overrides']}. "
                f"Route directions given: {self.stats['direction_announcements']}."
            )
        elif self.state == self.STATE_GPS_ONLY:
            return "GPS navigation active. Camera monitoring for obstacles."
        elif self.state == self.STATE_CAMERA_ONLY:
            return "Camera obstacle detection active. No GPS route."
        else:
            return "Navigation system idle."

    def reset(self):
        """Reset all fusion state."""
        with self._lock:
            self.state = self.STATE_IDLE
            self._obstacle_state = self.OBS_CLEAR
            self._last_obstacle_time = 0
            self._last_direction_time = 0
            self._last_resume_time = 0
            self._last_clear_time = 0
            self._obstacle_override_active = False
            self._current_map_instruction = None
            self._current_camera_instruction = None
            self._last_spoken_message = ""
            self._last_spoken_time = 0
