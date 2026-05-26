"""
============================================
Module: Google Maps Platform
============================================
Integrates Google Maps APIs for outdoor navigation:
  - Places API: Find nearby hospitals, ATMs, etc.
  - Directions API: Get walking route with steps
  - Geocoding API: Convert address to coordinates

All responses are formatted for voice output
(short, clear sentences for blind users).
============================================
"""

import requests
import time


class GoogleMapsService:
    """
    Google Maps API client for blind navigation.

    Usage:
        maps = GoogleMapsService(api_key="YOUR_KEY")
        places = maps.find_nearby_places(lat, lng, "hospital")
        route = maps.get_directions(origin_lat, origin_lng, dest_lat, dest_lng)
    """

    BASE_PLACES_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    BASE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
    BASE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
    BASE_PLACE_TEXT_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"

    def __init__(self, api_key, search_radius=1000, max_results=5):
        """
        Initialize Google Maps service.

        Args:
            api_key (str): Google Maps Platform API key
            search_radius (int): Default search radius in meters
            max_results (int): Max places to return
        """
        self.api_key = api_key
        self.search_radius = search_radius
        self.max_results = max_results

        if not api_key:
            print("[Maps] WARNING: No Google Maps API key set!")
            print("[Maps] Set GOOGLE_MAPS_API_KEY in your .env file")

    def is_available(self):
        """Check if API key is configured."""
        return bool(self.api_key)

    # ==========================================
    # Places API
    # ==========================================

    def find_nearby_places(self, lat, lng, place_type, keyword=None):
        """
        Find nearby places using Google Places API.

        Args:
            lat (float): Latitude
            lng (float): Longitude
            place_type (str): Google place type (e.g., "hospital", "atm")
            keyword (str): Optional keyword to refine search

        Returns:
            list[dict]: List of places with name, distance, address, lat, lng
                        Sorted by distance (nearest first)
        """
        if not self.api_key:
            return []

        try:
            params = {
                "location": f"{lat},{lng}",
                "radius": self.search_radius,
                "type": place_type,
                "key": self.api_key,
            }
            if keyword:
                params["keyword"] = keyword

            response = requests.get(self.BASE_PLACES_URL, params=params, timeout=10)
            data = response.json()

            if data.get("status") != "OK":
                error = data.get("status", "UNKNOWN")
                print(f"[Maps] Places API error: {error}")
                if data.get("error_message"):
                    print(f"[Maps] Detail: {data['error_message']}")
                return []

            places = []
            for result in data.get("results", [])[:self.max_results]:
                place_lat = result["geometry"]["location"]["lat"]
                place_lng = result["geometry"]["location"]["lng"]

                # Calculate distance
                from modules.gps_location import GPSLocation
                distance = GPSLocation.calculate_distance(lat, lng, place_lat, place_lng)

                places.append({
                    "name": result.get("name", "Unknown"),
                    "address": result.get("vicinity", ""),
                    "lat": place_lat,
                    "lng": place_lng,
                    "distance": distance,
                    "distance_text": GPSLocation.format_distance(distance),
                    "rating": result.get("rating", 0),
                    "open_now": result.get("opening_hours", {}).get("open_now", None),
                    "place_id": result.get("place_id", ""),
                })

            # Sort by distance
            places.sort(key=lambda p: p["distance"])
            return places

        except requests.Timeout:
            print("[Maps] Places API timeout")
            return []
        except Exception as e:
            print(f"[Maps] Places API error: {e}")
            return []

    def format_places_for_voice(self, places, place_type_name):
        """
        Format places list into voice-friendly sentences.

        Args:
            places (list): Places from find_nearby_places()
            place_type_name (str): Human name like "hospital", "ATM"

        Returns:
            str: Voice-ready text
        """
        if not places:
            return f"Sorry, no {place_type_name} found nearby."

        count = len(places)
        nearest = places[0]

        lines = [f"{count} {place_type_name}{'s' if count > 1 else ''} found nearby."]
        lines.append(f"The closest is {nearest['name']}, {nearest['distance_text']} away.")

        if count > 1:
            lines.append(f"Second closest is {places[1]['name']}, {places[1]['distance_text']} away.")

        lines.append(f"Say 'navigate to {place_type_name}' to get directions to the closest one.")

        return " ".join(lines)

    # ==========================================
    # Directions API
    # ==========================================

    def get_directions(self, origin_lat, origin_lng, dest_lat, dest_lng,
                       dest_name=None, mode="walking"):
        """
        Get walking directions from origin to destination.

        Args:
            origin_lat, origin_lng: Starting point
            dest_lat, dest_lng: Destination point
            dest_name (str): Name of destination for announcements
            mode (str): Travel mode ("walking", "driving", "transit")

        Returns:
            dict: Route info with steps, duration, distance, polyline
                  or None if no route found
        """
        if not self.api_key:
            return None

        try:
            params = {
                "origin": f"{origin_lat},{origin_lng}",
                "destination": f"{dest_lat},{dest_lng}",
                "mode": mode,
                "key": self.api_key,
            }

            response = requests.get(self.BASE_DIRECTIONS_URL, params=params, timeout=10)
            data = response.json()

            if data.get("status") != "OK":
                print(f"[Maps] Directions API: {data.get('status')}")
                return None

            route = data["routes"][0]
            leg = route["legs"][0]

            # Parse steps into simple instructions
            steps = []
            for step in leg["steps"]:
                # Remove HTML tags from instructions
                instruction = step["html_instructions"]
                instruction = instruction.replace("<b>", "").replace("</b>", "")
                instruction = instruction.replace("<div>", ". ").replace("</div>", "")
                instruction = instruction.replace("<wbr/>", "")
                # Remove any remaining HTML tags
                import re
                instruction = re.sub(r'<[^>]+>', '', instruction)

                steps.append({
                    "instruction": instruction,
                    "distance": step["distance"]["text"],
                    "distance_meters": step["distance"]["value"],
                    "duration": step["duration"]["text"],
                    "start_lat": step["start_location"]["lat"],
                    "start_lng": step["start_location"]["lng"],
                    "end_lat": step["end_location"]["lat"],
                    "end_lng": step["end_location"]["lng"],
                    "maneuver": step.get("maneuver", "straight"),
                })

            return {
                "dest_name": dest_name or leg["end_address"],
                "total_distance": leg["distance"]["text"],
                "total_distance_meters": leg["distance"]["value"],
                "total_duration": leg["duration"]["text"],
                "total_duration_seconds": leg["duration"]["value"],
                "steps": steps,
                "start_address": leg["start_address"],
                "end_address": leg["end_address"],
            }

        except requests.Timeout:
            print("[Maps] Directions API timeout")
            return None
        except Exception as e:
            print(f"[Maps] Directions API error: {e}")
            return None

    def format_route_start_for_voice(self, route):
        """
        Format the start of navigation for voice.

        Returns:
            str: Voice-ready announcement
        """
        if not route:
            return "Sorry, could not find a walking route."

        return (
            f"Starting navigation to {route['dest_name']}. "
            f"Total distance is {route['total_distance']}. "
            f"Estimated walking time is {route['total_duration']}. "
            f"{route['steps'][0]['instruction']} for {route['steps'][0]['distance']}."
        )

    def format_step_for_voice(self, step, step_num, total_steps):
        """
        Format a single navigation step for voice.

        Returns:
            str: Voice-ready instruction
        """
        return f"Step {step_num} of {total_steps}. {step['instruction']}. {step['distance']}."

    # ==========================================
    # Geocoding API
    # ==========================================

    def geocode_address(self, address):
        """
        Convert an address/place name to coordinates.

        Args:
            address (str): Address or place name

        Returns:
            dict: {lat, lng, formatted_address} or None
        """
        if not self.api_key:
            return None

        try:
            params = {
                "address": address,
                "key": self.api_key,
            }

            response = requests.get(self.BASE_GEOCODE_URL, params=params, timeout=10)
            data = response.json()

            if data.get("status") != "OK" or not data.get("results"):
                return None

            result = data["results"][0]
            return {
                "lat": result["geometry"]["location"]["lat"],
                "lng": result["geometry"]["location"]["lng"],
                "formatted_address": result["formatted_address"],
            }

        except Exception as e:
            print(f"[Maps] Geocoding error: {e}")
            return None

    def text_search_place(self, query, lat=None, lng=None):
        """
        Search for a place by text query (more flexible than Places nearby).

        Args:
            query (str): Search query like "AIIMS Hospital Delhi"
            lat, lng: Optional location bias

        Returns:
            dict: {name, lat, lng, address} or None
        """
        if not self.api_key:
            return None

        try:
            params = {
                "query": query,
                "key": self.api_key,
            }
            if lat and lng:
                params["location"] = f"{lat},{lng}"
                params["radius"] = 5000  # 5km bias

            response = requests.get(self.BASE_PLACE_TEXT_URL, params=params, timeout=10)
            data = response.json()

            if data.get("status") != "OK" or not data.get("results"):
                return None

            result = data["results"][0]
            return {
                "name": result.get("name", query),
                "lat": result["geometry"]["location"]["lat"],
                "lng": result["geometry"]["location"]["lng"],
                "address": result.get("formatted_address", ""),
            }

        except Exception as e:
            print(f"[Maps] Text search error: {e}")
            return None
