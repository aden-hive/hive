import express from "express";
import {
  listIntegrations,
  getIntegration,
  configureIntegration,
  testIntegration,
  removeIntegration,
} from "../controllers/integrationController.js";

const router = express.Router();

// GET endpoints
router.get("/", listIntegrations);
router.get("/:name", getIntegration);
router.post("/:name/test", testIntegration);

// POST endpoints
router.post("/:name/configure", configureIntegration);

// DELETE endpoints
router.delete("/:name", removeIntegration);

export default router;
