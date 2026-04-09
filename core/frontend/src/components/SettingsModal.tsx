import { useEffect, useRef, useState } from "react";
import { X, Eye, EyeOff, Check, Trash2, ChevronDown, Zap, ThumbsUp } from "lucide-react";
import { useColony } from "@/context/ColonyContext";
import { useTheme } from "@/context/ThemeContext";
import { useModel, LLM_PROVIDERS } from "@/context/ModelContext";
import type { ModelOption } from "@/api/config";

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
  initialSection?: "profile" | "byok";
}

export default function SettingsModal({ open, onClose, initialSection }: SettingsModalProps) {
  const { userProfile, setUserProfile } = useColony();
  const { theme, setTheme } = useTheme();
  const {
    currentProvider,
    currentModel,
    connectedProviders,
    availableModels,
    setModel,
    saveProviderKey,
    removeProviderKey,
    subscriptions,
    detectedSubscriptions,
    activeSubscription,
    activateSubscription,
  } = useModel();

  const [displayName, setDisplayName] = useState(userProfile.displayName);
  const [about, setAbout] = useState(userProfile.about);
  const [activeSection, setActiveSection] = useState<"profile" | "byok">(
    initialSection || "profile",
  );

  // Key entry state
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);

  // Model selection state
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);

  // Theme dropdown state
  const [themeDropdownOpen, setThemeDropdownOpen] = useState(false);
  const themeDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!themeDropdownOpen) return;
    const handler = (e: MouseEvent) => {
      if (themeDropdownRef.current && !themeDropdownRef.current.contains(e.target as Node)) {
        setThemeDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [themeDropdownOpen]);

  // Sync form fields when modal opens
  useEffect(() => {
    if (open) {
      setDisplayName(userProfile.displayName);
      setAbout(userProfile.about);
      if (initialSection) setActiveSection(initialSection);
    }
  }, [open, userProfile, initialSection]);

  if (!open) return null;

  const handleSave = () => {
    setUserProfile({ displayName: displayName.trim(), about: about.trim() });
    onClose();
  };

  const handleSaveKey = async (providerId: string) => {
    if (!keyInput.trim()) return;
    setSaving(true);
    try {
      await saveProviderKey(providerId, keyInput.trim());
      setEditingProvider(null);
      setKeyInput("");
      setShowKey(false);
    } catch (err) {
      console.error("Failed to save key:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveKey = async (providerId: string) => {
    try {
      await removeProviderKey(providerId);
    } catch (err) {
      console.error("Failed to remove key:", err);
    }
  };

  const handleSelectModel = async (provider: string, modelId: string) => {
    try {
      await setModel(provider, modelId);
      setModelDropdownOpen(false);
    } catch (err) {
      console.error("Failed to set model:", err);
    }
  };

  // Initials for avatar
  const initials = displayName
    .trim()
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  // Get human-readable model label
  const currentModelLabel = (() => {
    // Check subscription provider's models too
    const sub = activeSubscription
      ? subscriptions.find((s) => s.id === activeSubscription)
      : null;
    const providerForModels = sub?.provider || currentProvider;
    const models = availableModels[providerForModels] || [];
    const m = models.find((m) => m.id === currentModel);
    return m?.label || currentModel || "Not configured";
  })();

  const currentProviderName = (() => {
    if (activeSubscription) {
      const sub = subscriptions.find((s) => s.id === activeSubscription);
      return sub?.name || currentProvider;
    }
    return LLM_PROVIDERS.find((p) => p.id === currentProvider)?.name || currentProvider;
  })();

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

  // Models available for selection (from connected API key providers + active subscription's provider)
  const selectableProviders = LLM_PROVIDERS.filter(
    (p) => connectedProviders.has(p.id) && availableModels[p.id]?.length,
  );

  // Also include the active subscription's provider models if not already covered
  const activeSubInfo = activeSubscription
    ? subscriptions.find((s) => s.id === activeSubscription)
    : null;
  const subProviderInList = activeSubInfo
    ? selectableProviders.some((p) => p.id === activeSubInfo.provider)
    : true;

  const handleActivateSubscription = async (subId: string) => {
    try {
      await activateSubscription(subId);
    } catch (err) {
      console.error("Failed to activate subscription:", err);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-card border border-border/60 rounded-2xl shadow-2xl w-full max-w-[720px] h-[520px] max-h-[80vh] flex overflow-hidden">
        {/* Sidebar nav */}
        <div className="w-[180px] flex-shrink-0 border-r border-border/40 py-6 px-3 flex flex-col gap-6">
          <h2 className="text-sm font-semibold text-foreground px-3">
            SETTINGS
          </h2>

          <div className="flex flex-col gap-1">
            <p className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider px-3 mb-1">
              Account
            </p>
            <button
              onClick={() => setActiveSection("profile")}
              className={`text-left text-sm px-3 py-1.5 rounded-md transition-colors ${
                activeSection === "profile"
                  ? "bg-primary/15 text-primary font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/30"
              }`}
            >
              Profile
            </button>
          </div>

          <div className="flex flex-col gap-1">
            <p className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider px-3 mb-1">
              System
            </p>
            <button
              onClick={() => setActiveSection("byok")}
              className={`text-left text-sm px-3 py-1.5 rounded-md transition-colors ${
                activeSection === "byok"
                  ? "bg-primary/15 text-primary font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/30"
              }`}
            >
              BYOK
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 flex flex-col min-h-0">
          {/* Close button */}
          <button
            onClick={onClose}
            className="absolute top-4 right-4 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>

          <div className="flex-1 overflow-y-auto scrollbar-hide px-8 py-6 flex flex-col gap-6">
            {activeSection === "profile" && (
              <>
                {/* Display name */}
                <div>
                  <label className="text-sm font-medium text-foreground mb-2 block">
                    Display <span className="text-primary">*</span>
                  </label>
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-primary/15 flex items-center justify-center flex-shrink-0">
                      <span className="text-xs font-bold text-primary">
                        {initials || "?"}
                      </span>
                    </div>
                    <input
                      type="text"
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      placeholder="Display name"
                      className="flex-1 bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40"
                    />
                  </div>
                </div>

                {/* About */}
                <div>
                  <label className="text-sm font-medium text-foreground mb-2 block">
                    About
                  </label>
                  <textarea
                    value={about}
                    onChange={(e) => setAbout(e.target.value)}
                    placeholder="Tell people about yourself or your organization"
                    rows={4}
                    className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 resize-none"
                  />
                </div>

                {/* Theme */}
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium text-foreground">
                    Theme
                  </label>
                  <div className="relative" ref={themeDropdownRef}>
                    <button
                      onClick={() => setThemeDropdownOpen(!themeDropdownOpen)}
                      className="flex items-center gap-2 bg-muted/30 border border-border/50 rounded-lg px-3 py-1.5 text-sm text-foreground hover:bg-muted/40 transition-colors"
                    >
                      {theme === "light" ? "Light" : "Dark"}
                      <ChevronDown
                        className={`w-3.5 h-3.5 text-muted-foreground transition-transform ${
                          themeDropdownOpen ? "rotate-180" : ""
                        }`}
                      />
                    </button>

                    {themeDropdownOpen && (
                      <div className="absolute right-0 top-full mt-1 bg-card border border-border/60 rounded-lg shadow-xl z-10 min-w-[120px]">
                        {(["light", "dark"] as const).map((option) => (
                          <button
                            key={option}
                            onClick={() => {
                              setTheme(option);
                              setThemeDropdownOpen(false);
                            }}
                            className={`w-full text-left px-4 py-2 text-sm flex items-center gap-2 transition-colors first:rounded-t-lg last:rounded-b-lg ${
                              theme === option
                                ? "bg-primary/10 text-primary"
                                : "text-foreground hover:bg-muted/30"
                            }`}
                          >
                            {theme === option && <Check className="w-3 h-3 flex-shrink-0" />}
                            <span className={theme === option ? "" : "ml-5"}>
                              {option === "light" ? "Light" : "Dark"}
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Save button */}
                <div className="flex justify-end mt-auto pt-4">
                  <button
                    onClick={handleSave}
                    className="px-5 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
                  >
                    Save
                  </button>
                </div>
              </>
            )}

            {activeSection === "byok" && (
              <>
                {/* Header */}
                <div>
                  <h3 className="text-lg font-semibold text-foreground">
                    Bring Your Own Key
                  </h3>
                  <p className="text-sm text-muted-foreground mt-1">
                    Use your own API keys for hosted model providers. Your keys
                    are encrypted and never shared.
                  </p>
                </div>

                {/* Subscriptions */}
                {subscriptions.length > 0 && (
                  <div>
                    <p className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider mb-3">
                      Subscriptions
                    </p>
                    <div className="flex flex-col gap-1">
                      {subscriptions.map((sub) => {
                        const isDetected = detectedSubscriptions.has(sub.id);
                        const isActive = activeSubscription === sub.id;

                        return (
                          <div
                            key={sub.id}
                            className="flex items-center gap-3 py-2.5 px-2 rounded-lg hover:bg-muted/20 transition-colors"
                          >
                            {/* Icon */}
                            <div className="w-9 h-9 rounded-full bg-purple-500/10 flex items-center justify-center flex-shrink-0">
                              <Zap className="w-4 h-4 text-purple-400" />
                            </div>

                            {/* Info */}
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-foreground">
                                {sub.name}
                              </p>
                              <p className="text-xs text-muted-foreground truncate">
                                {sub.description}
                              </p>
                            </div>

                            {/* Status / Action */}
                            {isActive ? (
                              <span className="flex items-center gap-1 text-xs text-green-500 font-medium">
                                <Check className="w-3 h-3" />
                                Active
                              </span>
                            ) : isDetected ? (
                              <button
                                onClick={() => handleActivateSubscription(sub.id)}
                                className="px-3 py-1.5 rounded-md text-xs font-semibold bg-purple-500/15 text-purple-400 border border-purple-500/30 hover:bg-purple-500/25 transition-colors"
                              >
                                Enable
                              </button>
                            ) : (
                              <span className="text-xs text-muted-foreground/50">
                                Not detected
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* LLM Providers */}
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider mb-3">
                    API Key Providers
                  </p>
                  <div className="flex flex-col gap-1">
                    {LLM_PROVIDERS.map((provider) => {
                      const isConnected = connectedProviders.has(provider.id);
                      const isEditing = editingProvider === provider.id;

                      return (
                        <div key={provider.id}>
                          <div className="flex items-center gap-3 py-2.5 px-2 rounded-lg hover:bg-muted/20 transition-colors">
                            {/* Avatar */}
                            <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                              <span className="text-sm font-bold text-primary">
                                {provider.initial}
                              </span>
                            </div>

                            {/* Info */}
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-foreground">
                                {provider.name}
                              </p>
                              <p className="text-xs text-muted-foreground truncate">
                                {provider.description}
                              </p>
                            </div>

                            {/* Action */}
                            {isConnected && !isEditing ? (
                              <div className="flex items-center gap-2">
                                <span className="flex items-center gap-1 text-xs text-green-500 font-medium">
                                  <Check className="w-3 h-3" />
                                  Connected
                                </span>
                                <button
                                  onClick={() => handleRemoveKey(provider.id)}
                                  className="p-1 rounded text-muted-foreground/40 hover:text-red-400 transition-colors"
                                  title="Remove key"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            ) : !isEditing ? (
                              <button
                                onClick={() => {
                                  setEditingProvider(provider.id);
                                  setKeyInput("");
                                  setShowKey(false);
                                }}
                                className="px-3 py-1.5 rounded-md text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                              >
                                Add Key
                              </button>
                            ) : null}
                          </div>

                          {/* Inline key entry */}
                          {isEditing && (
                            <div className="ml-12 mr-2 mb-2 flex items-center gap-2">
                              <div className="relative flex-1">
                                <input
                                  type={showKey ? "text" : "password"}
                                  value={keyInput}
                                  onChange={(e) => setKeyInput(e.target.value)}
                                  placeholder={`Enter ${provider.name} API key`}
                                  autoFocus
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") handleSaveKey(provider.id);
                                    if (e.key === "Escape") {
                                      setEditingProvider(null);
                                      setKeyInput("");
                                    }
                                  }}
                                  className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 pr-9 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 font-mono"
                                />
                                <button
                                  onClick={() => setShowKey(!showKey)}
                                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/50 hover:text-foreground transition-colors"
                                >
                                  {showKey ? (
                                    <EyeOff className="w-3.5 h-3.5" />
                                  ) : (
                                    <Eye className="w-3.5 h-3.5" />
                                  )}
                                </button>
                              </div>
                              <button
                                onClick={() => handleSaveKey(provider.id)}
                                disabled={!keyInput.trim() || saving}
                                className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                {saving ? "..." : "Save"}
                              </button>
                              <button
                                onClick={() => {
                                  setEditingProvider(null);
                                  setKeyInput("");
                                }}
                                className="px-3 py-2 rounded-lg text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors"
                              >
                                Cancel
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Active Model */}
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider mb-3">
                    Active Model
                  </p>

                  <div className="relative">
                    <button
                      onClick={() => setModelDropdownOpen(!modelDropdownOpen)}
                      className="w-full flex items-center justify-between bg-muted/30 border border-border/50 rounded-lg px-4 py-3 text-left hover:bg-muted/40 transition-colors"
                    >
                      <div>
                        <p className="text-sm font-medium text-foreground">
                          {currentModelLabel}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {currentProviderName}
                        </p>
                      </div>
                      <ChevronDown
                        className={`w-4 h-4 text-muted-foreground transition-transform ${
                          modelDropdownOpen ? "rotate-180" : ""
                        }`}
                      />
                    </button>

                    {modelDropdownOpen && (
                      <div className="absolute top-full left-0 right-0 mt-1 bg-card border border-border/60 rounded-lg shadow-xl z-10 max-h-[280px] overflow-y-auto">
                        {/* Subscription models (if active) */}
                        {activeSubInfo && !subProviderInList && availableModels[activeSubInfo.provider]?.length > 0 && (
                          <div>
                            <p className="px-4 pt-3 pb-1 text-[11px] font-semibold text-purple-400/80 uppercase tracking-wider">
                              {activeSubInfo.name} ({activeSubInfo.provider})
                            </p>
                            {(availableModels[activeSubInfo.provider] || []).map(
                              (model: ModelOption) => {
                                const isActive = currentModel === model.id;
                                return (
                                  <button
                                    key={`sub-${model.id}`}
                                    onClick={() =>
                                      activateSubscription(activeSubscription!, model.id)
                                    }
                                    className={`w-full text-left px-4 py-2 text-sm flex items-center gap-2 transition-colors ${
                                      isActive
                                        ? "bg-primary/10 text-primary"
                                        : "text-foreground hover:bg-muted/30"
                                    }`}
                                  >
                                    {isActive && <Check className="w-3 h-3 flex-shrink-0" />}
                                    <span className={isActive ? "" : "ml-5"}>{model.label}</span>
                                    {model.recommended && recommendedIcon}
                                  </button>
                                );
                              },
                            )}
                          </div>
                        )}

                        {selectableProviders.length === 0 && !activeSubInfo ? (
                          <p className="px-4 py-3 text-sm text-muted-foreground">
                            Add an API key or enable a subscription to see available models.
                          </p>
                        ) : (
                          selectableProviders.map((provider) => (
                            <div key={provider.id}>
                              <p className="px-4 pt-3 pb-1 text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider">
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
                                      onClick={() =>
                                        handleSelectModel(provider.id, model.id)
                                      }
                                      className={`w-full text-left px-4 py-2 text-sm flex items-center gap-2 transition-colors ${
                                        isActive
                                          ? "bg-primary/10 text-primary"
                                          : "text-foreground hover:bg-muted/30"
                                      }`}
                                    >
                                      {isActive && (
                                        <Check className="w-3 h-3 flex-shrink-0" />
                                      )}
                                      <span
                                        className={isActive ? "" : "ml-5"}
                                      >
                                        {model.label}
                                      </span>
                                      {model.recommended && recommendedIcon}
                                    </button>
                                  );
                                },
                              )}
                            </div>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
