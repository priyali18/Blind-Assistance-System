"""
============================================
Module: Map Display
============================================
Generates an interactive Google Maps HTML page
showing:
  - User's current location (blue marker)
  - Destination (red marker)
  - Walking route drawn on map
  - Turn-by-turn directions panel
  - Auto-refreshing location tracking

Opens in the default browser for the caretaker
or developer to monitor navigation visually.
============================================
"""

import os
import webbrowser
import tempfile


class MapDisplay:
    """
    Generates and opens an interactive Google Maps
    route visualization in the browser.

    Usage:
        map_disp = MapDisplay(api_key="YOUR_KEY")
        map_disp.show_route(origin, destination, route_data)
        map_disp.show_nearby_places(lat, lng, places)
    """

    def __init__(self, api_key):
        """
        Initialize map display.

        Args:
            api_key (str): Google Maps JavaScript API key
        """
        self.api_key = api_key
        self._map_file = os.path.join(
            tempfile.gettempdir(), "blind_assistant_map.html"
        )

    def show_route(self, origin_lat, origin_lng, dest_lat, dest_lng,
                   dest_name="Destination", route_data=None):
        """
        Generate and open a map showing the walking route.

        Args:
            origin_lat, origin_lng: Starting coordinates
            dest_lat, dest_lng: Destination coordinates
            dest_name (str): Name of the destination
            route_data (dict): Route from GoogleMapsService.get_directions()
        """
        # Build step markers and directions list
        steps_js = ""
        directions_html = ""

        if route_data and route_data.get("steps"):
            for i, step in enumerate(route_data["steps"]):
                steps_js += f"""
                    stepMarkers.push(new google.maps.Marker({{
                        position: {{ lat: {step['start_lat']}, lng: {step['start_lng']} }},
                        map: map,
                        icon: {{
                            path: google.maps.SymbolPath.CIRCLE,
                            scale: 6,
                            fillColor: '#4285F4',
                            fillOpacity: 0.8,
                            strokeColor: '#fff',
                            strokeWeight: 2,
                        }},
                        label: {{ text: '{i+1}', color: '#fff', fontSize: '10px' }},
                        title: 'Step {i+1}'
                    }}));
                """
                directions_html += f"""
                    <div class="step {'active' if i == 0 else ''}">
                        <div class="step-num">{i+1}</div>
                        <div class="step-info">
                            <div class="step-text">{step['instruction']}</div>
                            <div class="step-dist">{step['distance']} &middot; {step['duration']}</div>
                        </div>
                    </div>
                """

            total_dist = route_data.get('total_distance', '')
            total_dur = route_data.get('total_duration', '')
        else:
            total_dist = ""
            total_dur = ""

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Blind Assistant - Navigation Map</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Arial, sans-serif; display: flex; height: 100vh; background: #1a1a2e; }}

        #map {{ flex: 1; height: 100%; }}

        #panel {{
            width: 380px;
            background: #16213e;
            color: #e0e0e0;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
        }}

        .header {{
            background: linear-gradient(135deg, #0f3460, #533483);
            padding: 20px;
            text-align: center;
        }}
        .header h1 {{ font-size: 18px; color: #fff; margin-bottom: 5px; }}
        .header .subtitle {{ font-size: 13px; color: #a0c4ff; }}

        .route-summary {{
            background: #1a1a40;
            padding: 15px 20px;
            display: flex;
            justify-content: space-around;
            border-bottom: 1px solid #333;
        }}
        .route-summary .stat {{
            text-align: center;
        }}
        .route-summary .stat .value {{
            font-size: 20px;
            font-weight: bold;
            color: #4ecca3;
        }}
        .route-summary .stat .label {{
            font-size: 11px;
            color: #888;
            margin-top: 2px;
        }}

        .dest-info {{
            padding: 15px 20px;
            background: #1a1a40;
            border-bottom: 1px solid #333;
        }}
        .dest-info .dest-name {{
            font-size: 16px;
            font-weight: bold;
            color: #fff;
        }}
        .dest-info .dest-label {{
            font-size: 11px;
            color: #888;
            margin-bottom: 3px;
        }}

        .directions-title {{
            padding: 12px 20px 8px;
            font-size: 13px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}

        .step {{
            display: flex;
            align-items: flex-start;
            padding: 12px 20px;
            border-bottom: 1px solid #222;
            transition: background 0.2s;
        }}
        .step:hover {{ background: #1a1a40; }}
        .step.active {{ background: #0f3460; border-left: 3px solid #4ecca3; }}

        .step-num {{
            min-width: 28px;
            height: 28px;
            border-radius: 50%;
            background: #333;
            color: #4ecca3;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: bold;
            margin-right: 12px;
            margin-top: 2px;
        }}
        .step.active .step-num {{ background: #4ecca3; color: #000; }}

        .step-text {{ font-size: 14px; line-height: 1.4; }}
        .step-dist {{ font-size: 12px; color: #888; margin-top: 3px; }}

        .footer {{
            margin-top: auto;
            padding: 15px 20px;
            background: #1a1a40;
            text-align: center;
            font-size: 11px;
            color: #555;
            border-top: 1px solid #333;
        }}
        .footer .live {{ color: #4ecca3; }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div id="panel">
        <div class="header">
            <h1>AI Blind Assistant</h1>
            <div class="subtitle">GPS Walking Navigation</div>
        </div>

        <div class="dest-info">
            <div class="dest-label">NAVIGATING TO</div>
            <div class="dest-name">{dest_name}</div>
        </div>

        <div class="route-summary">
            <div class="stat">
                <div class="value">{total_dist}</div>
                <div class="label">Distance</div>
            </div>
            <div class="stat">
                <div class="value">{total_dur}</div>
                <div class="label">Walking Time</div>
            </div>
            <div class="stat">
                <div class="value">{len(route_data['steps']) if route_data else 0}</div>
                <div class="label">Steps</div>
            </div>
        </div>

        <div class="directions-title">Turn-by-Turn Directions</div>
        {directions_html}

        <div class="footer">
            <span class="live">&#9679;</span> Live Navigation Active
        </div>
    </div>

    <script>
        function initMap() {{
            const origin = {{ lat: {origin_lat}, lng: {origin_lng} }};
            const destination = {{ lat: {dest_lat}, lng: {dest_lng} }};

            const map = new google.maps.Map(document.getElementById('map'), {{
                zoom: 14,
                center: origin,
                mapTypeControl: true,
                streetViewControl: false,
                styles: [
                    {{ elementType: 'geometry', stylers: [{{ color: '#242f3e' }}] }},
                    {{ elementType: 'labels.text.stroke', stylers: [{{ color: '#242f3e' }}] }},
                    {{ elementType: 'labels.text.fill', stylers: [{{ color: '#746855' }}] }},
                    {{ featureType: 'road', elementType: 'geometry', stylers: [{{ color: '#38414e' }}] }},
                    {{ featureType: 'road', elementType: 'geometry.stroke', stylers: [{{ color: '#212a37' }}] }},
                    {{ featureType: 'road', elementType: 'labels.text.fill', stylers: [{{ color: '#9ca5b3' }}] }},
                    {{ featureType: 'water', elementType: 'geometry', stylers: [{{ color: '#17263c' }}] }},
                    {{ featureType: 'poi', elementType: 'labels.text.fill', stylers: [{{ color: '#d59563' }}] }},
                ]
            }});

            // Origin marker (blue - You are here)
            new google.maps.Marker({{
                position: origin,
                map: map,
                title: 'Your Location',
                icon: {{
                    url: 'http://maps.google.com/mapfiles/ms/icons/blue-dot.png'
                }}
            }});

            // Destination marker (red)
            new google.maps.Marker({{
                position: destination,
                map: map,
                title: '{dest_name}',
                icon: {{
                    url: 'http://maps.google.com/mapfiles/ms/icons/red-dot.png'
                }}
            }});

            // Step markers
            const stepMarkers = [];
            {steps_js}

            // Draw route using Directions Service
            const directionsService = new google.maps.DirectionsService();
            const directionsRenderer = new google.maps.DirectionsRenderer({{
                map: map,
                suppressMarkers: true,
                polylineOptions: {{
                    strokeColor: '#4ecca3',
                    strokeWeight: 5,
                    strokeOpacity: 0.9,
                }}
            }});

            directionsService.route({{
                origin: origin,
                destination: destination,
                travelMode: 'WALKING',
            }}, function(response, status) {{
                if (status === 'OK') {{
                    directionsRenderer.setDirections(response);
                    // Fit map to route bounds
                    const bounds = response.routes[0].bounds;
                    map.fitBounds(bounds);
                }}
            }});
        }}
    </script>
    <script src="https://maps.googleapis.com/maps/api/js?key={self.api_key}&callback=initMap" async defer></script>
</body>
</html>"""

        self._write_and_open(html)
        print(f"[Map] Route map opened in browser: {dest_name}")

    def show_nearby_places(self, lat, lng, places, place_type_name):
        """
        Generate and open a map showing nearby places.

        Args:
            lat, lng: Center coordinates
            places (list): Places from GoogleMapsService.find_nearby_places()
            place_type_name (str): e.g., "hospital"
        """
        # Build place markers
        markers_js = ""
        places_html = ""
        colors = ['red', 'orange', 'yellow', 'green', 'purple']

        for i, place in enumerate(places):
            color = colors[i % len(colors)]
            safe_name = place["name"].replace("'", "\\'")
            markers_js += f"""
                new google.maps.Marker({{
                    position: {{ lat: {place['lat']}, lng: {place['lng']} }},
                    map: map,
                    title: '{safe_name}',
                    label: {{ text: '{i+1}', color: '#fff', fontSize: '11px', fontWeight: 'bold' }},
                    animation: google.maps.Animation.DROP,
                }});
            """
            open_status = ""
            if place.get("open_now") is True:
                open_status = '<span style="color:#4ecca3">Open Now</span>'
            elif place.get("open_now") is False:
                open_status = '<span style="color:#e74c3c">Closed</span>'

            places_html += f"""
                <div class="place" onclick="panTo({place['lat']}, {place['lng']})">
                    <div class="place-num">{i+1}</div>
                    <div class="place-info">
                        <div class="place-name">{place['name']}</div>
                        <div class="place-dist">{place['distance_text']} away {open_status}</div>
                        <div class="place-addr">{place.get('address', '')}</div>
                    </div>
                </div>
            """

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Blind Assistant - Nearby {place_type_name.title()}</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Arial, sans-serif; display: flex; height: 100vh; background: #1a1a2e; }}
        #map {{ flex: 1; height: 100%; }}
        #panel {{
            width: 380px;
            background: #16213e;
            color: #e0e0e0;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
        }}
        .header {{
            background: linear-gradient(135deg, #0f3460, #533483);
            padding: 20px;
            text-align: center;
        }}
        .header h1 {{ font-size: 18px; color: #fff; margin-bottom: 5px; }}
        .header .subtitle {{ font-size: 13px; color: #a0c4ff; }}
        .result-count {{
            padding: 12px 20px;
            background: #1a1a40;
            border-bottom: 1px solid #333;
            text-align: center;
            font-size: 14px;
        }}
        .result-count .num {{ color: #4ecca3; font-weight: bold; font-size: 22px; }}
        .places-title {{
            padding: 12px 20px 8px;
            font-size: 13px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .place {{
            display: flex;
            align-items: flex-start;
            padding: 14px 20px;
            border-bottom: 1px solid #222;
            cursor: pointer;
            transition: background 0.2s;
        }}
        .place:hover {{ background: #1a1a40; }}
        .place-num {{
            min-width: 30px;
            height: 30px;
            border-radius: 50%;
            background: #e74c3c;
            color: #fff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            font-weight: bold;
            margin-right: 12px;
        }}
        .place-name {{ font-size: 14px; font-weight: bold; color: #fff; }}
        .place-dist {{ font-size: 12px; color: #4ecca3; margin-top: 3px; }}
        .place-addr {{ font-size: 11px; color: #777; margin-top: 2px; }}
        .tip {{
            margin-top: auto;
            padding: 15px 20px;
            background: #1a1a40;
            text-align: center;
            font-size: 12px;
            color: #888;
            border-top: 1px solid #333;
        }}
        .tip em {{ color: #4ecca3; }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div id="panel">
        <div class="header">
            <h1>AI Blind Assistant</h1>
            <div class="subtitle">Nearby Places Search</div>
        </div>
        <div class="result-count">
            <div class="num">{len(places)}</div>
            {place_type_name.title()}(s) found nearby
        </div>
        <div class="places-title">Results (nearest first)</div>
        {places_html}
        <div class="tip">
            Say <em>"yes"</em> to navigate to the nearest one<br>
            or <em>"navigate to [name]"</em> for a specific place
        </div>
    </div>

    <script>
        let map;
        function panTo(lat, lng) {{
            map.panTo({{ lat: lat, lng: lng }});
            map.setZoom(16);
        }}
        function initMap() {{
            const center = {{ lat: {lat}, lng: {lng} }};
            map = new google.maps.Map(document.getElementById('map'), {{
                zoom: 14,
                center: center,
                styles: [
                    {{ elementType: 'geometry', stylers: [{{ color: '#242f3e' }}] }},
                    {{ elementType: 'labels.text.stroke', stylers: [{{ color: '#242f3e' }}] }},
                    {{ elementType: 'labels.text.fill', stylers: [{{ color: '#746855' }}] }},
                    {{ featureType: 'road', elementType: 'geometry', stylers: [{{ color: '#38414e' }}] }},
                    {{ featureType: 'road', elementType: 'geometry.stroke', stylers: [{{ color: '#212a37' }}] }},
                    {{ featureType: 'road', elementType: 'labels.text.fill', stylers: [{{ color: '#9ca5b3' }}] }},
                    {{ featureType: 'water', elementType: 'geometry', stylers: [{{ color: '#17263c' }}] }},
                ]
            }});

            // Your location (blue)
            new google.maps.Marker({{
                position: center,
                map: map,
                title: 'Your Location',
                icon: {{ url: 'http://maps.google.com/mapfiles/ms/icons/blue-dot.png' }}
            }});

            // Place markers
            {markers_js}

            // Fit bounds to show all markers
            const bounds = new google.maps.LatLngBounds();
            bounds.extend(center);
            {''.join(f"bounds.extend({{ lat: {p['lat']}, lng: {p['lng']} }});" for p in places)}
            map.fitBounds(bounds);
        }}
    </script>
    <script src="https://maps.googleapis.com/maps/api/js?key={self.api_key}&callback=initMap" async defer></script>
</body>
</html>"""

        self._write_and_open(html)
        print(f"[Map] Nearby places map opened: {len(places)} {place_type_name}(s)")

    def _write_and_open(self, html_content):
        """Write HTML to temp file and open in browser."""
        with open(self._map_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        webbrowser.open(f'file:///{self._map_file}')
