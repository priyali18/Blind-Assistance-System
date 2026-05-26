# client.py
import cv2, pyaudio, asyncio, websockets, base64, json
import numpy as np
import threading
import queue
import pyttsx3
import os
import time
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# Video Source from .env
CAMERA_SOURCE = os.getenv("CAMERA_SOURCE", "0")
try:
    # If it's a digit (like "0"), convert to int for local webcam
    CAMERA_INDEX = int(CAMERA_SOURCE) if CAMERA_SOURCE.isdigit() else CAMERA_SOURCE
except:
    CAMERA_INDEX = CAMERA_SOURCE

BACKEND_URL = "ws://localhost:8000/ws/stream"
FRAME_INTERVAL = 2.0  # 1 FPS

# ✅ Toggle this to switch between Push-to-Talk and VAD
USE_PUSH_TO_TALK = False

# --- High-Speed Threaded Camera Reader (v3: Robust MJPEG) ---
class CameraStream:
    def __init__(self, source):
        self.source = source
        self.lock = threading.Lock()
        self.running = True
        self.frame = None
        self.status = False
        
        # Open initial connection
        self.cap = cv2.VideoCapture(self.source)
        
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()
        print(f"[Camera] Stream thread started for {self.source}")

    def _update(self):
        while self.running:
            if not self.cap.isOpened():
                time.sleep(1)
                self.cap.open(self.source)
                continue

            # Standard read — the thread handles the blocking
            ret, frame = self.cap.read()
            
            if ret:
                with self.lock:
                    self.frame = frame
                    self.status = True
            else:
                # If read fails, wait a bit and try to reopen
                print("[Camera] Read failed, reconnecting...")
                self.cap.release()
                time.sleep(1)
                self.cap.open(self.source)

            # Control thread speed to match roughly 30fps and not choke CPU
            time.sleep(0.01)

    def get_frame(self):
        with self.lock:
            return self.frame

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()

def is_speech(audio_chunk: bytes, threshold=60) -> bool:
    audio_array = np.frombuffer(audio_chunk, dtype=np.int16)
    rms = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
    return rms > threshold

def find_working_mic(audio):
    preferred = [2, 1, 0]
    for idx in preferred:
        for rate in [16000, 44100, 48000]:
            try:
                stream = audio.open(
                    format=pyaudio.paInt16, channels=1, rate=rate,
                    input=True, frames_per_buffer=1024, input_device_index=idx
                )
                return stream, rate
            except Exception: continue
    raise RuntimeError("❌ No working microphone found.")

