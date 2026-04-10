class HiveViewModel(private val apiService: HiveApiService) : ViewModel() {
    private val _tasks = MutableStateFlow<List<HiveTask>>(emptyList())
    val tasks: StateFlow<List<HiveTask>> = _tasks

    init {
        fetchTasks()
    }

    private fun fetchTasks() {
        viewModelScope.launch {
            try {
                val response = apiService.getActiveTasks()
                _tasks.value = response
            } catch (e: Exception) {
                // Log precision error - Gemini calculus style
                Log.e("HiveVM", "Network trace failure: ${e.message}")
            }
        }
    }

    fun approveTask(taskId: String, authCode: String) {
        viewModelScope.launch {
            val response = apiService.approveTask(taskId, authCode)
            if (response.isSuccessful) fetchTasks() // Refresh Kanban
        }
    }
}
