# Bmaps: Blind Assistance & Smart Navigation System 👨‍🦯🚀

Bmaps is a state-of-the-art navigation and assistance system designed for visually impaired individuals. It combines real-time computer vision, advanced AI (Google Gemini), and geolocation services to provide a safer and more independent way to navigate the world.

---

## 🌟 Key Features

- **Real-time Obstacle Detection:** Uses **YOLOv8** to identify chairs, people, vehicles, and other hazards with high speed and precision.
- **Intelligent Navigation Engine:** A custom decision engine that provides immediate voice guidance (e.g., "Stop", "Move Left", "Path Clear").
- **Multimodal AI Integration:** Powered by **Google Gemini**, allowing users to ask natural language questions about their environment.
- **Smart Mapping & Geolocation:** Integrated with **Google Maps API** for real-time location tracking and finding nearby places like pharmacies, hospitals, or restaurants.
- **Hybrid Client Support:**
    - **Android App:** Feature-rich mobile client with CameraX integration and real-time audio streaming.
    - **Python Desktop Client:** Lightweight client for testing and local navigation.

---

## 🏗️ System Architecture

The system is composed of three main modules:

1.  **Android Client (`/Android`):** The primary user interface. It captures video and audio streams, handles voice commands, and provides feedback to the user via speech.
2.  **FastAPI Backend (`/Bmaps`):** The central brain. It orchestrates communication between the mobile app, the Gemini AI model, and Google Maps services. It also processes vision data using the navigation engine.
3.  **Obstacle Detection Module (`/Obstacle Detection`):** A standalone Python module focused on local computer vision tasks, including YOLOv8 detection and navigation fusion.

---

## 🛠️ Tech Stack

- **AI/ML:** Ultralytics YOLOv8, Google Gemini API
- **Backend:** FastAPI, WebSockets, Uvicorn
- **Mapping:** Google Maps Platform (Directions, Places, Geocoding)
- **Mobile:** Android (Kotlin, Jetpack Compose, CameraX, Retrofit)
- **Computer Vision:** OpenCV, NumPy
- **Audio:** PyAudio, PyTTSX3

---

## 🚀 Getting Started

### Prerequisites

- Python 3.9+
- Android Studio (for mobile development)
- Google Cloud API Key (with Gemini and Maps enabled)

### Backend Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/yourusername/blind-assistance-system.git
    cd blind-assistance-system
    ```

2.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Environment Variables:**
    Create a `.env` file in the `Bmaps/` directory:
    ```env
    GEMINI_API_KEY=your_gemini_api_key
    GOOGLE_MAPS_API_KEY=your_google_maps_api_key
    ```

4.  **Run the Server:**
    ```bash
    cd Bmaps
    python server.py
    ```

### Android App Setup

1.  Open the `Android` folder in **Android Studio**.
2.  Update the `BASE_URL` in `ApiClient.kt` or `GeminiLiveClient.kt` to point to your server's IP address.
3.  Build and run the app on a physical Android device.

---

## 📂 Project Structure

```text
├── Android/                # Kotlin Android App source code
├── Bmaps/                  # FastAPI Server and Gemini integration
├── Obstacle Detection/     # YOLOv8 logic and navigation engines
└── README.md               # You are here!
```

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
