# server.py
import sys
import os
import asyncio
import base64
import json
import cv2
import numpy as np
import time
import httpx
import re
import requests  # used directly in sync maps calls
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, WebSocket
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# PATH SETUP — channel_ii modules must be resolvable from
# both the main thread AND executor threads
# ============================================================
import sys
import os

ROOT_PATH = os.path.dirname(os.path.abspath(__file__))

if ROOT_PATH not in sys.path:
    sys.path.insert(0, ROOT_PATH)
CHANNEL_II_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "channel_ii")
if CHANNEL_II_PATH not in sys.path:
    sys.path.insert(0, CHANNEL_II_PATH)

from channel_ii.modules.detector import ObjectDetector
from channel_ii.modules.obstacle import ObstacleDetector
from channel_ii.modules.navigator import Navigator
from config import (
    YOLO_MODEL, YOLO_CONFIDENCE,
    OBSTACLE_CLASSES, CLOSE_THRESHOLD, MEDIUM_THRESHOLD,
    SAFETY_STOP_THRESHOLD, SPEECH_COOLDOWN,
    FRAME_WIDTH, FRAME_HEIGHT,
    GOOGLE_MAPS_API_KEY,
)

from map_server import app, map_state
from context import SYSTEM_PROMPT

# ============================================================
# GEMINI CLIENT
# ============================================================
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ============================================================
# MAPS API — self-contained blocking functions
#
# Why not use GoogleMapsService from channel_ii?
# Because google_maps.py does:
#   from modules.gps_location import GPSLocation
# inside find_nearby_places(). When this runs in a thread
# executor, sys.path context can differ and the import silently
# fails, returning [] with no error message logged anywhere.
# These inline functions have zero external dependencies.
# ============================================================
MAPS_NEARBY     = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
MAPS_TEXTSEARCH = "https://maps.googleapis.com/maps/api/place/textsearch/json"
MAPS_GEOCODE    = "https://maps.googleapis.com/maps/api/geocode/json"
MAPS_DIRECTIONS = "https://maps.googleapis.com/maps/api/directions/json"

