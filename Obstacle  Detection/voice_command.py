"""
============================================
Module: Voice Command Recognition
============================================
Listens for voice commands via microphone to
control the navigation system.

Supported Commands:
    - "start navigation" / "start" / "go" / "begin"
    - "stop navigation" / "stop" / "halt" / "pause"

Key Design:
    - Runs in a background thread (non-blocking)
    - Uses Google Speech Recognition (free, online)
    - Callback-based: fires a function when command detected
    - Tolerant of noise and partial matches
============================================
"""

import threading
import time
import speech_recognition as sr


class VoiceCommandListener:
    """
    Listens for voice commands and triggers callbacks.

    Usage:
        def on_command(cmd):
            if cmd == "start":
                print("Starting!")
            elif cmd == "stop":
                print("Stopping!")

        listener = VoiceCommandListener(callback=on_command)
        listener.start()
        # ... later ...
        listener.stop()
    """

    # Command keyword mappings
    # Simple commands (exact match)
    COMMANDS = {
        "start": ["start navigation", "start", "go", "begin"],
        "stop": ["stop navigation", "stop", "halt", "pause", "quit"],
        "where": ["where am i", "my location", "current location"],
        "status": ["navigation status", "status"],
        "yes": ["yes", "yeah", "yep", "sure", "ok", "okay"],
        "no": ["no", "nope", "cancel"],
    }

    # Prefix commands (extract the rest as argument)
    # E.g., "find nearby hospital" → command="find_nearby", arg="hospital"
    PREFIX_COMMANDS = {
        "find_nearby": ["find nearby", "search nearby", "nearby", "find", "search for"],
        "navigate_to": ["navigate to", "take me to", "directions to", "go to", "route to"],
    }

    def __init__(self, callback=None, energy_threshold=300,
                 pause_threshold=0.8, phrase_time_limit=5):
        """
        Initialize voice command listener.

        Args:
            callback (callable): Function called with command name
                                 when a command is recognized.
                                 Signature: callback(command_str)
            energy_threshold (int): Minimum audio energy to consider
                                    as speech (higher = less sensitive)
            pause_threshold (float): Seconds of silence to mark end of phrase
            phrase_time_limit (int): Max seconds to listen for a single phrase
        """
        self.callback = callback
        self.is_running = False
        self.is_listening = False
        self.listener_thread = None
        self._debug_count = 0  # Track listen cycles for debug

        # Speech recognizer setup
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = energy_threshold
        self.recognizer.pause_threshold = pause_threshold
        self.recognizer.dynamic_energy_threshold = True
        self.phrase_time_limit = phrase_time_limit

        # Microphone
        self.microphone = None

    def start(self):
        """Start listening for voice commands in a background thread."""
        if self.is_running:
            return

        # Test microphone access
        try:
            self.microphone = sr.Microphone()
            # Calibrate for ambient noise
            with self.microphone as source:
                print("[VoiceCmd] Calibrating microphone for ambient noise...")
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
            print(f"[VoiceCmd] Energy threshold: {self.recognizer.energy_threshold:.0f}")
        except Exception as e:
            print(f"[VoiceCmd] ERROR: Microphone not available: {e}")
            print("[VoiceCmd] Voice commands disabled. Use keyboard instead.")
            return

        self.is_running = True
        self.is_listening = True
        self.listener_thread = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name="VoiceCommandListener"
        )
        self.listener_thread.start()
        print("[VoiceCmd] Listening for commands (say 'start' or 'stop')...")

    def stop(self):
        """Stop the listener thread."""
        self.is_running = False
        self.is_listening = False

        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=3)

        print("[VoiceCmd] Stopped")

    def _listen_loop(self):
        """Background loop that continuously listens for commands."""
        while self.is_running:
            if not self.is_listening:
                time.sleep(0.5)
                continue

            try:
                with self.microphone as source:
                    # Re-calibrate periodically for changing noise levels
                    self._debug_count += 1
                    if self._debug_count % 20 == 1:
                        self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                        print(f"[VoiceCmd] Listening... (threshold={self.recognizer.energy_threshold:.0f})")

                    # Listen for a phrase (blocks until speech detected or timeout)
                    audio = self.recognizer.listen(
                        source,
                        timeout=4,
                        phrase_time_limit=self.phrase_time_limit
                    )

                # Recognize speech using Google (free, no API key needed)
                text = self.recognizer.recognize_google(audio).lower().strip()
                print(f"[VoiceCmd] Heard: \"{text}\"")

                # Match against known commands
                command = self._match_command(text)
                if command and self.callback:
                    if isinstance(command, tuple):
                        print(f"[VoiceCmd] >>> Command: {command[0].upper()} arg='{command[1]}'")
                    else:
                        print(f"[VoiceCmd] >>> Command matched: {command.upper()}")
                    self.callback(command)
                else:
                    print(f"[VoiceCmd] (not a command, ignoring)")

            except sr.WaitTimeoutError:
                # No speech detected within timeout — normal, keep listening
                pass
            except sr.UnknownValueError:
                # Speech was detected but not understood
                pass
            except sr.RequestError as e:
                # Google API error (no internet?)
                print(f"[VoiceCmd] Speech API error: {e}")
                time.sleep(2)
            except Exception as e:
                if self.is_running:
                    print(f"[VoiceCmd] Error: {e}")
                time.sleep(1)

    def _match_command(self, text):
        """
        Match recognized text against known commands.

        Handles two types:
        1. Simple commands: "start", "stop", "where am i"
        2. Prefix commands: "find nearby hospital" → ("find_nearby", "hospital")

        Args:
            text (str): Recognized speech text (lowercase)

        Returns:
            str or tuple or None:
                - str: Simple command name ("start", "stop")
                - tuple: (command, argument) for prefix commands
                - None: No match
        """
        # Check prefix commands FIRST (longer, more specific)
        for command, prefixes in self.PREFIX_COMMANDS.items():
            for prefix in prefixes:
                if prefix in text:
                    # Extract the argument after the prefix
                    idx = text.index(prefix) + len(prefix)
                    arg = text[idx:].strip()
                    if arg:  # Only match if there's an argument
                        return (command, arg)

        # Check simple commands
        for command, keywords in self.COMMANDS.items():
            for keyword in keywords:
                if keyword in text:
                    return command

        return None

    def pause_listening(self):
        """Temporarily pause listening (e.g., while TTS is speaking)."""
        self.is_listening = False

    def resume_listening(self):
        """Resume listening after a pause."""
        self.is_listening = True
