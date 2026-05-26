"""
============================================
Module: GPS Location
============================================
Gets the user's current location using:
  1. Windows Location API (if available)
  2. IP-based geolocation fallback (geocoder)

Provides:
  - Current latitude/longitude
  - Continuous location updates in background
  - Distance calculation between two points

Note: Laptops typically use WiFi-based positioning
which is accurate to ~50-100 meters. For precise
outdoor navigation, a USB GPS dongle or phone
GPS would be ideal.
============================================
"""

import threading
import time
import math


class GPSLocation:
    """
    Location provider with background updates.

    Usage:
        gps = GPSLocation()
        gps.start()
        lat, lng = gps.get_location()
        gps.stop()
    """

    def __init__(self, update_interval=5):
        """
        Initialize GPS location provider.

        Args:
            update_interval (float): Seconds between location updates
        """
        self.update_interval = update_interval
        self.is_running = False
        self._thread = None

        # Current position
        self._lat = None
        self._lng = None
        self._accuracy = None
        self._lock = threading.Lock()
        self._last_update = 0

        # Location method used
        self._method = "unknown"

    def start(self):
        """Start background location updates."""
        if self.is_running:
            return

        # Get initial location (blocking)
        self._update_location()

        if self._lat is not None:
            print(f"[GPS] Initial location: {self._lat:.6f}, {self._lng:.6f} ({self._method})")
        else:
            print("[GPS] WARNING: Could not get initial location")

        self.is_running = True
        self._thread = threading.Thread(
            target=self._update_loop,
            daemon=True,
            name="GPSLocationUpdater"
        )
        self._thread.start()
        print("[GPS] Background location updates started")

    def stop(self):
        """Stop background location updates."""
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        print("[GPS] Stopped")

    def get_location(self):
        """
        Get current location.

        Returns:
            tuple: (latitude, longitude) or (None, None) if unavailable
        """
        with self._lock:
            return (self._lat, self._lng)

    def get_location_info(self):
        """
        Get detailed location info.

        Returns:
            dict: Location details including lat, lng, accuracy, method
        """
        with self._lock:
            return {
                "lat": self._lat,
                "lng": self._lng,
                "accuracy": self._accuracy,
                "method": self._method,
                "last_update": self._last_update,
            }

    def _update_loop(self):
        """Background thread: periodically updates location."""
        while self.is_running:
            time.sleep(self.update_interval)
            if self.is_running:
                self._update_location()

    def _update_location(self):
        """Try to get current location using available methods."""
        # Method 1: Try geocoder (IP-based, works everywhere with internet)
        try:
            import geocoder
            g = geocoder.ip('me')
            if g.ok and g.latlng:
                with self._lock:
                    self._lat = g.latlng[0]
                    self._lng = g.latlng[1]
                    self._accuracy = 500  # IP geolocation ~500m accuracy
                    self._method = "IP-geolocation"
                    self._last_update = time.time()
                return
        except Exception:
            pass

        # Method 2: Try Windows Location API via PowerShell
        try:
            import subprocess
            ps_script = """
            Add-Type -AssemblyName System.Device
            $watcher = New-Object System.Device.Location.GeoCoordinateWatcher
            $watcher.Start()
            $timeout = 10
            $elapsed = 0
            while ($watcher.Status -ne 'Ready' -and $elapsed -lt $timeout) {
                Start-Sleep -Milliseconds 500
                $elapsed += 0.5
            }
            if ($watcher.Status -eq 'Ready') {
                $coord = $watcher.Position.Location
                Write-Output "$($coord.Latitude),$($coord.Longitude),$($coord.HorizontalAccuracy)"
            } else {
                Write-Output "FAILED"
            }
            $watcher.Stop()
            """
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True, text=True, timeout=15
            )
            output = result.stdout.strip()
            if output and output != "FAILED":
                parts = output.split(",")
                if len(parts) >= 2:
                    with self._lock:
                        self._lat = float(parts[0])
                        self._lng = float(parts[1])
                        self._accuracy = float(parts[2]) if len(parts) > 2 else 100
                        self._method = "Windows-Location-API"
                        self._last_update = time.time()
                    return
        except Exception:
            pass

    @staticmethod
    def calculate_distance(lat1, lng1, lat2, lng2):
        """
        Calculate distance between two GPS coordinates using Haversine formula.

        Args:
            lat1, lng1: First point coordinates
            lat2, lng2: Second point coordinates

        Returns:
            float: Distance in meters
        """
        R = 6371000  # Earth radius in meters

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lng2 - lng1)

        a = (math.sin(delta_phi / 2) ** 2 +
             math.cos(phi1) * math.cos(phi2) *
             math.sin(delta_lambda / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    @staticmethod
    def format_distance(meters):
        """
        Format distance for voice output.

        Args:
            meters (float): Distance in meters

        Returns:
            str: Human-readable distance string
        """
        if meters < 100:
            return f"{int(meters)} meters"
        elif meters < 1000:
            return f"{int(meters / 10) * 10} meters"  # Round to 10m
        else:
            km = meters / 1000
            return f"{km:.1f} kilometers"