def _haversine(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, sqrt, atan2
    R = 6_371_000
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2-lat1), radians(lng2-lng1)
    a = sin(dp/2)**2 + cos(p1)*cos(p2)*sin(dl/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def _fmt_dist(m):
    if m < 100:  return f"{int(m)} metres"
    if m < 1000: return f"{int(m/10)*10} metres"
    return f"{m/1000:.1f} km"

def _maps_nearby(lat, lng, place_type, radius=2000, max_results=10):
    """Blocking: Google Places nearbysearch."""
    try:
        r = requests.get(MAPS_NEARBY, params={
            "location": f"{lat},{lng}",
            "radius":   radius,
            "type":     place_type,
            "key":      GOOGLE_MAPS_API_KEY,
        }, timeout=10)
        data = r.json()
        status = data.get("status", "UNKNOWN")
        if status not in ("OK", "ZERO_RESULTS"):
            print(f"[Maps] nearbysearch error: {status} — {data.get('error_message','')}")
            return []
        results = []
        for p in data.get("results", [])[:max_results]:
            plat = p["geometry"]["location"]["lat"]
            plng = p["geometry"]["location"]["lng"]
            dist = _haversine(lat, lng, plat, plng)
            results.append({
                "name":          p.get("name", "Unknown"),
                "address":       p.get("vicinity", ""),
                "lat": plat, "lng": plng,
                "distance_m":    dist,
                "distance_text": _fmt_dist(dist),
                "open_now":      p.get("opening_hours", {}).get("open_now"),
            })
        results.sort(key=lambda x: x["distance_m"])
        return results
    except Exception as e:
        print(f"[Maps] nearbysearch exception: {e}")
        return []

def _maps_textsearch(query, lat=None, lng=None):
    """Blocking: Google Places textsearch."""
    try:
        params = {"query": query, "key": GOOGLE_MAPS_API_KEY}
        if lat and lng:
            params["location"] = f"{lat},{lng}"
            params["radius"]   = 5000
        r = requests.get(MAPS_TEXTSEARCH, params=params, timeout=10)
        data = r.json()
        if data.get("status") != "OK" or not data.get("results"):
            print(f"[Maps] textsearch no result for '{query}': {data.get('status')}")
            return None
        p = data["results"][0]
        return {
            "name":    p.get("name", query),
            "lat":     p["geometry"]["location"]["lat"],
            "lng":     p["geometry"]["location"]["lng"],
            "address": p.get("formatted_address", ""),
        }
    except Exception as e:
        print(f"[Maps] textsearch exception: {e}")
        return None

def _maps_geocode(address):
    """Blocking: Google Geocoding API."""
    try:
        r = requests.get(MAPS_GEOCODE, params={
            "address": address, "key": GOOGLE_MAPS_API_KEY
        }, timeout=10)
        data = r.json()
        if data.get("status") != "OK" or not data.get("results"):
            print(f"[Maps] geocode no result for '{address}': {data.get('status')}")
            return None
        res = data["results"][0]
        return {
            "name":    res.get("formatted_address", address),
            "lat":     res["geometry"]["location"]["lat"],
            "lng":     res["geometry"]["location"]["lng"],
            "address": res.get("formatted_address", ""),
        }
    except Exception as e:
        print(f"[Maps] geocode exception: {e}")
        return None

def _maps_directions(origin_lat, origin_lng, dest_lat, dest_lng, dest_name=""):
    """Blocking: Google Directions API (walking mode)."""
    try:
        r = requests.get(MAPS_DIRECTIONS, params={
            "origin":      f"{origin_lat},{origin_lng}",
            "destination": f"{dest_lat},{dest_lng}",
            "mode":        "walking",
            "key":         GOOGLE_MAPS_API_KEY,
        }, timeout=10)
        data = r.json()
        if data.get("status") != "OK":
            print(f"[Maps] directions error: {data.get('status')}")
            return None
        leg = data["routes"][0]["legs"][0]
        steps = []
        for step in leg["steps"]:
            clean = re.sub(r'<[^>]+>', ' ', step["html_instructions"])
            clean = re.sub(r'\s+', ' ', clean).strip()
            steps.append({
                "instruction":     clean,
                "distance":        step["distance"]["text"],
                "distance_meters": step["distance"]["value"],
                "duration":        step["duration"]["text"],
                "start_lat":       step["start_location"]["lat"],
                "start_lng":       step["start_location"]["lng"],
                "end_lat":         step["end_location"]["lat"],
                "end_lng":         step["end_location"]["lng"],
                "maneuver":        step.get("maneuver", ""),
            })
        return {
            "dest_name":            dest_name or leg["end_address"],
            "total_distance":       leg["distance"]["text"],
            "total_distance_meters":leg["distance"]["value"],
            "total_duration":       leg["duration"]["text"],
            "steps":                steps,
        }
    except Exception as e:
        print(f"[Maps] directions exception: {e}")
        return None


# ============================================================
# GEMINI TOOL DECLARATIONS
# ============================================================
maps_tool = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_nearby_landmarks",
        description=(
            "Find nearby places such as hospital, ATM, restaurant, pharmacy, park, bank, etc. "
            "Call this IMMEDIATELY when the user asks what is nearby or wants to find a specific "
            "type of place. Do NOT ask for confirmation first. "
            "Use gps.lat and gps.lng from the latest SITUATION_REPORT."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "latitude":      types.Schema(type=types.Type.NUMBER,  description="User latitude — use gps.lat from SITUATION_REPORT."),
                "longitude":     types.Schema(type=types.Type.NUMBER,  description="User longitude — use gps.lng from SITUATION_REPORT."),
                "place_type":    types.Schema(type=types.Type.STRING,  description="Google place type: hospital, atm, restaurant, pharmacy, bus_station, park, bank, supermarket, police, etc."),
                "radius_meters": types.Schema(type=types.Type.INTEGER, description="Search radius in metres. Default 1000."),
            },
            required=["latitude", "longitude", "place_type"]
        )
    ),
    types.FunctionDeclaration(
        name="start_navigation",
        description=(
            "Start turn-by-turn walking navigation to a destination. "
            "Call this IMMEDIATELY when the user says take me to, navigate to, go to, "
            "how do I get to, or any similar phrase. Do NOT ask for confirmation first. "
            "Use gps.lat and gps.lng from the latest SITUATION_REPORT."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "destination": types.Schema(type=types.Type.STRING, description="Name or address of the destination."),
                "latitude":    types.Schema(type=types.Type.NUMBER, description="User latitude — use gps.lat from SITUATION_REPORT."),
                "longitude":   types.Schema(type=types.Type.NUMBER, description="User longitude — use gps.lng from SITUATION_REPORT."),
            },
            required=["destination", "latitude", "longitude"]
        )
    ),
    types.FunctionDeclaration(
        name="search_place",
        description=(
            "Search for a specific named place to get its coordinates. "
            "Use this when start_navigation fails to find the destination, "
            "or when you need to resolve a place name before navigating."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query":     types.Schema(type=types.Type.STRING, description="Place name e.g. 'City Hospital Nagpur' or 'Nagpur central railway station'."),
                "latitude":  types.Schema(type=types.Type.NUMBER, description="User latitude for location bias."),
                "longitude": types.Schema(type=types.Type.NUMBER, description="User longitude for location bias."),
            },
            required=["query", "latitude", "longitude"]
        )
    ),
])


