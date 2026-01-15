/**
 * LLM Pricing Service
 *
 * Centralized pricing table for calculating costs by provider and model.
 * Prices are stored in MongoDB and cached in memory for performance.
 * Prices are in USD per 1M tokens (industry standard).
 *
 * Sources:
 * - OpenAI: https://openai.com/pricing
 * - Anthropic: https://www.anthropic.com/pricing
 * - Google: https://ai.google.dev/pricing
 * - AWS Bedrock: https://aws.amazon.com/bedrock/pricing/
 */

// In-memory cache for pricing data
const pricingCache = new Map<string, PricingEntry>();
const aliasCacheMap = new Map<string, string>(); // model alias -> canonical model
let cacheLoadedAt: number | null = null;
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

interface PricingEntry {
  model: string;
  provider: string;
  input: number;
  output: number;
  cached_input: number;
  aliases: string[];
  effective_date?: Date;
  updated_at?: Date;
  source?: string;
}

interface PricingTableEntry {
  provider: string;
  input: number;
  output: number;
  cached_input: number;
  aliases: string[];
}

// Fallback pricing for unknown models (conservative estimate)
const DEFAULT_PRICING = { input: 1.00, output: 3.00, cached_input: 0.25 };

// Default pricing table for seeding - USD per 1M tokens
// Updated: 2025-01-01
const DEFAULT_PRICING_TABLE: Record<string, PricingTableEntry> = {
  // OpenAI Models
  "gpt-4o": { provider: "openai", input: 2.50, output: 10.00, cached_input: 1.25, aliases: ["gpt-4o-2024-11-20", "gpt-4o-2024-08-06"] },
  "gpt-4o-2024-05-13": { provider: "openai", input: 5.00, output: 15.00, cached_input: 2.50, aliases: [] },
  "gpt-4o-mini": { provider: "openai", input: 0.15, output: 0.60, cached_input: 0.075, aliases: ["gpt-4o-mini-2024-07-18"] },
  "gpt-4-turbo": { provider: "openai", input: 10.00, output: 30.00, cached_input: 5.00, aliases: ["gpt-4-turbo-2024-04-09", "gpt-4-turbo-preview"] },
  "gpt-4": { provider: "openai", input: 30.00, output: 60.00, cached_input: 15.00, aliases: ["gpt-4-0613"] },
  "gpt-3.5-turbo": { provider: "openai", input: 0.50, output: 1.50, cached_input: 0.25, aliases: ["gpt-3.5-turbo-0125"] },
  "o1": { provider: "openai", input: 15.00, output: 60.00, cached_input: 7.50, aliases: ["o1-2024-12-17", "o1-preview"] },
  "o1-mini": { provider: "openai", input: 3.00, output: 12.00, cached_input: 1.50, aliases: ["o1-mini-2024-09-12"] },
  "o3-mini": { provider: "openai", input: 1.10, output: 4.40, cached_input: 0.55, aliases: [] },

  // Anthropic Models
  "claude-3-5-sonnet-20241022": { provider: "anthropic", input: 3.00, output: 15.00, cached_input: 0.30, aliases: ["claude-3-5-sonnet-20240620", "claude-3-5-sonnet-latest"] },
  "claude-sonnet-4-20250514": { provider: "anthropic", input: 3.00, output: 15.00, cached_input: 0.30, aliases: ["claude-sonnet-4-5-20250929"] },
  "claude-3-5-haiku-20241022": { provider: "anthropic", input: 0.80, output: 4.00, cached_input: 0.08, aliases: ["claude-3-5-haiku-latest"] },
  "claude-3-opus-20240229": { provider: "anthropic", input: 15.00, output: 75.00, cached_input: 1.50, aliases: ["claude-3-opus-latest"] },
  "claude-3-sonnet-20240229": { provider: "anthropic", input: 3.00, output: 15.00, cached_input: 0.30, aliases: [] },
  "claude-3-haiku-20240307": { provider: "anthropic", input: 0.25, output: 1.25, cached_input: 0.025, aliases: [] },
  "claude-opus-4-5-20251101": { provider: "anthropic", input: 15.00, output: 75.00, cached_input: 1.50, aliases: ["claude-opus-4-20250514"] },

  // Google Models
  "gemini-2.0-flash": { provider: "google", input: 0.10, output: 0.40, cached_input: 0.025, aliases: ["gemini-2.0-flash-exp"] },
  "gemini-1.5-flash": { provider: "google", input: 0.075, output: 0.30, cached_input: 0.01875, aliases: ["gemini-1.5-flash-latest"] },
  "gemini-1.5-flash-8b": { provider: "google", input: 0.0375, output: 0.15, cached_input: 0.01, aliases: [] },
  "gemini-1.5-pro": { provider: "google", input: 1.25, output: 5.00, cached_input: 0.3125, aliases: ["gemini-1.5-pro-latest"] },
  "gemini-1.0-pro": { provider: "google", input: 0.50, output: 1.50, cached_input: 0.125, aliases: ["gemini-pro"] },
  "gemini-exp-1206": { provider: "google", input: 0.00, output: 0.00, cached_input: 0.00, aliases: [] },

  // AWS Bedrock - Claude (cross-region inference)
  "anthropic.claude-3-5-sonnet-20241022-v2:0": { provider: "bedrock", input: 3.00, output: 15.00, cached_input: 0.30, aliases: [] },
  "anthropic.claude-3-5-haiku-20241022-v1:0": { provider: "bedrock", input: 0.80, output: 4.00, cached_input: 0.08, aliases: [] },
  "anthropic.claude-3-opus-20240229-v1:0": { provider: "bedrock", input: 15.00, output: 75.00, cached_input: 1.50, aliases: [] },
  "anthropic.claude-3-sonnet-20240229-v1:0": { provider: "bedrock", input: 3.00, output: 15.00, cached_input: 0.30, aliases: [] },
  "anthropic.claude-3-haiku-20240307-v1:0": { provider: "bedrock", input: 0.25, output: 1.25, cached_input: 0.025, aliases: [] },

  // AWS Bedrock - Amazon Models
  "amazon.nova-pro-v1:0": { provider: "bedrock", input: 0.80, output: 3.20, cached_input: 0.20, aliases: [] },
  "amazon.nova-lite-v1:0": { provider: "bedrock", input: 0.06, output: 0.24, cached_input: 0.015, aliases: [] },
  "amazon.nova-micro-v1:0": { provider: "bedrock", input: 0.035, output: 0.14, cached_input: 0.00875, aliases: [] },
  "amazon.titan-text-express-v1": { provider: "bedrock", input: 0.20, output: 0.60, cached_input: 0.05, aliases: [] },
  "amazon.titan-text-lite-v1": { provider: "bedrock", input: 0.15, output: 0.20, cached_input: 0.0375, aliases: [] },

  // Mistral Models
  "mistral-large-latest": { provider: "mistral", input: 2.00, output: 6.00, cached_input: 0.50, aliases: ["mistral-large-2411"] },
  "mistral-medium-latest": { provider: "mistral", input: 2.70, output: 8.10, cached_input: 0.675, aliases: [] },
  "mistral-small-latest": { provider: "mistral", input: 0.20, output: 0.60, cached_input: 0.05, aliases: ["mistral-small-2409"] },
  "codestral-latest": { provider: "mistral", input: 0.30, output: 0.90, cached_input: 0.075, aliases: [] },
  "pixtral-large-latest": { provider: "mistral", input: 2.00, output: 6.00, cached_input: 0.50, aliases: [] },
  "ministral-8b-latest": { provider: "mistral", input: 0.10, output: 0.10, cached_input: 0.025, aliases: [] },
  "ministral-3b-latest": { provider: "mistral", input: 0.04, output: 0.04, cached_input: 0.01, aliases: [] },

  // Cohere Models
  "command-r-plus": { provider: "cohere", input: 2.50, output: 10.00, cached_input: 0.625, aliases: [] },
  "command-r": { provider: "cohere", input: 0.15, output: 0.60, cached_input: 0.0375, aliases: [] },
  "command": { provider: "cohere", input: 1.00, output: 2.00, cached_input: 0.25, aliases: [] },
  "command-light": { provider: "cohere", input: 0.30, output: 0.60, cached_input: 0.075, aliases: [] },

  // DeepSeek Models
  "deepseek-chat": { provider: "deepseek", input: 0.14, output: 0.28, cached_input: 0.014, aliases: [] },
  "deepseek-reasoner": { provider: "deepseek", input: 0.55, output: 2.19, cached_input: 0.055, aliases: [] },

  // Groq Models (inference pricing, not training)
  "llama-3.3-70b-versatile": { provider: "groq", input: 0.59, output: 0.79, cached_input: 0.15, aliases: [] },
  "llama-3.1-70b-versatile": { provider: "groq", input: 0.59, output: 0.79, cached_input: 0.15, aliases: [] },
  "llama-3.1-8b-instant": { provider: "groq", input: 0.05, output: 0.08, cached_input: 0.0125, aliases: [] },
  "llama-3.2-90b-vision-preview": { provider: "groq", input: 0.90, output: 0.90, cached_input: 0.225, aliases: [] },
  "mixtral-8x7b-32768": { provider: "groq", input: 0.24, output: 0.24, cached_input: 0.06, aliases: [] },
};

