package com.visioncompanion.app

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.util.Base64
import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.app.ActivityCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.android.gms.location.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

class GeminiViewModel(application: Application) : AndroidViewModel(application), GeminiLiveClient.GeminiLiveListener {

    var isStreaming by mutableStateOf(false)
    var isMicOpen by mutableStateOf(false)
    var statusText by mutableStateOf("Ready to assist")
    var lastTranscript by mutableStateOf("")
    var isConnected by mutableStateOf(false)
    var showSettings by mutableStateOf(false)

    private var geminiClient: GeminiLiveClient? = null
    
    // GPS tracking
    private var fusedLocationClient: FusedLocationProviderClient? = null
    private var locationCallback: LocationCallback? = null

    // Audio Capture
    private var audioRecord: AudioRecord? = null
    private var audioCaptureJob: Job? = null
    private val SAMPLE_RATE = 16000
    private var bufferSizeCapture = 4096

    // Audio Playback
    private var audioTrack: AudioTrack? = null
    private val PLAYBACK_RATE = 24000

    init {
        try {
            // 1. Init GPS Client
            fusedLocationClient = LocationServices.getFusedLocationProviderClient(application)
            
            // 2. Init Gemini Client
            geminiClient = GeminiLiveClient(ApiClient.WS_URL, this)
            
            // 3. Calculate Capture Buffer
            val minRecordBuffer = AudioRecord.getMinBufferSize(
                SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
            )
            bufferSizeCapture = if (minRecordBuffer > 0) minRecordBuffer else 4096

            // 4. Init Audio Track (Playback)
            initAudioTrack()
            
            // 5. Connect and Start Tracking
            geminiClient?.connect()
            startLocationTracking()
            
        } catch (e: Exception) {
            Log.e("GeminiViewModel", "CRITICAL INIT ERROR: ${e.message}")
            statusText = "Initialization Error"
        }
    }

    private fun startLocationTracking() {
        try {
            val context = getApplication<Application>().applicationContext
            if (ActivityCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
                Log.e("GeminiViewModel", "Location permission NOT granted")
                return
            }

            val locationRequest = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 5000)
                .setMinUpdateIntervalMillis(2000)
                .build()

            locationCallback = object : LocationCallback() {
                override fun onLocationResult(locationResult: LocationResult) {
                    for (location in locationResult.locations) {
                        Log.d("GeminiViewModel", "📍 GPS: ${location.latitude}, ${location.longitude}")
                        geminiClient?.sendLocation(location.latitude, location.longitude)
                    }
                }
            }

            fusedLocationClient?.requestLocationUpdates(locationRequest, locationCallback!!, android.os.Looper.getMainLooper())
        } catch (e: Exception) {
            Log.e("GeminiViewModel", "Failed to start location tracking: ${e.message}")
        }
    }

    fun reconnect() {
        viewModelScope.launch {
            try {
                geminiClient?.disconnect()
                geminiClient = GeminiLiveClient(ApiClient.WS_URL, this@GeminiViewModel)
                geminiClient?.connect()
            } catch (e: Exception) {
                Log.e("GeminiViewModel", "Reconnect failed: ${e.message}")
            }
        }
    }

    fun toggleStreaming() {
        if (!isStreaming) {
            startStreaming()
        } else {
            stopStreaming()
        }
    }

    fun toggleMic() {
        if (!isStreaming) return
        
        isMicOpen = !isMicOpen
        if (isMicOpen) {
            geminiClient?.sendControlSignal(speechStart = true)
            statusText = "Listening..."
        } else {
            geminiClient?.sendControlSignal(speechEnd = true)
            statusText = "Thinking..."
        }
    }

    private fun startStreaming() {
        isStreaming = true
        statusText = "Stream Active"
        startAudioCapture()
    }

    private fun stopStreaming() {
        isStreaming = false
        isMicOpen = false
        statusText = "Stopped"
        
        audioCaptureJob?.cancel()
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null
    }

    private fun startAudioCapture() {
        val context = getApplication<Application>().applicationContext
        if (ActivityCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) return

        try {
            audioRecord = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufferSizeCapture
            )

            audioRecord?.startRecording()
            
            audioCaptureJob = viewModelScope.launch(Dispatchers.IO) {
                val buffer = ByteArray(bufferSizeCapture)
                while (isStreaming) {
                    val read = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                    if (read > 0 && isMicOpen) {
                        val base64String = Base64.encodeToString(buffer, 0, read, Base64.NO_WRAP)
                        geminiClient?.sendAudio(base64String)
                    }
                }
            }
        } catch (e: Exception) {
            Log.e("GeminiViewModel", "Audio capture failed: ${e.message}")
        }
    }

    private fun initAudioTrack() {
        try {
            val minBufferSize = AudioTrack.getMinBufferSize(
                PLAYBACK_RATE,
                AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT
            )
            val bufferSize = if (minBufferSize > 0) minBufferSize else bufferSizeCapture

            audioTrack = AudioTrack.Builder()
                .setAudioAttributes(AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build())
                .setAudioFormat(AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(PLAYBACK_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build())
                .setBufferSizeInBytes(bufferSize)
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build()
        } catch (e: Exception) {
            Log.e("GeminiViewModel", "Failed to init AudioTrack: ${e.message}")
        }
    }

    fun sendVideoFrame(base64: String) {
        if (isStreaming) {
            geminiClient?.sendVideoFrame(base64)
        }
    }

    override fun onConnected() {
        isConnected = true
        statusText = "Connected"
    }

    override fun onDisconnected() {
        isConnected = false
        statusText = "Disconnected"
        stopStreaming()
    }

    override fun onError(message: String) {
        statusText = "Error: $message"
    }

    override fun onAudioDataReceived(base64Audio: String) {
        try {
            val audioData = Base64.decode(base64Audio, Base64.DEFAULT)
            audioTrack?.let {
                it.write(audioData, 0, audioData.size)
                it.play()
            }
        } catch (e: Exception) {
            Log.e("GeminiViewModel", "Playback error: ${e.message}")
        }
    }

    override fun onTranscriptReceived(text: String) {
        lastTranscript = text
    }

    override fun onTurnComplete() {
        statusText = "Listening..."
    }

    override fun onCleared() {
        super.onCleared()
        stopStreaming()
        locationCallback?.let { fusedLocationClient?.removeLocationUpdates(it) }
        geminiClient?.disconnect()
        audioTrack?.release()
    }
}
