package com.visioncompanion.app

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.os.Bundle
import android.util.Base64
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    private val viewModel: GeminiViewModel by viewModels()
    private val cameraExecutor = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (!hasPermissions()) {
            ActivityCompat.requestPermissions(this, arrayOf(
                Manifest.permission.CAMERA,
                Manifest.permission.RECORD_AUDIO,
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION
            ), 10)
        }

        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = Color.Black) {
                    VisionCompanionApp(viewModel, cameraExecutor)
                }
            }
        }
    }

    private fun hasPermissions() = arrayOf(
        Manifest.permission.CAMERA,
        Manifest.permission.RECORD_AUDIO,
        Manifest.permission.ACCESS_FINE_LOCATION,
        Manifest.permission.ACCESS_COARSE_LOCATION
    ).all {
        ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraExecutor.shutdown()
    }
}

@Composable
fun VisionCompanionApp(viewModel: GeminiViewModel, cameraExecutor: java.util.concurrent.ExecutorService) {
    Box(modifier = Modifier.fillMaxSize()) {
        // Full screen camera background
        CameraPreview(
            isStreaming = viewModel.isStreaming,
            cameraExecutor = cameraExecutor,
            onFrameCaptured = { viewModel.sendVideoFrame(it) }
        )

        // Overlay UI
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(24.dp),
            verticalArrangement = Arrangement.Bottom,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            // Header with Settings
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End
            ) {
                IconButton(
                    onClick = { viewModel.showSettings = true },
                    modifier = Modifier.background(Color.Black.copy(alpha = 0.5f), CircleShape)
                ) {
                    Icon(Icons.Default.Settings, contentDescription = "Settings", tint = Color.White)
                }
            }

            if (viewModel.showSettings) {
                SettingsDialog(viewModel)
            }

            Spacer(modifier = Modifier.weight(1f))

            // Status Card
            Surface(
                color = Color.Black.copy(alpha = 0.7f),
                shape = RoundedCornerShape(20.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 16.dp)
            ) {
                Column(modifier = Modifier.padding(20.dp)) {
                    Text(
                        text = viewModel.statusText.uppercase(),
                        color = if (viewModel.isStreaming) {
                            if (viewModel.isMicOpen) Color(0xFF00E676) else Color(0xFF2196F3)
                        } else Color.Gray,
                        fontWeight = FontWeight.Bold,
                        fontSize = 12.sp,
                        letterSpacing = 1.sp
                    )
                    
                    if (viewModel.lastTranscript.isNotEmpty()) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = viewModel.lastTranscript,
                            color = Color.White,
                            fontSize = 18.sp,
                            lineHeight = 24.sp
                        )
                    }
                }
            }

            // MIC BUTTON
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 16.dp),
                horizontalArrangement = Arrangement.Center
            ) {
                IconButton(
                    onClick = { viewModel.toggleMic() },
                    modifier = Modifier
                        .size(80.dp)
                        .background(
                            color = if (viewModel.isMicOpen) Color(0xFF00E676) else Color(0xFF2196F3).copy(alpha = 0.2f),
                            shape = CircleShape
                        ),
                    enabled = viewModel.isStreaming
                ) {
                    Icon(
                        imageVector = if (viewModel.isMicOpen) Icons.Default.Mic else Icons.Default.MicOff,
                        contentDescription = "Mic",
                        tint = if (viewModel.isMicOpen) Color.Black else Color.White,
                        modifier = Modifier.size(36.dp)
                    )
                }
            }

            // Minimalist Toggle Button
            Button(
                onClick = { viewModel.toggleStreaming() },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(88.dp),
                shape = RoundedCornerShape(24.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (viewModel.isStreaming) Color(0xFF00E676) else Color(0xFF1A237E)
                ),
                elevation = ButtonDefaults.buttonElevation(defaultElevation = 8.dp)
            ) {
                Text(
                    text = if (viewModel.isStreaming) "STOP ASSISTANT" else "START ASSISTANT",
                    fontSize = 20.sp,
                    fontWeight = FontWeight.ExtraBold,
                    color = if (viewModel.isStreaming) Color.Black else Color.White
                )
            }
        }
    }
}