declare const _ACHO_MG_DB: { db: (name: string) => { collection: (name: string) => unknown } };
declare const _ACHO_MDB_CONFIG: { ERP_DBNAME: string };
declare const _ACHO_MDB_COLLECTIONS: { ADEN_LLM_PRICING: string };

interface MongoCollection {
  find: (query: Record<string, unknown>) => { toArray: () => Promise<unknown[]>; sort: (sort: Record<string, number>) => { toArray: () => Promise<unknown[]> } };
  findOne: (query: Record<string, unknown>) => Promise<unknown>;
  findOneAndUpdate: (query: Record<string, unknown>, update: Record<string, unknown>, options: Record<string, unknown>) => Promise<unknown>;
  deleteOne: (query: Record<string, unknown>) => Promise<{ deletedCount: number }>;
  insertOne: (doc: Record<string, unknown>) => Promise<unknown>;
  updateOne: (query: Record<string, unknown>, update: Record<string, unknown>) => Promise<unknown>;
}

/**
 * Get the MongoDB collection for pricing
 * @returns {Collection} MongoDB collection
 */
function getPricingCollection(): MongoCollection {
  const db = _ACHO_MG_DB.db(_ACHO_MDB_CONFIG.ERP_DBNAME);
  return db.collection(_ACHO_MDB_COLLECTIONS.ADEN_LLM_PRICING) as MongoCollection;
}

