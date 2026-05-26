"""
============================================
Module: Voice Output (Text-to-Speech)
============================================
Uses Windows SAPI directly via win32com for
reliable threaded speech. Falls back to pyttsx3
or ElevenLabs if available.

Key Design:
  - Non-blocking: speech runs in a background thread
  - Uses Windows SAPI COM directly (avoids pyttsx3 bugs)
  - COM initialized per-thread (required on Windows)
  - Only speaks the LATEST instruction (old ones dropped)
============================================
"""

import threading
import queue
import time
import os


class VoiceOutput:
    """
    Text-to-Speech using Windows SAPI directly.

    Usage:
        voice = VoiceOutput()
        voice.start()
        voice.speak("Stop! Chair ahead.")
        voice.stop()
    """

    def __init__(self, elevenlabs_api_key="", voice_id="21m00Tcm4TlvDq8ikWAM",
                 pyttsx3_rate=175, pyttsx3_volume=1.0, use_elevenlabs=True):
        """
        Initialize voice output.

        Args:
            elevenlabs_api_key (str): ElevenLabs API key
            voice_id (str): ElevenLabs voice ID
            pyttsx3_rate (int): Speech rate (words per minute)
            pyttsx3_volume (float): Volume (0.0 to 1.0)
            use_elevenlabs (bool): Try ElevenLabs first
        """
        self.elevenlabs_api_key = elevenlabs_api_key
        self.voice_id = voice_id
        self.speech_rate = pyttsx3_rate
        self.speech_volume = pyttsx3_volume
        self.use_elevenlabs = use_elevenlabs

        # Latest message to speak (only one at a time, newest wins)
        self._latest_message = None
        self._message_lock = threading.Lock()

        self.is_running = False
        self.worker_thread = None
        self._sapi_voice = None

        self._elevenlabs_client = None
        self._elevenlabs_available = False

        # Initialize ElevenLabs if key provided
        if self.use_elevenlabs and self.elevenlabs_api_key:
            self._init_elevenlabs()

        print("[Voice] Will use Windows SAPI (initialized in worker thread)")

    def _init_elevenlabs(self):
        """Initialize ElevenLabs API client."""
        try:
            from elevenlabs import ElevenLabs
            self._elevenlabs_client = ElevenLabs(api_key=self.elevenlabs_api_key)
            self._elevenlabs_available = True
            print("[Voice] ElevenLabs initialized (primary TTS)")
        except Exception as e:
            print(f"[Voice] ElevenLabs unavailable: {e}")
            self._elevenlabs_available = False

    def start(self):
        """Start the background speech worker thread."""
        if self.is_running:
            return

        self.is_running = True
        self.worker_thread = threading.Thread(
            target=self._speech_worker,
            daemon=True,
            name="VoiceOutputWorker"
        )
        self.worker_thread.start()
        print("[Voice] Background speech worker started")

    def stop(self):
        """Stop the speech worker."""
        self.is_running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=3)
        print("[Voice] Stopped")

    def speak(self, text):
        """
        Set the latest message to be spoken (non-blocking).
        Replaces any pending message — only the newest matters.

        Args:
            text (str): The message to speak
        """
        with self._message_lock:
            self._latest_message = text

    def _speech_worker(self):
        """
        Background thread: initializes Windows SAPI COM,
        then continuously checks for new messages to speak.
        """
        # Initialize COM for this thread (REQUIRED on Windows)
        try:
            import pythoncom
            pythoncom.CoInitialize()
            com_initialized = True
        except ImportError:
            com_initialized = False

        # Initialize SAPI voice in this thread
        sapi_ready = self._init_sapi()

        while self.is_running:
            # Grab the latest message (atomic swap)
            with self._message_lock:
                text = self._latest_message
                self._latest_message = None

            if text is None:
                time.sleep(0.1)  # No message, wait briefly
                continue

            # Speak it
            if sapi_ready:
                self._speak_sapi(text)
            else:
                self._speak_pyttsx3_fresh(text)

        # Cleanup COM
        if com_initialized:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def _init_sapi(self):
        """
        Initialize Windows SAPI voice directly via win32com.
        This is what pyttsx3 uses underneath, but without the
        buggy wrapper that breaks on repeated runAndWait() calls.
        """
        try:
            import win32com.client
            self._sapi_voice = win32com.client.Dispatch("SAPI.SpVoice")
            # Rate: -10 (slowest) to 10 (fastest). Map from WPM roughly.
            # 175 WPM ≈ rate 2
            rate = max(-10, min(10, (self.speech_rate - 150) // 25))
            self._sapi_voice.Rate = rate
            self._sapi_voice.Volume = int(self.speech_volume * 100)
            print(f"[Voice] Windows SAPI initialized (rate={rate}, vol={int(self.speech_volume*100)})")
            return True
        except Exception as e:
            print(f"[Voice] SAPI init failed: {e}, will use pyttsx3 fallback")
            self._sapi_voice = None
            return False

    def _speak_sapi(self, text):
        """
        Speak using Windows SAPI directly.
        Reliable, no state bugs, works in threads with COM init.
        """
        try:
            # SVSFlagsAsync = 1 (but we want sync so we block until done)
            self._sapi_voice.Speak(text, 0)
        except Exception as e:
            print(f"[Voice] SAPI speak error: {e}")
            # Try reinitializing
            self._init_sapi()

    def _speak_pyttsx3_fresh(self, text):
        """
        Fallback: create a FRESH pyttsx3 engine for each message.
        Avoids the state bug where engine breaks after first runAndWait().
        """
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', self.speech_rate)
            engine.setProperty('volume', self.speech_volume)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
            del engine
        except Exception as e:
            print(f"[Voice] pyttsx3 error: {e}")

    def _speak_elevenlabs(self, text):
        """Speak using ElevenLabs API."""
        try:
            import subprocess
            import tempfile

            audio_generator = self._elevenlabs_client.text_to_speech.convert(
                text=text,
                voice_id=self.voice_id,
                model_id="eleven_turbo_v2",
                output_format="mp3_44100_128"
            )

            audio_bytes = b""
            for chunk in audio_generator:
                audio_bytes += chunk

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(audio_bytes)
                temp_path = f.name

            subprocess.run(
                ["powershell", "-c",
                 f"(New-Object Media.SoundPlayer '{temp_path}').PlaySync()"],
                capture_output=True, timeout=5
            )

            try:
                os.unlink(temp_path)
            except Exception:
                pass

            return True
        except Exception as e:
            print(f"[Voice] ElevenLabs error: {e}")
            self._elevenlabs_available = False
            return False

    def get_status(self):
        """Return current TTS engine status."""
        if self._elevenlabs_available:
            return "ElevenLabs"
        elif self._sapi_voice:
            return "SAPI"
        else:
            return "pyttsx3"