@Composable
fun SettingsDialog(viewModel: GeminiViewModel) {
    var host by remember { mutableStateOf(ApiClient.serverHost) }
    var uid by remember { mutableStateOf(ApiClient.userId) }

    AlertDialog(
        onDismissRequest = { viewModel.showSettings = false },
        title = { Text("Connection Settings") },
        text = {
            Column {
                OutlinedTextField(
                    value = host,
                    onValueChange = { host = it },
                    label = { Text("Server IP / Host") },
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = uid,
                    onValueChange = { uid = it },
                    label = { Text("Your User ID (Identifier)") },
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            Button(onClick = {
                ApiClient.serverHost = host
                ApiClient.userId = uid
                viewModel.showSettings = false
                viewModel.reconnect()
            }) {
                Text("Save & Connect")
            }
        }
    )
}

@Composable
fun CameraPreview(
    isStreaming: Boolean,
    cameraExecutor: java.util.concurrent.ExecutorService,
    onFrameCaptured: (String) -> Unit
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember { PreviewView(context) }
    var lastFrameTime by remember { mutableStateOf(0L) }

    AndroidView(
        factory = { previewView },
        modifier = Modifier.fillMaxSize()
    ) { view ->
        val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
        cameraProviderFuture.addListener({
            val cameraProvider = cameraProviderFuture.get()
            
            val preview = Preview.Builder().build().also {
                it.setSurfaceProvider(view.surfaceProvider)
            }

            val imageAnalysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                .build()
                .also {
                    it.setAnalyzer(cameraExecutor) { imageProxy ->
                        if (isStreaming) {
                            val currentTime = System.currentTimeMillis()
                            if (currentTime - lastFrameTime > 500) { // 2 FPS
                                val rawBitmap = imageProxyToBitmap(imageProxy)
                                if (rawBitmap != null) {
                                    val matrix = android.graphics.Matrix()
                                    matrix.postRotate(90f)
                                    val bitmap = Bitmap.createBitmap(rawBitmap, 0, 0, rawBitmap.width, rawBitmap.height, matrix, true)
                                    
                                    val outputStream = ByteArrayOutputStream()
                                    bitmap.compress(Bitmap.CompressFormat.JPEG, 50, outputStream)
                                    val base64String = Base64.encodeToString(outputStream.toByteArray(), Base64.NO_WRAP)
                                    onFrameCaptured(base64String)
                                }
                                lastFrameTime = currentTime
                            }
                        }
                        imageProxy.close()
                    }
                }

            try {
                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    imageAnalysis
                )
            } catch (e: Exception) {
                Log.e("CameraPreview", "Use case binding failed", e)
            }
        }, ContextCompat.getMainExecutor(context))
    }
}

private fun imageProxyToBitmap(image: ImageProxy): Bitmap? {
    val yBuffer = image.planes[0].buffer
    val uBuffer = image.planes[1].buffer
    val vBuffer = image.planes[2].buffer

    val ySize = yBuffer.remaining()
    val uSize = uBuffer.remaining()
    val vSize = vBuffer.remaining()

    val nv21 = ByteArray(ySize + uSize + vSize)
    yBuffer.get(nv21, 0, ySize)
    vBuffer.get(nv21, ySize, vSize)
    uBuffer.get(nv21, ySize + vSize, uSize)

    val yuvImage = YuvImage(nv21, ImageFormat.NV21, image.width, image.height, null)
    val out = ByteArrayOutputStream()
    yuvImage.compressToJpeg(Rect(0, 0, yuvImage.width, yuvImage.height), 100, out)
    val imageBytes = out.toByteArray()
    return BitmapFactory.decodeByteArray(imageBytes, 0, imageBytes.size)
}