/**
 * Check if cache is still valid
 * @returns {boolean}
 */
function isCacheValid(): boolean {
  if (!cacheLoadedAt || pricingCache.size === 0) return false;
  return Date.now() - cacheLoadedAt < CACHE_TTL_MS;
}

interface DbPricingDoc {
  model: string;
  provider: string;
  input_per_1m: number;
  output_per_1m: number;
  cached_input_per_1m: number;
  aliases?: string[];
  effective_date?: Date;
  updated_at?: Date;
}

/**
 * Load pricing from MongoDB into memory cache
 * @param {boolean} force - Force reload even if cache is valid
 * @returns {Promise<Map>} Pricing cache
 */
async function loadPricingFromDb(force = false): Promise<Map<string, PricingEntry>> {
  if (!force && isCacheValid()) {
    return pricingCache;
  }

  try {
    const collection = getPricingCollection();
    const docs = await collection.find({}).toArray() as DbPricingDoc[];

    if (docs.length === 0) {
      console.log("[pricing_service] No pricing in DB, using defaults");
      loadFromDefaults();
      return pricingCache;
    }

    // Clear and rebuild cache
    pricingCache.clear();
    aliasCacheMap.clear();

    for (const doc of docs) {
      const pricing: PricingEntry = {
        model: doc.model,
        provider: doc.provider,
        input: doc.input_per_1m,
        output: doc.output_per_1m,
        cached_input: doc.cached_input_per_1m,
        aliases: doc.aliases || [],
        effective_date: doc.effective_date,
        updated_at: doc.updated_at,
      };
      pricingCache.set(doc.model.toLowerCase(), pricing);

      // Build alias map
      for (const alias of pricing.aliases) {
        aliasCacheMap.set(alias.toLowerCase(), doc.model.toLowerCase());
      }
    }

    cacheLoadedAt = Date.now();
    console.log(`[pricing_service] Loaded ${pricingCache.size} pricing entries from DB`);
    return pricingCache;
  } catch (err) {
    console.error("[pricing_service] Error loading from DB, using defaults:", (err as Error).message);
    loadFromDefaults();
    return pricingCache;
  }
}

