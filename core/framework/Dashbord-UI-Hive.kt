@Composable
fun HiveDashboard(viewModel: HiveViewModel) {
    val tasks by viewModel.tasks.collectAsState()

    Column(modifier = Modifier.fillMaxSize().background(Color(0xFF0F172A)).padding(16.dp)) {
        Text(
            text = "ADEN HIVE MONITOR",
            style = MaterialTheme.typography.headlineMedium,
            color = Color.White,
            fontWeight = FontWeight.Bold
        )
        
        Spacer(modifier = Modifier.height(16.dp))

        LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            items(tasks) { task ->
                HiveTaskCard(task) { code ->
                    viewModel.approveTask(task.id, code)
                }
            }
        }
    }
}

@Composable
fun HiveTaskCard(task: HiveTask, onApprove: (String) -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFF1E293B)),
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Text(task.title, color = Color.White, fontWeight = FontWeight.Bold)
                StatusBadge(task.status)
            }
            Text(task.description, color = Color.LightGray, style = MaterialTheme.typography.bodySmall)
            
            if (task.status == "APPEALED") {
                Button(
                    onClick = { onApprove("123456") }, // Simulated 2FA input
                    modifier = Modifier.padding(top = 8.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF3B82F6))
                ) {
                    Text("Secure Approve (2FA)")
                }
            }
        }
    }
}

@Composable
fun StatusBadge(status: String) {
    val color = when(status) {
        "PASSED" -> Color(0xFF10A37F)
        "TESTING" -> Color(0xFF3B82F6)
        else -> Color.Gray
    }
    Surface(color = color.copy(alpha = 0.2f), shape = CircleShape) {
        Text(status, color = color, modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp), fontSize = 10.sp)
    }
}
