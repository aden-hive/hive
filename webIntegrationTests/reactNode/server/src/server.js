import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import hiveRoutes from "./routes/hiveRoutes.js";
import integrationRoutes from "./routes/integrationRoutes.js";

dotenv.config();

const app = express();
const PORT = process.env.PORT || 5000;

// Middleware
app.use(cors());
app.use(express.json());

// Routes
app.use("/api/hive", hiveRoutes);
app.use("/api/integrations", integrationRoutes);

// Health check
app.get("/api/health", (req, res) => {
  res.json({
    status: "Backend is running",
    version: "1.1.0",
    features: ["hive-agents", "integrations", "credentials"],
    timestamp: new Date().toISOString(),
  });
});

// Error handling
app.use((err, req, res, next) => {
  console.error("Error:", err.message);
  res.status(500).json({ error: err.message });
});

app.listen(PORT, () => {
  console.log(`🚀 Hive Dashboard Backend running on http://localhost:${PORT}`);
  console.log(`📦 Integrations API available at /api/integrations`);
});