/**
 * Load pricing from hardcoded defaults into cache
 */
function loadFromDefaults(): void {
  pricingCache.clear();
  aliasCacheMap.clear();

  for (const [model, data] of Object.entries(DEFAULT_PRICING_TABLE)) {
    const pricing: PricingEntry = {
      model,
      provider: data.provider,
      input: data.input,
      output: data.output,
      cached_input: data.cached_input,
      aliases: data.aliases || [],
      source: "default",
    };
    pricingCache.set(model.toLowerCase(), pricing);

    // Build alias map
    for (const alias of data.aliases || []) {
      aliasCacheMap.set(alias.toLowerCase(), model.toLowerCase());
    }
  }

  cacheLoadedAt = Date.now();
  console.log(`[pricing_service] Loaded ${pricingCache.size} pricing entries from defaults`);
}

/**
 * Invalidate cache to force reload on next access
 */
function invalidateCache(): void {
  cacheLoadedAt = null;
}

/**
 * Resolve model name to canonical form using aliases
 * @param {string} model - Model name (possibly an alias)
 * @returns {string} Canonical model name
 */
function resolveAlias(model: string): string | null {
  if (!model) return null;
  const lower = model.toLowerCase().trim();

  // Check if it's a direct match
  if (pricingCache.has(lower)) {
    return lower;
  }

  // Check alias map
  if (aliasCacheMap.has(lower)) {
    return aliasCacheMap.get(lower)!;
  }

  // Try partial matching for model families
  for (const [key, pricing] of pricingCache.entries()) {
    // Check if input starts with a known model prefix
    if (lower.startsWith(key) || key.startsWith(lower)) {
      return key;
    }
    // Check aliases
    for (const alias of pricing.aliases || []) {
      if (lower.startsWith(alias.toLowerCase()) || alias.toLowerCase().startsWith(lower)) {
        return key;
      }
    }
  }

  return lower;
}

interface ModelPricingResult {
  input: number;
  output: number;
  cached_input: number;
  model: string;
  provider: string;
  source: string;
}

/**
 * Get pricing for a model
 * @param {string} model - Model name
 * @param {string} provider - Provider name (optional, for disambiguation)
 * @returns {Promise<Object>} Pricing { input, output, cached_input } in USD per 1M tokens
 */
