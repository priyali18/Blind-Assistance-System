# map_server.py
# Serves a live Leaflet map + Google Street View at http://localhost:8001
# Auto-updates user position and street view every 2 seconds

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared state
map_state = {
    "lat": 21.04617,
    "lng": 79.06136,
    "places": [],
    "last_query": None,
    "status": "Waiting...",
    "navigation": {
        "is_active": False,
        "destination": None,
        "dest_lat": None,
        "dest_lng": None,
        "steps": [],
        "current_step_index": 0
    }
}

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

@app.get("/state")
async def get_state():
    return JSONResponse(map_state)

@app.post("/start_navigation")
async def start_nav(data: dict):
    """Trigger navigation on the map dashboard."""
    map_state["navigation"] = {
        "is_active": True,
        "destination": data.get("destination"),
        "dest_lat": data.get("lat"),
        "dest_lng": data.get("lng"),
        "steps": data.get("steps", []),
        "current_step_index": 0
    }
    map_state["status"] = f"Navigating to {data.get('destination')}"
    return {"status": "success"}

@app.get("/", response_class=HTMLResponse)
async def map_page():
    html_content = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Walking Assistant — Live View</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://maps.googleapis.com/maps/api/js?key={API_KEY}&libraries=places"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: sans-serif; background: #0f1117; color: #eee; height: 100vh; display: flex; flex-direction: column; }
    #header { padding: 10px 16px; background: #1a1d27; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #2a2d3a; z-index: 10; }
    #header h1 { font-size: 15px; font-weight: 600; color: #fff; }
    #status-pill { font-size: 11px; padding: 3px 10px; border-radius: 12px; background: #2a2d3a; color: #aaa; }
    #status-pill.active { background: #1a3a2a; color: #4ade80; }
    
    #container { flex: 1; display: flex; overflow: hidden; }
    #map { flex: 2; border-right: 2px solid #2a2d3a; }
    #street-view { flex: 1; background: #000; }
    
    #places-panel {
      position: absolute; bottom: 20px; left: 16px; z-index: 1000;
      background: rgba(15, 17, 23, 0.9); border: 1px solid #2a2d3a;
      border-radius: 10px; padding: 10px 14px; min-width: 220px; max-width: 300px;
      backdrop-filter: blur(6px);
      max-height: 400px; overflow-y: auto;
    }
    #places-panel h3 { font-size: 11px; color: #888; text-transform: uppercase; margin-bottom: 6px; }
    #places-list { list-style: none; font-size: 13px; color: #ddd; }
    
    #debug-panel {
      position: absolute; top: 70px; right: 16px; z-index: 1000;
      background: rgba(30, 30, 45, 0.95); border: 1px solid #ff00ff55;
      border-radius: 8px; padding: 12px; width: 280px; font-family: monospace;
      box-shadow: 0 4px 15px rgba(0,0,0,0.5);
    }
    #debug-panel h4 { font-size: 10px; color: #ff00ff; margin-bottom: 8px; border-bottom: 1px solid #ff00ff33; padding-bottom: 4px; }
    #query-json { font-size: 11px; color: #00ff00; white-space: pre-wrap; word-break: break-all; }
    
    #coords { font-size: 10px; color: #666; margin-top: 8px; }
  </style>
