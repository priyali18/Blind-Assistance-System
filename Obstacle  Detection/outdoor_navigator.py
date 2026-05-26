"""
============================================
Module: Outdoor GPS Navigator
============================================
Manages outdoor walking navigation with:
  - Turn-by-turn voice guidance
  - Real-time position tracking
  - Off-route detection and recalculation
  - Step-by-step instruction announcements

Integrates GPS location + Google Maps APIs
to provide a fully voice-controlled outdoor
navigation experience for blind users.
============================================
"""

import threading
import time
import math


class OutdoorNavigator:
    """
    GPS-based outdoor walking navigator.

    Manages the navigation state machine:
    IDLE → SEARCHING → NAVIGATING → ARRIVED / IDLE

    Usage:
        nav = OutdoorNavigator(gps, maps, voice)
        nav.find_nearby("hospital")
        nav.navigate_to_nearest()
        nav.navigate_to_place("railway station")
    """

    # Navigator states
    STATE_IDLE = "IDLE"
    STATE_SEARCHING = "SEARCHING"
    STATE_NAVIGATING = "NAVIGATING"
    STATE_ARRIVED = "ARRIVED"

    def __init__(self, gps, maps_service, voice_output,
                 place_types=None,
                 off_track_threshold=50,
                 step_announce_distance=30,
                 update_interval=5):
        """
        Initialize outdoor navigator.

        Args:
            gps: GPSLocation instance
            maps_service: GoogleMapsService instance
            voice_output: VoiceOutput instance
            place_types (dict): Mapping of spoken names to Google place types
            off_track_threshold (float): Meters off-route before recalculating
            step_announce_distance (float): Meters before turn to announce
            update_interval (float): Seconds between position checks
        """
        self.gps = gps
        self.maps = maps_service
        self.voice = voice_output
        self.place_types = place_types or {}
        self.off_track_threshold = off_track_threshold
        self.step_announce_distance = step_announce_distance
        self.update_interval = update_interval

        # Navigation state
        self.state = self.STATE_IDLE
        self._route = None            # Current route from Directions API
        self._current_step = 0        # Current step index in route
        self._last_places = []        # Last search results
        self._last_place_type = ""    # Last searched place type name
        self._nav_thread = None
        self._lock = threading.Lock()

        # Destination info
        self._dest_name = None
        self._dest_lat = None
        self._dest_lng = None

    # ==========================================
    # Voice Command Handlers
    # ==========================================

    def find_nearby(self, spoken_place_type):
        """
        Find nearby places based on voice command.
        E.g., "find nearby hospital" → searches Google Places API.

        Args:
            spoken_place_type (str): What the user said (e.g., "hospital", "atm")

        Returns:
            str: Voice response to speak
        """
        lat, lng = self.gps.get_location()
        if lat is None:
            return "Cannot determine your location. Please check GPS."

        # Map spoken type to Google place type
        google_type = self.place_types.get(spoken_place_type.lower())
        if not google_type:
            # Try using the spoken text directly as keyword search
            google_type = spoken_place_type.lower()

        self.state = self.STATE_SEARCHING
        print(f"[OutdoorNav] Searching for '{spoken_place_type}' near {lat:.4f},{lng:.4f}")

        places = self.maps.find_nearby_places(lat, lng, google_type, keyword=spoken_place_type)
        self._last_places = places
        self._last_place_type = spoken_place_type

        self.state = self.STATE_IDLE

        response = self.maps.format_places_for_voice(places, spoken_place_type)
        print(f"[OutdoorNav] Found {len(places)} results")
        return response

    def navigate_to_nearest(self):
        """
        Navigate to the nearest place from the last search.

        Returns:
            str: Voice response to speak
        """
        if not self._last_places:
            return "No places found from previous search. Say find nearby something first."

        nearest = self._last_places[0]
        return self._start_navigation(
            nearest["lat"], nearest["lng"], nearest["name"]
        )

    def navigate_to_place(self, place_query):
        """
        Navigate to a specific place by name.
        E.g., "navigate to railway station"

        Args:
            place_query (str): Place name to navigate to

        Returns:
            str: Voice response to speak
        """
        lat, lng = self.gps.get_location()
        if lat is None:
            return "Cannot determine your location. Please check GPS."

        # First try as a nearby place type
        google_type = self.place_types.get(place_query.lower())
        if google_type:
            places = self.maps.find_nearby_places(lat, lng, google_type, keyword=place_query)
            if places:
                nearest = places[0]
                return self._start_navigation(
                    nearest["lat"], nearest["lng"], nearest["name"]
                )

        # Then try text search
        result = self.maps.text_search_place(place_query, lat, lng)
        if result:
            return self._start_navigation(
                result["lat"], result["lng"], result["name"]
            )

        # Then try geocoding
        result = self.maps.geocode_address(place_query)
        if result:
            return self._start_navigation(
                result["lat"], result["lng"], result["formatted_address"]
            )

        return f"Sorry, could not find {place_query}. Try a different name."

    def stop_navigation(self):
        """
        Stop current navigation.

        Returns:
            str: Voice response
        """
        if self.state == self.STATE_NAVIGATING:
            self.state = self.STATE_IDLE
            self._route = None
            self._current_step = 0
            print("[OutdoorNav] Navigation stopped by user")
            return "Navigation stopped."
        return "No navigation is active."

    # ==========================================
    # Navigation Engine
    # ==========================================

    def _start_navigation(self, dest_lat, dest_lng, dest_name):
        """
        Start navigating to a destination.

        Args:
            dest_lat, dest_lng: Destination coordinates
            dest_name: Name of destination

        Returns:
            str: Voice announcement for route start
        """
        lat, lng = self.gps.get_location()
        if lat is None:
            return "Cannot determine your location."

        print(f"[OutdoorNav] Getting directions to {dest_name}")

        route = self.maps.get_directions(lat, lng, dest_lat, dest_lng, dest_name)
        if not route:
            return f"Sorry, could not find a walking route to {dest_name}."

        self._route = route
        self._current_step = 0
        self._dest_name = dest_name
        self._dest_lat = dest_lat
        self._dest_lng = dest_lng
        self.state = self.STATE_NAVIGATING

        # Start the navigation tracking thread
        if self._nav_thread and self._nav_thread.is_alive():
            pass  # Already running
        else:
            self._nav_thread = threading.Thread(
                target=self._navigation_loop,
                daemon=True,
                name="OutdoorNavTracker"
            )
            self._nav_thread.start()

        announcement = self.maps.format_route_start_for_voice(route)
        print(f"[OutdoorNav] Navigation started: {route['total_distance']} / {route['total_duration']}")
        return announcement

    def _navigation_loop(self):
        """
        Background thread: tracks position and announces turns.
        Runs while state is NAVIGATING.
        """
        last_step_announced = -1

        while self.state == self.STATE_NAVIGATING:
            time.sleep(self.update_interval)

            if self.state != self.STATE_NAVIGATING:
                break

            lat, lng = self.gps.get_location()
            if lat is None:
                self.voice.speak("GPS signal lost. Trying to reconnect.")
                continue

            route = self._route
            if not route or not route["steps"]:
                break

            # Check if we've arrived at destination
            dist_to_dest = self.gps.calculate_distance(
                lat, lng, self._dest_lat, self._dest_lng
            )
            if dist_to_dest < 30:  # Within 30 meters of destination
                self.state = self.STATE_ARRIVED
                self.voice.speak(
                    f"You have arrived at {self._dest_name}. Navigation complete."
                )
                print(f"[OutdoorNav] ARRIVED at {self._dest_name}")
                self.state = self.STATE_IDLE
                break

            # Find the closest step to current position
            current_step = self._find_current_step(lat, lng, route["steps"])

            if current_step != last_step_announced and current_step < len(route["steps"]):
                step = route["steps"][current_step]
                total = len(route["steps"])
                announcement = self.maps.format_step_for_voice(step, current_step + 1, total)
                self.voice.speak(announcement)
                print(f"[OutdoorNav] Step {current_step + 1}/{total}: {step['instruction']}")
                last_step_announced = current_step
                self._current_step = current_step

            # Check if off-route
            min_dist = self._distance_to_route(lat, lng, route["steps"])
            if min_dist > self.off_track_threshold:
                self.voice.speak("You are off track. Recalculating route.")
                print(f"[OutdoorNav] Off track by {min_dist:.0f}m, recalculating...")
                # Recalculate route
                new_route = self.maps.get_directions(
                    lat, lng, self._dest_lat, self._dest_lng, self._dest_name
                )
                if new_route:
                    self._route = new_route
                    self._current_step = 0
                    last_step_announced = -1
                    step = new_route["steps"][0]
                    self.voice.speak(
                        f"New route calculated. {step['instruction']} for {step['distance']}."
                    )

        print("[OutdoorNav] Navigation loop ended")

    def _find_current_step(self, lat, lng, steps):
        """
        Find which step the user is closest to.

        Args:
            lat, lng: Current position
            steps: List of route steps

        Returns:
            int: Index of the current step
        """
        min_dist = float('inf')
        closest_step = self._current_step

        # Only search from current step forward (don't go backwards)
        for i in range(self._current_step, len(steps)):
            step = steps[i]
            dist = self.gps.calculate_distance(
                lat, lng, step["start_lat"], step["start_lng"]
            )
            if dist < min_dist:
                min_dist = dist
                closest_step = i

            # Also check end point of step
            dist_end = self.gps.calculate_distance(
                lat, lng, step["end_lat"], step["end_lng"]
            )
            if dist_end < min_dist:
                min_dist = dist_end
                closest_step = i + 1  # Move to next step

        return min(closest_step, len(steps) - 1)

    def _distance_to_route(self, lat, lng, steps):
        """
        Calculate minimum distance from current position to any step point.

        Returns:
            float: Minimum distance in meters
        """
        min_dist = float('inf')
        for step in steps:
            dist = self.gps.calculate_distance(
                lat, lng, step["start_lat"], step["start_lng"]
            )
            min_dist = min(min_dist, dist)
        return min_dist

    # ==========================================
    # Status
    # ==========================================

    def get_status(self):
        """Get current navigation status."""
        with self._lock:
            info = {
                "state": self.state,
                "destination": self._dest_name,
                "current_step": self._current_step,
                "total_steps": len(self._route["steps"]) if self._route else 0,
            }
            if self._route:
                info["total_distance"] = self._route["total_distance"]
                info["total_duration"] = self._route["total_duration"]
            return info

    def get_status_voice(self):
        """
        Get navigation status as a voice message.

        Returns:
            str: Voice-ready status
        """
        if self.state == self.STATE_IDLE:
            return "No outdoor navigation active."
        elif self.state == self.STATE_SEARCHING:
            return "Searching for places."
        elif self.state == self.STATE_NAVIGATING:
            step = self._current_step + 1
            total = len(self._route["steps"]) if self._route else 0
            return (
                f"Navigating to {self._dest_name}. "
                f"On step {step} of {total}. "
                f"Total distance is {self._route['total_distance']}."
            )
        elif self.state == self.STATE_ARRIVED:
            return f"You have arrived at {self._dest_name}."
        return "Unknown status."
