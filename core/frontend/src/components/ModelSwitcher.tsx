import { useState, useRef, useEffect } from "react";
import { ChevronDown, Check, Settings, ThumbsUp } from "lucide-react";
import { useModel, LLM_PROVIDERS } from "@/context/ModelContext";
import type { ModelOption } from "@/api/config";

interface ModelSwitcherProps {
  onOpenSettings?: () => void;
}

export default function ModelSwitcher({ onOpenSettings }: ModelSwitcherProps) {
  const {
    currentProvider,
    currentModel,
    connectedProviders,
    availableModels,
    setModel,
    activateSubscription,
    activeSubscription,
    subscriptions,
    detectedSubscriptions,
    loading,
  } = useModel();

  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  if (loading) return null;

  // Get short display label for the pill
  const activeSubInfo = activeSubscription
    ? subscriptions.find((s) => s.id === activeSubscription)
    : null;
  const modelsProvider = activeSubInfo?.provider || currentProvider;
  const models = availableModels[modelsProvider] || [];
  const currentModelInfo = models.find((m) => m.id === currentModel);
  const shortLabel = currentModelInfo
    ? currentModelInfo.label.split(" - ")[0]
    : currentModel || "No model";

  // Providers with API keys
  const apiKeyProviders = LLM_PROVIDERS.filter(
    (p) => connectedProviders.has(p.id) && availableModels[p.id]?.length,
  );

  const handleSelectApiKey = async (provider: string, modelId: string) => {
    setOpen(false);
    try {
      await setModel(provider, modelId);
    } catch (err) {
      console.error("Failed to switch model:", err);
    }
  };

  const handleSelectSubscription = async (subscriptionId: string) => {
    setOpen(false);
    try {
      await activateSubscription(subscriptionId);
    } catch (err) {
      console.error("Failed to activate subscription:", err);
    }
  };

  // Get detected but inactive subscriptions
  const availableSubscriptions = subscriptions.filter(
    (sub) => detectedSubscriptions.has(sub.id) && activeSubscription !== sub.id
  );

  const recommendedIcon = (
    <span
      className="group/recommend ml-auto relative inline-flex items-center justify-center rounded bg-primary/10 text-primary p-1 flex-shrink-0"
      aria-label="Recommended model"
    >
      <ThumbsUp className="w-3 h-3" />
      <span className="pointer-events-none absolute right-full mr-2 top-1/2 -translate-y-1/2 whitespace-nowrap rounded border border-border/60 bg-card px-2 py-1 text-[10px] font-medium text-foreground opacity-0 invisible group-hover/recommend:opacity-100 group-hover/recommend:visible transition-none shadow-sm">
        Recommended model
      </span>
    </span>
  );

  const hasAnyProvider = apiKeyProviders.length > 0 || availableSubscriptions.length > 0 || activeSubInfo;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors border border-transparent hover:border-border/40"
      >
        <span className="max-w-[120px] truncate">{shortLabel}</span>
        <ChevronDown
          className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 w-[260px] bg-card border border-border/60 rounded-lg shadow-xl z-50 overflow-hidden">
          <div className="max-h-[320px] overflow-y-auto">
            {/* Active subscription */}
            {activeSubInfo && (
              <div className="px-3 py-2 bg-purple-500/5 border-b border-border/40">
                <p className="text-[10px] font-semibold text-purple-400/80 uppercase tracking-wider mb-1">
                  Active Subscription
                </p>
                <div className="flex items-center gap-2">
                  <Check className="w-3 h-3 text-purple-400" />
                  <span className="text-xs font-medium text-foreground">
                    {activeSubInfo.name}
                  </span>
                </div>
              </div>
            )}

            {/* Available subscriptions */}
            {availableSubscriptions.length > 0 && (
              <div>
                <p className="px-3 pt-2.5 pb-1 text-[10px] font-semibold text-purple-400/80 uppercase tracking-wider">
                  Available Subscriptions
                </p>
                {availableSubscriptions.map((sub) => (
                  <button
                    key={sub.id}
                    onClick={() => handleSelectSubscription(sub.id)}
                    className="w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors text-foreground hover:bg-muted/30"
                  >
                    <span className="w-3" />
                    <span className="truncate">{sub.name}</span>
                  </button>
                ))}
              </div>
            )}

            {/* API key provider models */}
            {!hasAnyProvider ? (
              <p className="px-4 py-3 text-xs text-muted-foreground">
                No providers available. Add an API key or subscription.
              </p>
            ) : (
              apiKeyProviders.length > 0 && (
                <div>
                  <p className="px-3 pt-2.5 pb-1 text-[10px] font-semibold text-muted-foreground/60 uppercase tracking-wider">
                    API Key Providers
                  </p>
                  {apiKeyProviders.map((provider) => (
                    <div key={provider.id}>
                      <p className="px-3 pt-2.5 pb-1 text-[10px] font-semibold text-muted-foreground/60 uppercase tracking-wider">
                        {provider.name}
                      </p>
                      {(availableModels[provider.id] || []).map(
                        (model: ModelOption) => {
                          const isActive =
                            currentProvider === provider.id &&
                            currentModel === model.id &&
                            !activeSubscription;
                          return (
                            <button
                              key={model.id}
                              onClick={() => handleSelectApiKey(provider.id, model.id)}
                              className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                                isActive
                                  ? "bg-primary/10 text-primary"
                                  : "text-foreground hover:bg-muted/30"
                              }`}
                            >
                              {isActive ? (
                                <Check className="w-3 h-3 flex-shrink-0" />
                              ) : (
                                <span className="w-3" />
                              )}
                              <span className="truncate">
                                {model.label.split(" - ")[0]}
                              </span>
                              {model.recommended && recommendedIcon}
                            </button>
                          );
                        },
                      )}
                    </div>
                  ))}
                </div>
              )
            )}
          </div>

          {/* Footer link */}
          {onOpenSettings && (
            <div className="border-t border-border/40">
              <button
                onClick={() => {
                  setOpen(false);
                  onOpenSettings();
                }}
                className="w-full flex items-center gap-2 px-3 py-2.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/20 transition-colors"
              >
                <Settings className="w-3 h-3" />
                Manage Keys...
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