</head>
<body>
  <div id="header">
    <h1>Walking Assistant — Live View</h1>
    <span id="status-pill">Connecting...</span>
    <button id="map-toggle" onclick="toggleMapType()" style="margin-left: auto; padding: 4px 12px; background: #3b82f6; border: none; border-radius: 4px; color: white; cursor: pointer; font-size: 11px; font-weight: bold;">SWITCH TO DARK MAP</button>
  </div>
  
  <div id="container">
    <div id="map"></div>
    <div id="street-view"></div>
  </div>

  <div id="debug-panel">
    <h4>DEVELOPER: LAST MAP TOOL CALL</h4>
    <div id="query-json">Waiting for search...</div>
  </div>

  <div id="places-panel">
    <h3>Nearby Places</h3>
    <ul id="places-list"><li>Loading local places...</li></ul>
    <div id="coords">GPS: —</div>
  </div>

  <script>
    let map;
    let userMarker;
    let panorama;
    let markers = [];
    let directionsRenderer;
    let directionsService;
    let lastDest = null;

    function initMap() {
      const pos = { lat: 21.04617, lng: 79.06136 };
      
      // Initialize Google Maps with Satellite view and Dark Style
      map = new google.maps.Map(document.getElementById("map"), {
        center: pos,
        zoom: 17,
        mapTypeId: "satellite",
        disableDefaultUI: true,
        zoomControl: true,
        styles: [
          { elementType: "geometry", stylers: [{ color: "#242f3e" }] },
          { elementType: "labels.text.stroke", stylers: [{ color: "#242f3e" }] },
          { elementType: "labels.text.fill", stylers: [{ color: "#746855" }] },
          {
            featureType: "administrative.locality",
            elementType: "labels.text.fill",
            stylers: [{ color: "#d59563" }],
          },
          {
            featureType: "poi",
            elementType: "labels.text.fill",
            stylers: [{ color: "#d59563" }],
          },
          {
            featureType: "poi.park",
            elementType: "geometry",
            stylers: [{ color: "#263c3f" }],
          },
          {
            featureType: "poi.park",
            elementType: "labels.text.fill",
            stylers: [{ color: "#6b9a76" }],
          },
          {
            featureType: "road",
            elementType: "geometry",
            stylers: [{ color: "#38414e" }],
          },
          {
            featureType: "road",
            elementType: "geometry.stroke",
            stylers: [{ color: "#212a37" }],
          },
          {
            featureType: "road",
            elementType: "labels.text.fill",
            stylers: [{ color: "#9ca5b3" }],
          },
          {
            featureType: "road.highway",
            elementType: "geometry",
            stylers: [{ color: "#746855" }],
          },
          {
            featureType: "road.highway",
            elementType: "geometry.stroke",
            stylers: [{ color: "#1f2835" }],
          },
          {
            featureType: "road.highway",
            elementType: "labels.text.fill",
            stylers: [{ color: "#f3d19c" }],
          },
          {
            featureType: "transit",
            elementType: "geometry",
            stylers: [{ color: "#2f3948" }],
          },
          {
            featureType: "transit.station",
            elementType: "labels.text.fill",
            stylers: [{ color: "#d59563" }],
          },
          {
            featureType: "water",
            elementType: "geometry",
            stylers: [{ color: "#17263c" }],
          },
          {
            featureType: "water",
            elementType: "labels.text.fill",
            stylers: [{ color: "#515c6d" }],
          },
          {
            featureType: "water",
            elementType: "labels.text.stroke",
            stylers: [{ color: "#17263c" }],
          },
        ],
      });
      
      directionsService = new google.maps.DirectionsService();
      directionsRenderer = new google.maps.DirectionsRenderer({
        map: map,
        suppressMarkers: true,
        polylineOptions: {
            strokeColor: '#4ecca3',
            strokeWeight: 6,
            strokeOpacity: 0.8,
        }
      });

      userMarker = new google.maps.Marker({
        position: pos,
        map: map,
        title: "You are here",
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 8,
          fillColor: "#3b82f6",
          fillOpacity: 1,
          strokeColor: "#ffffff",
          strokeWeight: 3
        }
      });

      panorama = new google.maps.StreetViewPanorama(
        document.getElementById("street-view"),
        {
          position: pos,
          pov: { heading: 0, pitch: 0 },
          zoom: 1, addressControl: false, showRoadLabels: false
        }
      );
      
      // Developer Debug: Listen for Street View Errors
      panorama.addListener("status_changed", () => {
        const status = panorama.getStatus();
        if (status !== "OK") {
          console.warn("⚠️ Street View Error:", status);
          document.getElementById('status-pill').textContent = "Street View: " + status;
          document.getElementById('status-pill').className = ''; 
        }
      });
      
      // Fetch upfront places using Maps JS API
      searchLocalPlaces(pos);
    }

    function searchLocalPlaces(location) {
      const service = new google.maps.places.PlacesService(map);
      service.nearbySearch({
        location: location,
        radius: 500,
        type: 'point_of_interest'
      }, (results, status) => {
        if (status === google.maps.places.PlacesServiceStatus.OK && results) {
          // Clear old markers
          markers.forEach(m => m.setMap(null));
          markers = [];
          
          const list = document.getElementById('places-list');
          list.innerHTML = '';
          
          results.slice(0, 10).forEach((place, i) => {
            const marker = new google.maps.Marker({
              map,
              position: place.geometry.location,
              title: place.name,
              label: { text: String(i+1), color: 'white', fontSize: '11px', fontWeight: 'bold' }
            });
            markers.push(marker);
            
            const li = document.createElement('li');
            li.style.marginBottom = '6px';
            li.innerHTML = `<strong>${i+1}. ${place.name}</strong><br><span style="color:#aaa; font-size:10px;">${place.vicinity || ''}</span>`;
            list.appendChild(li);
          });
        }
      });
    }

    function toggleMapType() {
      const currentType = map.getMapTypeId();
      const btn = document.getElementById('map-toggle');
      if (currentType === 'satellite') {
        map.setMapTypeId('roadmap');
        btn.textContent = 'SWITCH TO SATELLITE';
        btn.style.background = '#1a1d27';
        btn.style.border = '1px solid #3b82f6';
      } else {
        map.setMapTypeId('satellite');
        btn.textContent = 'SWITCH TO DARK MAP';
        btn.style.background = '#3b82f6';
        btn.style.border = 'none';
      }
    }

    let lastPos = {lat: 0, lng: 0};

    async function update() {
      try {
        const res = await fetch('/state');
        const data = await res.json();
        const pos = {lat: data.lat, lng: data.lng};
        
        if (userMarker) userMarker.setPosition(pos);
        
        if (Math.abs(pos.lat - lastPos.lat) > 0.00001 || Math.abs(pos.lng - lastPos.lng) > 0.00001) {
          if (map) map.panTo(pos);
          if (panorama) panorama.setPosition(pos);
          
          // Re-search places when we move significantly
          if (map) searchLocalPlaces(pos);
          lastPos = pos;
        }

        // Handle Navigation Path
        if (data.navigation.is_active) {
            const dest = { lat: data.navigation.dest_lat, lng: data.navigation.dest_lng };
            if (JSON.stringify(dest) !== JSON.stringify(lastDest)) {
                directionsService.route({
                    origin: pos,
                    destination: dest,
                    travelMode: 'WALKING',
                }, function(response, status) {
                    if (status === 'OK') {
                        directionsRenderer.setDirections(response);
                    }
                });
                lastDest = dest;
            }
        } else {
            if (lastDest) {
                directionsRenderer.setDirections({routes: []});
                lastDest = null;
            }
        }

        document.getElementById('coords').textContent = `GPS: ${pos.lat.toFixed(6)}, ${pos.lng.toFixed(6)}`;
        document.getElementById('status-pill').textContent = data.status || 'Live';
        document.getElementById('status-pill').className = 'active';

        // Update Developer Debug Info
        const queryDiv = document.getElementById('query-json');
        if (data.last_query) {
            queryDiv.textContent = JSON.stringify(data.last_query, null, 2);
        }

        // If Gemini fetched custom places, we can append them or just let the local JS places stay.
        // We'll let the local places stay since they are visual and pinned on the map.
      } catch(e) {}
    }

    window.onload = () => {
      if (typeof google !== 'undefined') {
        initMap();
        setInterval(update, 2000);
        update();
      }
    };
  </script>
</body>
</html>
""".replace("{API_KEY}", GOOGLE_API_KEY)
    return HTMLResponse(content=html_content)