async function getModelPricing(model: string, provider: string | null = null): Promise<ModelPricingResult> {
  await loadPricingFromDb();

  const resolved = resolveAlias(model);

  // Try exact match
  if (resolved && pricingCache.has(resolved)) {
    const pricing = pricingCache.get(resolved)!;
    return {
      input: pricing.input,
      output: pricing.output,
      cached_input: pricing.cached_input,
      model: pricing.model,
      provider: pricing.provider,
      source: "db",
    };
  }

  // Try provider-prefixed lookup for Bedrock
  if (provider === "bedrock" || provider === "aws") {
    for (const [key, pricing] of pricingCache.entries()) {
      if (key.includes(resolved || "") || (resolved || "").includes(key.split(".").pop()?.split("-")[0] || "")) {
        return {
          input: pricing.input,
          output: pricing.output,
          cached_input: pricing.cached_input,
          model: pricing.model,
          provider: pricing.provider,
          source: "bedrock_match",
        };
      }
    }
  }

  // Return default pricing
  console.log(`[pricing_service] Unknown model: ${model}, using default pricing`);
  return {
    ...DEFAULT_PRICING,
    model: model,
    provider: provider || "unknown",
    source: "default",
  };
}

/**
 * Get model pricing synchronously (uses cached data)
 * @param {string} model - Model name
 * @returns {Object} Pricing { input, output, cached_input } in USD per 1M tokens
 */
function getModelPricingSync(model: string): ModelPricingResult {
  const resolved = resolveAlias(model);

  if (resolved && pricingCache.has(resolved)) {
    const cached = pricingCache.get(resolved)!;
    return {
      input: cached.input,
      output: cached.output,
      cached_input: cached.cached_input,
      model: cached.model,
      provider: cached.provider,
      source: "db",
    };
  }

  return { ...DEFAULT_PRICING, model, provider: "unknown", source: "default" };
}

interface CostCalculationParams {
  model: string;
  provider?: string;
  input_tokens?: number;
  output_tokens?: number;
  cached_tokens?: number;
}

interface CostResult {
  total: number;
  input_cost: number;
  output_cost: number;
  cached_cost: number;
  pricing: {
    model: string;
    source: string;
    input_per_1m: number;
    output_per_1m: number;
    cached_per_1m: number;
  };
}

/**
 * Calculate cost for a request (synchronous version using cached data)
 * @param {Object} params - Request parameters
 * @returns {Object} Cost breakdown { total, input_cost, output_cost, cached_cost, pricing }
 */
function calculateCostSync({ model, provider: _provider, input_tokens = 0, output_tokens = 0, cached_tokens = 0 }: CostCalculationParams): CostResult {
  const resolved = resolveAlias(model);
  let pricing: { input: number; output: number; cached_input: number; model: string; source: string };

  if (resolved && pricingCache.has(resolved)) {
    const cached = pricingCache.get(resolved)!;
    pricing = {
      input: cached.input,
      output: cached.output,
      cached_input: cached.cached_input,
      model: cached.model,
      source: "db",
    };
  } else {
    pricing = { ...DEFAULT_PRICING, model, source: "default" };
  }

  // Non-cached input tokens
  const nonCachedInput = Math.max(0, input_tokens - cached_tokens);

  // Calculate costs (pricing is per 1M tokens)
  const inputCost = (nonCachedInput / 1_000_000) * pricing.input;
  const outputCost = (output_tokens / 1_000_000) * pricing.output;
  const cachedCost = (cached_tokens / 1_000_000) * pricing.cached_input;

  const total = inputCost + outputCost + cachedCost;

  return {
    total,
    input_cost: inputCost,
    output_cost: outputCost,
    cached_cost: cachedCost,
    pricing: {
      model: pricing.model,
      source: pricing.source,
      input_per_1m: pricing.input,
      output_per_1m: pricing.output,
      cached_per_1m: pricing.cached_input,
    },
  };
}

/**
 * Calculate cost for a request (async version)
 * @param {Object} params - Request parameters
 * @returns {Promise<Object>} Cost breakdown { total, input_cost, output_cost, cached_cost, pricing }
 */
async function calculateCost(params: CostCalculationParams): Promise<CostResult> {
  await loadPricingFromDb();
  return calculateCostSync(params);
}

