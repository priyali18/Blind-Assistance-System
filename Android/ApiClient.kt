package com.visioncompanion.app

import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Query
import java.io.File
import java.util.concurrent.TimeUnit

data class AnalyzeResponse(
    val success: Boolean,
    val description: String,
    val mode: String,
    val tokens_used: Int
)

data class ChatResponse(
    val success: Boolean,
    val response: String,
    val user_id: String
)

data class Obstacle(
    val `object`: String,
    val position: String,
    val distance: String,
    val warning: String
)

data class ObstacleData(
    val has_danger: Boolean,
    val urgency: String,
    val obstacles: List<Obstacle>,
    val safe_path: String
)

data class ObstacleResponse(
    val success: Boolean,
    val data: ObstacleData
)

data class TextResponse(
    val success: Boolean,
    val text_found: Boolean,
    val content: String
)

interface VisionCompanionApi {

    @GET("/")
    suspend fun healthCheck(): Response<Map<String, Any>>

    @Multipart
    @POST("/api/analyze-scene")
    suspend fun analyzeScene(
        @Part image: MultipartBody.Part,
        @Query("mode") mode: String = "general"
    ): Response<AnalyzeResponse>

    @Multipart
    @POST("/api/chat")
    suspend fun chat(
        @Part("message") message: RequestBody,
        @Part("user_id") userId: RequestBody,
        @Part image: MultipartBody.Part? = null
    ): Response<ChatResponse>

    @Multipart
    @POST("/api/detect-obstacles")
    suspend fun detectObstacles(
        @Part image: MultipartBody.Part
    ): Response<ObstacleResponse>

    @Multipart
    @POST("/api/read-text")
    suspend fun readText(
        @Part image: MultipartBody.Part
    ): Response<TextResponse>
}

object ApiClient {
    // These will be updated from the UI Settings
    var serverHost: String = "3.68.158.31"
    var userId: String = "User_" + (1000..9999).random()

    val BASE_URL: String get() = "http://$serverHost:8000/"
    val WS_URL: String get() = "ws://$serverHost:8000/ws/stream?user_id=$userId"

    private val client = OkHttpClient.Builder()
        .addInterceptor(
            HttpLoggingInterceptor().apply {
            }
        )
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    val api: VisionCompanionApi = Retrofit.Builder()
        .baseUrl(BASE_URL)
        .client(client)
        .addConverterFactory(GsonConverterFactory.create())
        .build()
        .create(VisionCompanionApi::class.java)

    fun createImagePart(file: File): MultipartBody.Part {
        val body = file.asRequestBody("image/jpeg".toMediaTypeOrNull())
        return MultipartBody.Part.createFormData("image", file.name, body)
    }

    fun createTextBody(text: String): RequestBody {
        return text.toRequestBody("text/plain".toMediaTypeOrNull())
    }
}