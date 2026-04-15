import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { configApi, type ModelOption, type SubscriptionInfo } from "@/api/config";
import { credentialsApi } from "@/api/credentials";

// Provider metadata matching quickstart + routes_config.py
export interface ProviderInfo {
  id: string;
  name: string;
  description: string;
  envVar: string;
  initial: string;
}

export const LLM_PROVIDERS: ProviderInfo[] = [
  { id: "anthropic", name: "Anthropic (Claude)", description: "Claude 4 family - Fast, balanced, and most capable", envVar: "ANTHROPIC_API_KEY", initial: "A" },
  { id: "openai", name: "OpenAI (GPT)", description: "GPT-5.4 family - Best intelligence and value", envVar: "OPENAI_API_KEY", initial: "O" },
  { id: "gemini", name: "Google Gemini", description: "Gemini 3 family - Fast and best quality", envVar: "GEMINI_API_KEY", initial: "G" },
  { id: "groq", name: "Groq", description: "Ultra-fast inference, GPT-OSS and Llama", envVar: "GROQ_API_KEY", initial: "G" },
  { id: "cerebras", name: "Cerebras", description: "Ultra-fast inference, GPT-OSS and Z.ai GLM", envVar: "CEREBRAS_API_KEY", initial: "C" },
  { id: "minimax", name: "MiniMax", description: "MiniMax M2.7 and M2.5 - Best coding quality", envVar: "MINIMAX_API_KEY", initial: "M" },
  { id: "openrouter", name: "OpenRouter", description: "200+ models, any provider", envVar: "OPENROUTER_API_KEY", initial: "O" },
  { id: "mistral", name: "Mistral", description: "Mistral Large, Medium, Small, Codestral", envVar: "MISTRAL_API_KEY", initial: "M" },
  { id: "together", name: "Together AI", description: "DeepSeek, Qwen3, GPT-OSS, Llama", envVar: "TOGETHER_API_KEY", initial: "T" },
  { id: "deepseek", name: "DeepSeek", description: "DeepSeek Chat and Reasoner", envVar: "DEEPSEEK_API_KEY", initial: "D" },
];

interface ModelContextValue {
  // Current active config
  currentProvider: string;
  currentModel: string;
  hasApiKey: boolean;
  loading: boolean;

  // Which providers have keys stored (env var or credential store)
  connectedProviders: Set<string>;

  // Subscriptions
  subscriptions: SubscriptionInfo[];
  detectedSubscriptions: Set<string>;
  activeSubscription: string | null;

  // Model catalogue per provider
  availableModels: Record<string, ModelOption[]>;

  // Actions
  setModel: (provider: string, model: string) => Promise<void>;
  activateSubscription: (subscriptionId: string) => Promise<void>;
  saveProviderKey: (providerId: string, apiKey: string) => Promise<void>;
  removeProviderKey: (providerId: string) => Promise<void>;
  refresh: () => Promise<void>;
}

const ModelContext = createContext<ModelContextValue | null>(null);

export function ModelProvider({ children }: { children: ReactNode }) {
  const [currentProvider, setCurrentProvider] = useState("");
  const [currentModel, setCurrentModel] = useState("");
  const [hasApiKey, setHasApiKey] = useState(false);
  const [loading, setLoading] = useState(true);
  const [connectedProviders, setConnectedProviders] = useState<Set<string>>(new Set());
  const [availableModels, setAvailableModels] = useState<Record<string, ModelOption[]>>({});
  const [subscriptions, setSubscriptions] = useState<SubscriptionInfo[]>([]);
  const [detectedSubscriptions, setDetectedSubscriptions] = useState<Set<string>>(new Set());
  const [activeSubscription, setActiveSubscription] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [llmConfig, modelsData] = await Promise.all([
        configApi.getLLMConfig(),
        configApi.getModels(),
      ]);

      setCurrentProvider(llmConfig.provider);
      setCurrentModel(llmConfig.model);
      setHasApiKey(llmConfig.has_api_key);
      setAvailableModels(modelsData.models);

      // Backend checks both env vars and credential store for all providers
      setConnectedProviders(new Set(llmConfig.connected_providers || []));

      // Subscriptions
      setSubscriptions(llmConfig.subscriptions || []);
      setDetectedSubscriptions(new Set(llmConfig.detected_subscriptions || []));
      setActiveSubscription(llmConfig.active_subscription);
    } catch (err) {
      console.error("Failed to load model config:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const setModel = useCallback(
    async (provider: string, model: string) => {
      const result = await configApi.setLLMConfig(provider, model);
      setCurrentProvider(result.provider);
      setCurrentModel(result.model);
      setHasApiKey(result.has_api_key);
      setActiveSubscription(result.active_subscription);
    },
    [],
  );

  const activateSubscriptionFn = useCallback(
    async (subscriptionId: string) => {
      const result = await configApi.activateSubscription(subscriptionId);
      setCurrentProvider(result.provider);
      setCurrentModel(result.model);
      setHasApiKey(result.has_api_key);
      setActiveSubscription(result.active_subscription);
    },
    [],
  );

  const saveProviderKey = useCallback(
    async (providerId: string, apiKey: string) => {
      await credentialsApi.save(providerId, { api_key: apiKey });
      setConnectedProviders((prev) => new Set([...prev, providerId]));
      await refresh();
    },
    [refresh],
  );

  const removeProviderKey = useCallback(
    async (providerId: string) => {
      await credentialsApi.delete(providerId);
      setConnectedProviders((prev) => {
        const next = new Set(prev);
        next.delete(providerId);
        return next;
      });
      await refresh();
    },
    [refresh],
  );

  return (
    <ModelContext.Provider
      value={{
        currentProvider,
        currentModel,
        hasApiKey,
        loading,
        connectedProviders,
        subscriptions,
        detectedSubscriptions,
        activeSubscription,
        availableModels,
        setModel,
        activateSubscription: activateSubscriptionFn,
        saveProviderKey,
        removeProviderKey,
        refresh,
      }}
    >
      {children}
    </ModelContext.Provider>
  );
}

export function useModel() {
  const context = useContext(ModelContext);
  if (!context) {
    throw new Error("useModel must be used within a ModelProvider");
  }
  return context;
}