interface UpsertPricingInput {
  provider?: string;
  input_per_1m?: number;
  input?: number;
  output_per_1m?: number;
  output?: number;
  cached_input_per_1m?: number;
  cached_input?: number;
  aliases?: string[];
  effective_date?: Date;
}

/**
 * Upsert pricing for a model
 * @param {string} model - Model identifier
 * @param {Object} pricing - Pricing data
 * @param {string} userId - User making the change
 * @returns {Promise<Object>} Updated document
 */
async function upsertPricing(model: string, pricing: UpsertPricingInput, userId: string | null = null): Promise<unknown> {
  const collection = getPricingCollection();

  const doc = {
    model: model,
    provider: pricing.provider,
    input_per_1m: pricing.input_per_1m ?? pricing.input,
    output_per_1m: pricing.output_per_1m ?? pricing.output,
    cached_input_per_1m: pricing.cached_input_per_1m ?? pricing.cached_input,
    aliases: pricing.aliases || [],
    effective_date: pricing.effective_date || new Date(),
    updated_at: new Date(),
    updated_by: userId,
  };

  const result = await collection.findOneAndUpdate(
    { model: model },
    { $set: doc },
    { upsert: true, returnDocument: "after" }
  );

  // Invalidate cache to force reload
  invalidateCache();

  return result;
}

/**
 * Delete pricing for a model
 * @param {string} model - Model identifier
 * @returns {Promise<boolean>} True if deleted
 */
async function deletePricing(model: string): Promise<boolean> {
  const collection = getPricingCollection();
  const result = await collection.deleteOne({ model: model });

  // Invalidate cache to force reload
  invalidateCache();

  return result.deletedCount > 0;
}

interface SeedResult {
  inserted: number;
  updated: number;
  skipped: number;
  errors: { model: string; error: string }[];
}

/**
 * Seed default pricing to MongoDB
 * @param {string} userId - User making the change
 * @param {boolean} overwrite - If true, overwrite existing entries
 * @returns {Promise<Object>} Seed results
 */
async function seedDefaultPricing(userId: string | null = null, overwrite = false): Promise<SeedResult> {
  const collection = getPricingCollection();
  const results: SeedResult = { inserted: 0, updated: 0, skipped: 0, errors: [] };

  for (const [model, data] of Object.entries(DEFAULT_PRICING_TABLE)) {
    try {
      const existing = await collection.findOne({ model });

      if (existing && !overwrite) {
        results.skipped++;
        continue;
      }

      const doc = {
        model,
        provider: data.provider,
        input_per_1m: data.input,
        output_per_1m: data.output,
        cached_input_per_1m: data.cached_input,
        aliases: data.aliases || [],
        effective_date: new Date(),
        updated_at: new Date(),
        updated_by: userId,
      };

      if (existing) {
        await collection.updateOne({ model }, { $set: doc });
        results.updated++;
      } else {
        await collection.insertOne(doc);
        results.inserted++;
      }
    } catch (err) {
      results.errors.push({ model, error: (err as Error).message });
    }
  }

  // Invalidate cache to force reload
  invalidateCache();

  console.log(`[pricing_service] Seeded pricing: ${results.inserted} inserted, ${results.updated} updated, ${results.skipped} skipped`);
  return results;
}

interface AllPricingResult {
  [key: string]: {
    provider: string;
    input: number;
    output: number;
    cached_input: number;
    aliases: string[];
  };
}

/**
 * Get all available pricing data
 * @returns {Promise<Object>} Full pricing table
 */
async function getAllPricing(): Promise<AllPricingResult> {
  await loadPricingFromDb();

  const result: AllPricingResult = {};
  for (const [, pricing] of pricingCache.entries()) {
    result[pricing.model] = {
      provider: pricing.provider,
      input: pricing.input,
      output: pricing.output,
      cached_input: pricing.cached_input,
      aliases: pricing.aliases,
    };
  }
  return result;
}

