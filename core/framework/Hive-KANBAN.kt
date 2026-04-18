data class HiveTask(
    val id: String,
    val title: String,
    val description: String,
    val status: String, // e.g., "TESTING", "APPEALED", "FAILED"
    val securityContext: String
)

interface HiveApiService {
    @GET("kanban/tasks")
    suspend fun getActiveTasks(): List<HiveTask>

    @POST("kanban/appeal/{id}")
    suspend fun approveTask(@Path("id") taskId: String, @Header("X-2FA-Code") code: String): Response<Unit>
}