class WalkingAssistantClient:
    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.stream, self.mic_rate = find_working_mic(self.audio)
        self.tts = pyttsx3.init()
        self.tts.setProperty('rate', 190)

        self.lat = 21.04617
        self.lng = 79.06136

        # Initialize Threaded Camera
        print(f"📷 Opening Camera Stream: {CAMERA_SOURCE}")
        self.cam = CameraStream(CAMERA_INDEX)

        self.audio_queue = queue.Queue()
        self.playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self.playback_thread.start()

        self.greeting_done = asyncio.Event()
        self.conversation = []
        self.status = "Initializing..."
        self.is_speaking = False
        self.running = True

        self.ptt_active = False
        self.ptt_just_released = False

    def _playback_worker(self):
        out_stream = self.audio.open(format=pyaudio.paInt16, channels=1, rate=24000, output=True)
        while True:
            chunk = self.audio_queue.get()
            if chunk is None: break
            out_stream.write(chunk)
        out_stream.close()

    def add_message(self, role: str, text: str):
        time_str = datetime.now().strftime("%H:%M:%S")
        self.conversation.append({"role": role, "text": text, "time": time_str})
        if len(self.conversation) > 8: self.conversation.pop(0)

    def capture_audio_chunk(self):
        return self.stream.read(1024, exception_on_overflow=False)

    def ui_thread(self):
        while self.running:
            # Grab the LATEST frame from the background thread
            frame = self.cam.get_frame()
            self._draw_ui(frame)

            key = cv2.waitKey(30) & 0xFF
            if key == ord('q'): self.running = False; break
            if key == ord('w'): self.lat += 0.0001
            if key == ord('s'): self.lat -= 0.0001
            if key == ord('a'): self.lng -= 0.0001
            if key == ord('d'): self.lng += 0.0001

            if USE_PUSH_TO_TALK:
                if key == 32: self.ptt_active = True
                else:
                    if self.ptt_active: self.ptt_active = False; self.ptt_just_released = True

        self.cam.stop()
        cv2.destroyAllWindows()
        self.audio_queue.put(None)

    def _draw_ui(self, frame):
        canvas = np.zeros((600, 1100, 3), dtype=np.uint8)
        if frame is not None:
            canvas[60:540, 20:660] = cv2.resize(frame, (640, 480))

        cv2.putText(canvas, "AI WALKING ASSISTANT (Lag-Free Mode)", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)

        # Draw status
        status_color = (0, 0, 255) if self.ptt_active else (0, 255, 0) if self.is_speaking else (100, 100, 255)
        cv2.putText(canvas, f"STATUS: {self.status.upper()}", (400, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2)

        panel_x = 680
        y = 90
        for msg in self.conversation:
            color = (100, 255, 100) if msg["role"] == "user" else (255, 200, 50)
            cv2.putText(canvas, f"[{msg['time']}] {msg['role'].upper()}:", (panel_x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
            y += 18
            cv2.putText(canvas, msg["text"][:50], (panel_x + 10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (220, 220, 220), 1)
            y += 22

        cv2.putText(canvas, f"GPS: {self.lat:.5f}, {self.lng:.5f} (WASD to move)", (10, 590), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)
        cv2.imshow("Walking Assistant Monitor", canvas)

    async def connect_and_run(self):
        async with websockets.connect(BACKEND_URL, ping_interval=20, ping_timeout=60) as ws:
            self.status = "Connected"
            async def receive_loop():
                while self.running:
                    try:
                        data = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.0))
                        if data.get("audio"):
                            self.audio_queue.put(base64.b64decode(data["audio"]))
                            self.status = "Speaking"
                        if data.get("transcript"):
                            text = data["transcript"]
                            self.add_message("gemini", text)
                            if "REFLEX:" in text or not data.get("audio"):
                                self.tts.say(text.replace("REFLEX:", ""))
                                self.tts.runAndWait()
                        if data.get("turn_complete"):
                            self.greeting_done.set()
                            self.status = "Listening"
                    except asyncio.TimeoutError: continue
                    except: break

            async def send_loop():
                last_frame_time = 0
                was_speaking = False
                silence_counter = 0
                SILENCE_TIMEOUT = 12 # ~2.4 seconds of silence to trigger ActivityEnd

                await self.greeting_done.wait()
                while self.running:
                    try:
                        now = asyncio.get_event_loop().time()
                        payload = {"lat": self.lat, "lng": self.lng}
                        raw_audio = self.capture_audio_chunk()

                        if is_speech(raw_audio):
                            self.is_speaking = True
                            self.status = "User Speaking"
                            payload["audio"] = base64.b64encode(raw_audio).decode('utf-8')
                            if not was_speaking: payload["speech_start"] = True
                            was_speaking = True
                            silence_counter = 0
                        else:
                            if was_speaking:
                                silence_counter += 1
                                if silence_counter >= SILENCE_TIMEOUT:
                                    payload["speech_end"] = True
                                    was_speaking = False
                                    self.add_message("user", "[voice input]")
                                    self.status = "Processing"

                        if now - last_frame_time >= FRAME_INTERVAL:
                            # Use the latest frame from the background thread
                            frame = self.cam.get_frame()
                            if frame is not None:
                                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                                payload["frame"] = base64.b64encode(buffer).decode('utf-8')
                            last_frame_time = now

                        await ws.send(json.dumps(payload))
                        await asyncio.sleep(0.2)
                    except: break

            await asyncio.gather(receive_loop(), send_loop())

    async def run(self):
        threading.Thread(target=self.ui_thread, daemon=True).start()
        while self.running:
            try: await self.connect_and_run()
            except: pass
            if self.running: await asyncio.sleep(3)

asyncio.run(WalkingAssistantClient().run())