interface PricingByProviderResult {
  [provider: string]: {
    [model: string]: {
      input: number;
      output: number;
      cached_input: number;
      aliases: string[];
    };
  };
}

/**
 * Get pricing summary grouped by provider
 * @returns {Promise<Object>} Pricing by provider
 */
async function getPricingByProvider(): Promise<PricingByProviderResult> {
  await loadPricingFromDb();

  const byProvider: PricingByProviderResult = {};

  for (const [, pricing] of pricingCache.entries()) {
    const provider = pricing.provider || "other";
    if (!byProvider[provider]) {
      byProvider[provider] = {};
    }
    byProvider[provider][pricing.model] = {
      input: pricing.input,
      output: pricing.output,
      cached_input: pricing.cached_input,
      aliases: pricing.aliases,
    };
  }

  return byProvider;
}

interface DegradationModel {
  model: string;
  label: string;
  input_cost: number;
  output_cost: number;
  avg_cost: number;
}

interface DegradationTargetsResult {
  providers: string[];
  models: { [provider: string]: DegradationModel[] };
}

/**
 * Get degradation target models grouped by provider
 * Returns models sorted by cost (cheapest first) for budget control "degrade" mode
 * @returns {Promise<Object>} { providers: [...], models: { provider: [...] } }
 */
async function getDegradationTargets(): Promise<DegradationTargetsResult> {
  await loadPricingFromDb();

  const byProvider: { [provider: string]: DegradationModel[] } = {};

  for (const [, pricing] of pricingCache.entries()) {
    const provider = pricing.provider || "other";
    if (!byProvider[provider]) {
      byProvider[provider] = [];
    }

    // Calculate average cost per 1M tokens (input + output) / 2
    const avgCost = (pricing.input + pricing.output) / 2;

    byProvider[provider].push({
      model: pricing.model,
      label: pricing.model,
      input_cost: pricing.input,
      output_cost: pricing.output,
      avg_cost: avgCost,
    });
  }

  // Sort models within each provider by avg_cost (cheapest first)
  for (const provider of Object.keys(byProvider)) {
    byProvider[provider].sort((a, b) => a.avg_cost - b.avg_cost);
  }

  // Get sorted list of providers
  const providers = Object.keys(byProvider).sort();

  return {
    providers,
    models: byProvider,
  };
}

/**
 * Get pricing directly from DB (bypasses cache)
 * @param {string} model - Model identifier
 * @returns {Promise<Object|null>} Pricing document or null
 */
async function getPricingFromDb(model: string): Promise<unknown> {
  const collection = getPricingCollection();
  return collection.findOne({ model });
}

/**
 * List all pricing from DB (bypasses cache)
 * @returns {Promise<Array>} All pricing documents
 */
async function listAllPricingFromDb(): Promise<unknown[]> {
  const collection = getPricingCollection();
  return collection.find({}).sort({ provider: 1, model: 1 }).toArray();
}

/**
 * Initialize pricing service - call on server startup
 * @returns {Promise<void>}
 */
async function initialize(): Promise<void> {
  try {
    await loadPricingFromDb(true);
    console.log("[pricing_service] Initialized successfully");
  } catch (err) {
    console.error("[pricing_service] Failed to initialize, using defaults:", (err as Error).message);
    loadFromDefaults();
  }
}

export default {
  // Core functions
  getModelPricing,
  getModelPricingSync,
  calculateCost,
  calculateCostSync,

  // CRUD operations
  upsertPricing,
  deletePricing,
  seedDefaultPricing,

  // Query functions
  getAllPricing,
  getPricingByProvider,
  getDegradationTargets,
  getPricingFromDb,
  listAllPricingFromDb,

  // Cache management
  loadPricingFromDb,
  invalidateCache,
  initialize,

  // Constants (for reference/testing)
  DEFAULT_PRICING,
  DEFAULT_PRICING_TABLE,
};
