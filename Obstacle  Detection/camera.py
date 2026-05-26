"""
============================================
Module: Camera (Threaded)
============================================
Handles webcam access with a background reader
thread so the main loop is never blocked by
slow camera hardware.

Architecture:
    - Background thread continuously calls cap.read()
    - read_frame() returns the latest cached frame instantly
    - Works even if camera only delivers 1 FPS
    - Display loop stays smooth at 30+ FPS

Windows Fix:
    Uses DirectShow (CAP_DSHOW) backend instead of
    the default MSMF backend, which causes
    "can't grab frame" errors on many Windows systems.
============================================
"""

import cv2
import time
import os
import threading


class Camera:
    """
    Threaded camera with instant frame access.

    The background thread continuously reads from the camera.
    read_frame() returns the latest frame without blocking.

    Usage:
        cam = Camera(camera_index=0, width=640, height=480)
        cam.start()
        frame = cam.read_frame()   # Returns instantly
        cam.stop()
    """

    def __init__(self, camera_index=0, width=640, height=480):
        """
        Initialize camera settings.

        Args:
            camera_index (int): Camera device index (0 = default webcam)
            width (int): Desired frame width in pixels
            height (int): Desired frame height in pixels
        """
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.cap = None
        self.is_running = False

        # Threaded reader state
        self._frame = None              # Latest frame (shared with thread)
        self._frame_lock = threading.Lock()
        self._reader_thread = None
        self._new_frame_flag = False     # True when a fresh frame is available
        self._camera_fps = 0.0           # Measured camera hardware FPS

        # Suppress OpenCV MSMF warnings on Windows
        os.environ["OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"] = "0"

    def start(self):
        """
        Open the camera and start the background reader thread.

        Returns:
            bool: True if camera opened successfully, False otherwise
        """
        # Release any existing capture first
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass

        # Try DirectShow backend first (stable on Windows),
        # then fall back to default backend
        backends = [
            (cv2.CAP_DSHOW, "DirectShow"),
            (cv2.CAP_ANY, "Default"),
        ]

        for backend, name in backends:
            self.cap = cv2.VideoCapture(self.camera_index, backend)
            if self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self.cap.set(cv2.CAP_PROP_FPS, 30)

                actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

                # Read first frame to initialize
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    with self._frame_lock:
                        self._frame = frame

                self.is_running = True

                # Start background reader thread
                self._reader_thread = threading.Thread(
                    target=self._reader_loop,
                    daemon=True,
                    name="CameraReader"
                )
                self._reader_thread.start()

                print(f"[Camera] Started via {name} ({actual_w}x{actual_h}, threaded reader)")
                return True
            else:
                self.cap.release()

        print(f"[Camera] ERROR: Cannot open camera {self.camera_index}")
        print("[Camera] Tip: Close any other app using the camera and retry")
        return False

    def _reader_loop(self):
        """
        Background thread: continuously reads frames from the camera.
        This absorbs the blocking cap.read() so the main loop stays fast.
        """
        fail_count = 0
        frame_count = 0
        fps_start = time.time()

        while self.is_running:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(0.1)
                continue

            ret, frame = self.cap.read()

            if ret and frame is not None:
                with self._frame_lock:
                    self._frame = frame
                    self._new_frame_flag = True
                fail_count = 0
                frame_count += 1

                # Measure actual camera FPS
                elapsed = time.time() - fps_start
                if elapsed >= 3.0:
                    self._camera_fps = frame_count / elapsed
                    frame_count = 0
                    fps_start = time.time()
            else:
                fail_count += 1
                if fail_count >= 20:
                    print("[Camera] Reader: too many failures, pausing...")
                    time.sleep(1)
                    fail_count = 0

    def read_frame(self):
        """
        Return the latest frame instantly (non-blocking).

        Returns:
            numpy.ndarray or None: The latest captured frame (BGR),
                                   or None if no frame available yet.
        """
        with self._frame_lock:
            return self._frame

    def has_new_frame(self):
        """Check if a new frame has arrived since the last check."""
        with self._frame_lock:
            if self._new_frame_flag:
                self._new_frame_flag = False
                return True
            return False

    def get_camera_fps(self):
        """Return the measured camera hardware FPS."""
        return self._camera_fps

    def stop(self):
        """Stop the reader thread and release camera resources."""
        self.is_running = False

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3)

        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            print("[Camera] Stopped and released")

    def __del__(self):
        """Ensure camera is released when object is destroyed."""
        self.stop()
