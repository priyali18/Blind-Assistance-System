"""
============================================
Module: Navigation Decision Engine
============================================
Takes processed obstacle data and produces
voice navigation instructions.

Core Logic:
    1. If obstacle in CENTER and CLOSE → STOP
    2. If obstacle in CENTER and MEDIUM → CAUTION
    3. If obstacle in LEFT → move right
    4. If obstacle in RIGHT → move left
    5. If no obstacles → path clear, move forward

Anti-Spam:
    - Cooldown timer prevents repeating the same
      instruction within SPEECH_COOLDOWN seconds
    - Priority system ensures STOP overrides all
============================================
"""

import time


class Navigator:
    """
    Navigation decision engine.

    Converts obstacle information into spoken instructions
    with cooldown logic to prevent repetitive speech.

    Usage:
        nav = Navigator(cooldown=2.0)
        instruction = nav.decide(obstacles)
        if instruction:
            speak(instruction)
    """

    # Instruction priority (lower number = higher priority)
    PRIORITY = {
        "STOP": 0,
        "CAUTION": 1,
        "MOVE_RIGHT": 2,
        "MOVE_LEFT": 3,
        "CLEAR": 4,
    }

    def __init__(self, cooldown=2.0):
        """
        Initialize navigator.

        Args:
            cooldown (float): Minimum seconds between ANY instructions.
                              Prevents rapid-fire instruction spam.
        """
        self.cooldown = cooldown

        # Track last time ANY instruction was spoken (global cooldown)
        self._last_speak_time = 0
        self.last_instruction = None  # Last instruction type returned

    def _can_speak(self, instruction_type):
        """
        Check if enough time has passed since ANY instruction was last given.

        Uses a GLOBAL cooldown — no instruction can fire until the
        cooldown from the previous one expires. STOP has a shorter
        cooldown because safety is critical.

        Args:
            instruction_type (str): e.g. "STOP", "MOVE_LEFT"

        Returns:
            bool: True if instruction can be spoken now
        """
        now = time.time()
        elapsed = now - self._last_speak_time

        # STOP gets shorter cooldown for safety
        if instruction_type == "STOP":
            return elapsed >= 1.5
        else:
            return elapsed >= self.cooldown

    def _mark_spoken(self, instruction_type):
        """Record that an instruction was just spoken."""
        self._last_speak_time = time.time()
        self.last_instruction = instruction_type

    def decide(self, obstacles):
        """
        Make a navigation decision based on current obstacles.

        This is the CORE decision logic. It processes all obstacles,
        determines the highest-priority instruction, and returns it
        only if the cooldown has expired.

        Args:
            obstacles (list[dict]): Processed obstacles from ObstacleDetector.
                Each dict has: label, region, distance, danger_level, should_stop

        Returns:
            dict or None: Navigation instruction with keys:
                - "type": Instruction type (STOP, CAUTION, MOVE_LEFT, etc.)
                - "message": Human-readable spoken message
                - "priority": Priority level (0=highest)
                - "obstacle": The obstacle that triggered it (or None)
            Returns None if no instruction needed or cooldown active.
        """
        if not obstacles:
            # No obstacles detected → path is clear
            return self._make_instruction(
                "CLEAR",
                "Path is clear. Move forward.",
                obstacle=None
            )

        # Collect all candidate instructions from all obstacles
        candidates = []

        for obs in obstacles:
            region = obs["region"]
            distance = obs["distance"]
            label = obs["label"]
            danger = obs["danger_level"]

            # ---- Rule 1: CENTER + CLOSE = STOP ----
            if obs["should_stop"] or (region == "CENTER" and distance == "CLOSE"):
                candidates.append(self._make_instruction(
                    "STOP",
                    f"Stop! {label} directly ahead.",
                    obstacle=obs
                ))

            # ---- Rule 2: CENTER + MEDIUM = CAUTION ----
            elif region == "CENTER" and distance == "MEDIUM":
                candidates.append(self._make_instruction(
                    "CAUTION",
                    f"Caution. {label} ahead. Slow down.",
                    obstacle=obs
                ))

            # ---- Rule 3: LEFT obstacle = move right ----
            elif region == "LEFT":
                if distance in ("CLOSE", "MEDIUM"):
                    candidates.append(self._make_instruction(
                        "MOVE_RIGHT",
                        f"{label} on your left. Move right.",
                        obstacle=obs
                    ))

            # ---- Rule 4: RIGHT obstacle = move left ----
            elif region == "RIGHT":
                if distance in ("CLOSE", "MEDIUM"):
                    candidates.append(self._make_instruction(
                        "MOVE_LEFT",
                        f"{label} on your right. Move left.",
                        obstacle=obs
                    ))

        # Filter out None candidates (from cooldown-blocked instructions)
        candidates = [c for c in candidates if c is not None]

        # If no actionable candidates, path is effectively clear
        if not candidates:
            return self._make_instruction(
                "CLEAR",
                "Path is clear. Move forward.",
                obstacle=None
            )

        # Pick highest priority instruction (lowest priority number)
        candidates.sort(key=lambda c: c["priority"])
        best = candidates[0]

        return best

    def _make_instruction(self, inst_type, message, obstacle=None):
        """
        Create a navigation instruction dict.

        Args:
            inst_type (str): STOP, CAUTION, MOVE_LEFT, MOVE_RIGHT, CLEAR
            message (str): Human-readable message to speak
            obstacle (dict or None): The obstacle that triggered this

        Returns:
            dict: Instruction with type, message, priority, obstacle
        """
        # Apply cooldown for CLEAR too (avoid constant "path is clear")
        if not self._can_speak(inst_type):
            return None

        self._mark_spoken(inst_type)

        return {
            "type": inst_type,
            "message": message,
            "priority": self.PRIORITY.get(inst_type, 99),
            "obstacle": obstacle,
        }

    def reset(self):
        """Reset all cooldown timers (e.g. when restarting navigation)."""
        self._last_speak_time = 0
        self.last_instruction = None