# ============================================================
# NAVIGATION STATE
# ============================================================
class NavigationState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.is_active        = False
        self.destination      = None
        self.dest_lat         = None
        self.dest_lng         = None
        self.route            = None
        self.current_step_idx = 0
        self.last_announced   = -1

nav_state = NavigationState()


# ============================================================
# THREAD EXECUTOR
# max_workers=4: 2 for YOLO, 2 for Maps API calls
# ============================================================
executor = ThreadPoolExecutor(max_workers=4)

async def _run_blocking(fn, *args):
    """
    Run a blocking function in the thread executor.
    Uses asyncio.get_running_loop() — correct for Python 3.10+,
    avoids the deprecated get_event_loop() which can return the
    wrong loop inside an already-running coroutine.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, fn, *args)


# ============================================================
# DASHBOARD PUSH HELPERS
# ============================================================
async def _push_route_to_dashboard(destination, dest_lat, dest_lng, steps):
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            await client.post("http://localhost:8001/start_navigation", json={
                "destination": destination,
                "lat": dest_lat, "lng": dest_lng,
                "steps": steps,
            })
        print(f"[Dashboard] Route pushed: {destination}")
    except Exception as e:
        print(f"[Dashboard] push_route failed (non-fatal): {e}")

async def _push_step_to_dashboard(step_index: int):
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            await client.post("http://localhost:8001/update_step", json={"step_index": step_index})
    except Exception:
        pass

async def _push_stop_to_dashboard():
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            await client.post("http://localhost:8001/stop_navigation")
    except Exception:
        pass


# ============================================================
# TOOL HANDLERS
# ============================================================

async def handle_get_nearby_landmarks(args: dict) -> dict:
    lat        = float(args["latitude"])
    lng        = float(args["longitude"])
    place_type = str(args.get("place_type", "point_of_interest"))
    radius     = int(args.get("radius_meters", 1000))

    print(f"[Tool] get_nearby_landmarks: '{place_type}' @ ({lat:.5f},{lng:.5f}) r={radius}m")

    places = await _run_blocking(_maps_nearby, lat, lng, place_type, radius)

    map_state["last_query"] = args
    map_state["places"]     = places
    map_state["status"]     = f"Found {len(places)} {place_type}(s)"

    if not places:
        return {"result": f"No {place_type} found within {_fmt_dist(radius)}."}

    lines = [f"Found {len(places)} {place_type}{'s' if len(places)>1 else ''} nearby."]
    for i, p in enumerate(places[:3]):
        open_str = ""
        if p.get("open_now") is True:  open_str = ", open now"
        if p.get("open_now") is False: open_str = ", currently closed"
        lines.append(f"{i+1}. {p['name']}, {p['distance_text']} away{open_str}.")
    if len(places) > 3:
        lines.append(f"And {len(places)-3} more.")

    return {
        "result": " ".join(lines),
        "places": [{"name":p["name"],"distance":p["distance_text"],
                    "address":p["address"],"lat":p["lat"],"lng":p["lng"]}
                   for p in places],
    }


async def handle_search_place(args: dict) -> dict:
    query = str(args["query"])
    lat   = float(args["latitude"])
    lng   = float(args["longitude"])

    print(f"[Tool] search_place: '{query}' @ ({lat:.5f},{lng:.5f})")

    result = await _run_blocking(_maps_textsearch, query, lat, lng)
    if not result:
        result = await _run_blocking(_maps_geocode, query)
    if not result:
        return {"result": f"Could not find '{query}'. Try a more specific name or address."}

    return {
        "result":  f"Found {result['name']} at {result['address']}.",
        "name":    result["name"],
        "lat":     result["lat"],
        "lng":     result["lng"],
        "address": result["address"],
    }


async def handle_start_navigation(args: dict) -> dict:
    destination = str(args["destination"])
    origin_lat  = float(args["latitude"])
    origin_lng  = float(args["longitude"])

    print(f"[Tool] start_navigation: '{destination}' from ({origin_lat:.5f},{origin_lng:.5f})")

    # Resolve destination → coordinates
    dest = await _run_blocking(_maps_textsearch, destination, origin_lat, origin_lng)
    if not dest:
        dest = await _run_blocking(_maps_geocode, destination)
    if not dest:
        return {"error": f"Could not find '{destination}'. Try a more specific name."}

    dest_lat  = dest["lat"]
    dest_lng  = dest["lng"]
    dest_name = dest.get("name", destination)
    print(f"[Tool] Destination resolved: {dest_name} ({dest_lat:.5f},{dest_lng:.5f})")

    # Get walking directions
    route = await _run_blocking(_maps_directions, origin_lat, origin_lng, dest_lat, dest_lng, dest_name)
    if not route:
        return {"error": f"No walking route found to {dest_name}. Are you outdoors with GPS?"}

    # Update navigation state
    nav_state.is_active        = True
    nav_state.destination      = dest_name
    nav_state.dest_lat         = dest_lat
    nav_state.dest_lng         = dest_lng
    nav_state.route            = route
    nav_state.current_step_idx = 0
    nav_state.last_announced   = -1

    # Push to dashboard (background task, non-blocking)
    asyncio.create_task(_push_route_to_dashboard(dest_name, dest_lat, dest_lng, route["steps"]))

    first_step = route["steps"][0]["instruction"]
    print(f"[Tool] Nav started: {route['total_distance']}, {route['total_duration']}, {len(route['steps'])} steps")

    return {
        "result":         f"Navigation started to {dest_name}. {route['total_distance']}, about {route['total_duration']} walking. First instruction: {first_step}.",
        "destination":    dest_name,
        "total_distance": route["total_distance"],
        "total_duration": route["total_duration"],
        "total_steps":    len(route["steps"]),
        "first_step":     first_step,
    }


async def dispatch_tool(fc) -> dict:
    """Route a Gemini function_call to the correct handler."""
    name = fc.name
    args = dict(fc.args)

    # Safety net: inject current GPS if Gemini forgot to include it
    if not args.get("latitude"):
        args["latitude"]  = map_state["lat"]
    if not args.get("longitude"):
        args["longitude"] = map_state["lng"]

    print(f"[Tool] Dispatching '{name}' with args: {args}")

    if name == "get_nearby_landmarks":
        return await handle_get_nearby_landmarks(args)
    elif name == "search_place":
        return await handle_search_place(args)
    elif name == "start_navigation":
        return await handle_start_navigation(args)
    else:
        print(f"[Tool] Unknown tool name: {name}")
        return {"error": f"Unknown tool: {name}"}


# ============================================================
# YOLO REFLEX MODELS
# ============================================================
CLOUD_MODE = os.getenv("CLOUD_MODE", "false").lower() == "true"

if not CLOUD_MODE:
    print("[Init] Loading YOLOv8 reflex models...")
    detector          = ObjectDetector(YOLO_MODEL, YOLO_CONFIDENCE)
    obstacle_detector = ObstacleDetector(
        obstacle_classes=OBSTACLE_CLASSES,
        frame_width=FRAME_WIDTH, frame_height=FRAME_HEIGHT,
        close_threshold=CLOSE_THRESHOLD, medium_threshold=MEDIUM_THRESHOLD,
        safety_stop_threshold=SAFETY_STOP_THRESHOLD,
    )
    navigator_reflex = Navigator(cooldown=SPEECH_COOLDOWN)
else:
    print("[Init] ☁️ CLOUD_MODE: Skipping heavy local ML models.")
    detector = None
    obstacle_detector = None
    navigator_reflex = None

ML_RES = (320, 240)

def process_reflexes(frame_bytes: bytes):
    """
    Reflex loop: YOLO detection + Obstacle logic.
    Returns (report_dict, instruction_dict).
    """
    if CLOUD_MODE:
        return {"obstacles": [], "instruction": "NONE"}, None
    """Blocking — runs in thread executor. Must not touch asyncio."""
    nparr = np.frombuffer(frame_bytes, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        return None, None
    ml_frame    = cv2.resize(frame, ML_RES)
    detections  = detector.detect(ml_frame)
    obstacles   = obstacle_detector.process(detections)
    instruction = navigator_reflex.decide(obstacles)
    report = {
        "obstacles":   [o["label"] for o in obstacles],
        "instruction": instruction["type"] if instruction else "NONE",
    }
    return report, instruction


# ============================================================
# WEBSOCKET ENDPOINT
# ============================================================
@app.get("/healthz")
async def healthz():
    return {"status": "ok", "cloud_mode": CLOUD_MODE}

@app.websocket("/ws/stream")
async def stream_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("✅ WebSocket accepted")
    map_state["status"] = "Connected"
    nav_state.reset()

    try:
        async with gemini_client.aio.live.connect(
            model="gemini-2.5-flash-native-audio-latest",
            config=types.LiveConnectConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[maps_tool],
                response_modalities=["AUDIO"],
                realtime_input_config=types.RealtimeInputConfig(
                    automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)
                ),
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
                    )
                )
            )
        ) as session:
            print("✅ Gemini Live session opened")
            map_state["status"] = "Ready"

            # Initial greeting
            await session.send_client_content(
                turns=[types.Content(
                    parts=[types.Part(text=(
                        "Greet the user briefly. Say you are NavBot, their walking assistant, "
                        "and you are ready to help. One or two plain sentences only. No markdown."
                    ))],
                    role="user"
                )],
                turn_complete=True
            )

            # ──────────────────────────────────────────────────
            # SEND LOOP — client → server → Gemini
            # ──────────────────────────────────────────────────
            async def send_loop():
                audio_sent_this_turn  = False
                last_report_time      = 0.0
                last_proactive_time   = time.time()
                last_instruction_type = "NONE"

                while True:
                    try:
                        raw  = await websocket.receive_text()
                        data = json.loads(raw)
                    except Exception as e:
                        print(f"❌ Send loop error: {e}")
                        break

                    # ── GPS update ──────────────────────────────
                    if "lat" in data and "lng" in data:
                        map_state["lat"] = data["lat"]
                        map_state["lng"] = data["lng"]
                        map_state["status"] = "Walking..."

                        if nav_state.is_active and nav_state.route:
                            steps = nav_state.route["steps"]
                            dist_to_dest = _haversine(
                                map_state["lat"], map_state["lng"],
                                nav_state.dest_lat, nav_state.dest_lng
                            )
                            if dist_to_dest < 30:
                                print("🏁 Arrived!")
                                nav_state.reset()
                                map_state["status"] = "Arrived"
                                asyncio.create_task(_push_stop_to_dashboard())
                            else:
                                min_dist = float("inf")
                                best_idx = nav_state.current_step_idx
                                for i in range(nav_state.current_step_idx, len(steps)):
                                    s   = steps[i]
                                    d_s = _haversine(map_state["lat"], map_state["lng"], s["start_lat"], s["start_lng"])
                                    d_e = _haversine(map_state["lat"], map_state["lng"], s["end_lat"],   s["end_lng"])
                                    if d_s < min_dist: min_dist = d_s; best_idx = i
                                    if d_e < min_dist: min_dist = d_e; best_idx = min(i+1, len(steps)-1)
                                if best_idx != nav_state.current_step_idx:
                                    nav_state.current_step_idx = best_idx
                                    print(f"📍 Step {best_idx+1}/{len(steps)}")
                                    asyncio.create_task(_push_step_to_dashboard(best_idx))
                                if min_dist > 60:
                                    map_state["status"] = "Off track!"

                    # ── Camera frame → YOLO + Gemini video ─────
                    if "frame" in data:
                        frame_bytes = base64.b64decode(data["frame"])

                        report, instruction = await _run_blocking(process_reflexes, frame_bytes)

                        if report:
                            # Immediate STOP reflex — bypasses LLM latency
                            if instruction and instruction["type"] == "STOP":
                                print(f"🚨 REFLEX STOP: {instruction['message']}")
                                map_state["status"] = "HAZARD: STOP"
                                await websocket.send_text(json.dumps({
                                    "transcript": f"REFLEX: {instruction['message']}"
                                }))

                            now          = time.time()
                            current_inst = report.get("instruction", "NONE")

                            significant_change = (current_inst != last_instruction_type)
                            time_for_update    = (now - last_proactive_time > 15.0)
                            nav_step_change    = (
                                nav_state.is_active and
                                nav_state.current_step_idx != nav_state.last_announced
                            )

                            if now - last_report_time > 2.0:
                                should_trigger = significant_change or time_for_update or nav_step_change

                                report["latitude"]  = map_state["lat"]
                                report["longitude"] = map_state["lng"]
                                report["gps"]       = {"lat": map_state["lat"], "lng": map_state["lng"]}

                                if nav_state.is_active and nav_state.route:
                                    curr = nav_state.route["steps"][nav_state.current_step_idx]
                                    report["navigation"] = {
                                        "is_active":        True,
                                        "destination":      nav_state.destination,
                                        "instruction":      curr["instruction"],
                                        "distance_to_turn": curr["distance"],
                                        "step_number":      nav_state.current_step_idx + 1,
                                        "total_steps":      len(nav_state.route["steps"]),
                                    }
                                else:
                                    report["navigation"] = {"is_active": False}

                                await session.send_client_content(
                                    turns=[types.Content(
                                        parts=[types.Part(text=f"SITUATION_REPORT: {json.dumps(report)}")],
                                        role="user"
                                    )],
                                    turn_complete=should_trigger
                                )

                                last_report_time = now
                                if should_trigger:
                                    last_proactive_time   = now
                                    last_instruction_type = current_inst
                                    if nav_state.is_active:
                                        nav_state.last_announced = nav_state.current_step_idx
                                    print(f"🧠 Proactive: change={significant_change} time={time_for_update} nav={nav_step_change}")

                        # Always forward frame to Gemini vision stream
                        await session.send_realtime_input(
                            video=types.Blob(data=frame_bytes, mime_type="image/jpeg")
                        )

                    # ── Voice activity ──────────────────────────
                    if data.get("speech_start"):
                        print("🎙️ ActivityStart")
                        await session.send_realtime_input(activity_start=types.ActivityStart())

                    if "audio" in data:
                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=base64.b64decode(data["audio"]),
                                mime_type="audio/pcm;rate=16000"
                            )
                        )
                        audio_sent_this_turn = True

                    if (data.get("speech_end") or data.get("turn_complete")) and audio_sent_this_turn:
                        print("🔚 ActivityEnd")
                        await session.send_realtime_input(activity_end=types.ActivityEnd())
                        audio_sent_this_turn = False

            # ──────────────────────────────────────────────────
            # RECEIVE LOOP — Gemini → server → client
            # ──────────────────────────────────────────────────
            async def receive_loop():
                while True:
                    try:
                        async for response in session.receive():

                            # ── Text transcript ─────────────────
                            if response.server_content and response.server_content.model_turn:
                                for part in response.server_content.model_turn.parts:
                                    if hasattr(part, "text") and part.text:
                                        print(f"💬 Gemini: {part.text}")
                                        await websocket.send_text(json.dumps({"transcript": part.text}))

                            # ── Tool calls ──────────────────────
                            if response.tool_call:
                                for fc in response.tool_call.function_calls:
                                    print(f"🗺️  Tool: {fc.name}  args={dict(fc.args)}")
                                    await websocket.send_text(json.dumps({"tool_called": fc.name}))

                                    try:
                                        # 15s timeout — Maps API can be slow on first call
                                        result = await asyncio.wait_for(
                                            dispatch_tool(fc), timeout=15.0
                                        )
                                    except asyncio.TimeoutError:
                                        print(f"❌ Tool timeout: {fc.name}")
                                        result = {"error": f"{fc.name} timed out. Please try again."}
                                    except Exception as tool_err:
                                        print(f"❌ Tool error [{fc.name}]: {tool_err}")
                                        result = {"error": str(tool_err)}

                                    # Always respond — never leave Gemini waiting on a tool
                                    await session.send_tool_response(
                                        function_responses=[
                                            types.FunctionResponse(
                                                name=fc.name,
                                                id=fc.id,
                                                response=result
                                            )
                                        ]
                                    )
                                    print(f"✅ Tool response: {fc.name} → {str(result)[:150]}")

                            # ── Audio ────────────────────────────
                            if response.data:
                                await websocket.send_text(json.dumps({
                                    "audio": base64.b64encode(response.data).decode()
                                }))

                            # ── Turn complete ────────────────────
                            if response.server_content and response.server_content.turn_complete:
                                print("✅ Turn complete")
                                await websocket.send_text(json.dumps({"turn_complete": True}))

                    except Exception as e:
                        print(f"❌ Receive loop error: {e}")
                        break

            await asyncio.gather(send_loop(), receive_loop())

    except Exception as e:
        print(f"❌ Gemini session error: {e}")
        map_state["status"] = "Error"
        await websocket.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)