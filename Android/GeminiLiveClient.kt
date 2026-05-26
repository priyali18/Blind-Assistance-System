package com.visioncompanion.app

import android.util.Log
import com.google.gson.Gson
import okhttp3.*
import okio.ByteString
import java.util.concurrent.TimeUnit

/**
 * GeminiLiveClient handles the WebSocket connection to the walking assistant backend.
 * It supports streaming audio, video frames, and GPS data.
 */
class GeminiLiveClient(
    private val serverUrl: String,
    private val listener: GeminiLiveListener
) {
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS) // For WebSockets
        .build()

    private var webSocket: WebSocket? = null
    private val gson = Gson()

    interface GeminiLiveListener {
        fun onConnected()
        fun onDisconnected()
        fun onError(message: String)
        fun onAudioDataReceived(base64Audio: String)
        fun onTranscriptReceived(text: String)
        fun onTurnComplete()
    }

    fun connect() {
        Log.d(TAG, "🔌 Connecting to: $serverUrl")
        
        val request = try {
            Request.Builder()
                .url(serverUrl)
                .build()
        } catch (e: Exception) {
            Log.e(TAG, "❌ Invalid URL: $serverUrl", e)
            listener.onError("Invalid Server URL: $serverUrl")
            return
        }

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d(TAG, "✅ WebSocket Connected to $serverUrl")
                listener.onConnected()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val map = gson.fromJson(text, Map::class.java)
                    
                    if (map.containsKey("audio")) {
                        listener.onAudioDataReceived(map["audio"] as String)
                    }
                    
                    if (map.containsKey("transcript")) {
                        listener.onTranscriptReceived(map["transcript"] as String)
                    }

                    if (map.containsKey("turn_complete")) {
                        listener.onTurnComplete()
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Error parsing message: ${e.message}")
                }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket Closing: $reason")
                webSocket.close(1000, null)
                listener.onDisconnected()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "❌ WebSocket Failure: ${t.message}")
                listener.onError(t.message ?: "Unknown connection error")
            }
        })
    }

    fun disconnect() {
        webSocket?.close(1000, "User requested disconnect")
        webSocket = null
    }

    /**
     * Sends binary audio data to the backend.
     */
    fun sendAudio(base64Audio: String) {
        val payload = mapOf("audio" to base64Audio)
        sendJson(payload)
    }

    /**
     * Sends a video frame (JPEG) to the backend.
     */
    fun sendVideoFrame(base64Frame: String) {
        val payload = mapOf("frame" to base64Frame)
        sendJson(payload)
    }

    /**
     * Sends location data to the backend.
     */
    fun sendLocation(lat: Double, lng: Double) {
        val payload = mapOf("lat" to lat, "lng" to lng)
        sendJson(payload)
    }

    /**
     * Sends manual VAD signals.
     */
    fun sendControlSignal(speechStart: Boolean? = null, speechEnd: Boolean? = null) {
        val payload = mutableMapOf<String, Any>()
        speechStart?.let { payload["speech_start"] = it }
        speechEnd?.let { payload["speech_end"] = it }
        sendJson(payload)
    }

    private fun sendJson(payload: Any) {
        val json = gson.toJson(payload)
        webSocket?.send(json)
    }

    companion object {
        private const val TAG = "GeminiLiveClient"
    }
}
