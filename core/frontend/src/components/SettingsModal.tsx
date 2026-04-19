import { useEffect, useRef, useState } from "react";
import { X, Eye, EyeOff, Check, Pencil, ChevronDown, Zap, ThumbsUp, Loader2, AlertCircle, Camera } from "lucide-react";
import { useColony } from "@/context/ColonyContext";
import { useTheme } from "@/context/ThemeContext";
import { useModel, LLM_PROVIDERS } from "@/context/ModelContext";
import { credentialsApi } from "@/api/credentials";
import { configApi, type ModelOption } from "@/api/config";
import { compressImage } from "@/lib/image-utils";

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
  initialSection?: "profile" | "byok";
}

function ValidationBadge({ state }: { state: "validating" | { valid: boolean | null; message: string } | undefined }) {
  if (!state) return <StatusText icon={<Check className="w-3 h-3" />} color="green">Connected</StatusText>;
  if (state === "validating") return <StatusText icon={<Loader2 className="w-3 h-3 animate-spin" />} color="muted">Verifying...</StatusText>;
  if (state.valid === false) return <StatusText icon={<AlertCircle className="w-3 h-3" />} color="red" title={state.message}>Invalid key</StatusText>;
  if (state.valid === true) return <StatusText icon={<Check className="w-3 h-3" />} color="green">Verified</StatusText>;
  return <StatusText icon={<Check className="w-3 h-3" />} color="green">Connected</StatusText>;
}

function StatusText({ icon, color, title, children }: { icon: React.ReactNode; color: "green" | "red" | "muted"; title?: string; children: React.ReactNode }) {
  const cls = color === "green" ? "text-green-500" : color === "red" ? "text-red-400" : "text-muted-foreground";
  return <span className={`flex items-center gap-1 text-xs font-medium ${cls}`} title={title}>{icon}{children}</span>;
}

export default function SettingsModal({ open, onClose, initialSection }: SettingsModalProps) {
  const { userProfile, setUserProfile, userAvatarVersion, bumpUserAvatar } = useColony();
  const { theme, setTheme } = useTheme();
  const {
    currentProvider, currentModel, connectedProviders, availableModels,
    setModel, saveProviderKey, subscriptions, detectedSubscriptions,
    activeSubscription, activateSubscription,
  } = useModel();

  const [displayName, setDisplayName] = useState(userProfile.displayName);
  const [about, setAbout] = useState(userProfile.about);
  const [activeSection, setActiveSection] = useState<"profile" | "byok">(initialSection || "profile");
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validation, setValidation] = useState<Record<string, "validating" | { valid: boolean | null; message: string }>>({});
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const [themeDropdownOpen, setThemeDropdownOpen] = useState(false);
  const avatarUrl = `/api/config/profile/avatar?v=${userAvatarVersion}`;
  const [avatarFailed, setAvatarFailed] = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const avatarInputRef = useRef<HTMLInputElement>(null);
  const themeDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!themeDropdownOpen) return;
    const handler = (e: MouseEvent) => {
      if (themeDropdownRef.current && !themeDropdownRef.current.contains(e.target as Node))
        setThemeDropdownOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [themeDropdownOpen]);

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

  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !file.type.startsWith("image/")) return;
    e.target.value = "";
    setUploadingAvatar(true);
    try {
      const compressed = await compressImage(file);
      await configApi.uploadAvatar(compressed);
      bumpUserAvatar();
      setAvatarFailed(false);
    } catch {}
    setUploadingAvatar(false);
  };

  const clearValidation = (providerId: string) => {
    setTimeout(() => setValidation((v) => { const next = { ...v }; delete next[providerId]; return next; }), 4000);
  };

  const handleSaveKey = async (providerId: string) => {
    const trimmedKey = keyInput.trim();
    if (!trimmedKey) return;
    setSaving(true);
    setValidation((v) => ({ ...v, [providerId]: "validating" }));

    const validateResult = await credentialsApi
      .validateKey(providerId, trimmedKey)
      .catch(() => ({ valid: null as boolean | null, message: "Could not verify key" }));

    if (validateResult.valid === false) {
      setSaving(false);
      setValidation((v) => ({ ...v, [providerId]: { valid: false, message: validateResult.message } }));
      clearValidation(providerId);
      return;
    }

    try {
      await saveProviderKey(providerId, trimmedKey);
    } catch {
      setSaving(false);
      setValidation((v) => ({ ...v, [providerId]: { valid: false, message: "Failed to save key" } }));
      clearValidation(providerId);
      return;
    }

    setSaving(false);
    setEditingProvider(null);
    setKeyInput("");
    setShowKey(false);
    setValidation((v) => ({ ...v, [providerId]: { valid: validateResult.valid, message: validateResult.message } }));
    clearValidation(providerId);
  };

  const handleSelectModel = async (provider: string, modelId: string) => {
    try { await setModel(provider, modelId); setModelDropdownOpen(false); } catch {}
  };

  const handleActivateSubscription = async (subId: string) => {
    try { await activateSubscription(subId); } catch {}
  };

  const initials = displayName.trim().split(/\s+/).map((w) => w[0]).join("").toUpperCase().slice(0, 2);

  const activeSubInfo = activeSubscription ? subscriptions.find((s) => s.id === activeSubscription) : null;
  const providerForModels = activeSubInfo?.provider || currentProvider;
  const modelsForLabel = availableModels[providerForModels] || [];
  const currentModelLabel = modelsForLabel.find((m) => m.id === currentModel)?.label || currentModel || "Not configured";

  const currentProviderName = activeSubscription
    ? (subscriptions.find((s) => s.id === activeSubscription)?.name || currentProvider)
    : (LLM_PROVIDERS.find((p) => p.id === currentProvider)?.name || currentProvider);

  const selectableProviders = LLM_PROVIDERS.filter(
    (p) => connectedProviders.has(p.id) && availableModels[p.id]?.length,
  );

  const startEditing = (providerId: string) => {
    setEditingProvider(providerId);
    setKeyInput("");
    setShowKey(false);
  };

  const cancelEditing = () => {
    setEditingProvider(null);
    setKeyInput("");
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      <div className="relative bg-card border border-border/60 rounded-2xl shadow-2xl w-full max-w-[720px] h-[520px] max-h-[80vh] flex overflow-hidden">
        {/* Sidebar */}
        <div className="w-[180px] flex-shrink-0 border-r border-border/40 py-6 px-3 flex flex-col gap-6">
          <h2 className="text-sm font-semibold text-foreground px-3">SETTINGS</h2>
          <div className="flex flex-col gap-1">
            <p className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider px-3 mb-1">Account</p>
            <button
              onClick={() => setActiveSection("profile")}
              className={`text-left text-sm px-3 py-1.5 rounded-md ${activeSection === "profile" ? "bg-primary/15 text-primary font-medium" : "text-muted-foreground hover:text-foreground hover:bg-muted/30"}`}
            >
              Profile
            </button>
          </div>
          <div className="flex flex-col gap-1">
            <p className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider px-3 mb-1">System</p>
            <button
              onClick={() => setActiveSection("byok")}
              className={`text-left text-sm px-3 py-1.5 rounded-md ${activeSection === "byok" ? "bg-primary/15 text-primary font-medium" : "text-muted-foreground hover:text-foreground hover:bg-muted/30"}`}
            >
              BYOK
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 flex flex-col min-h-0">
          <button onClick={onClose} className="absolute top-4 right-4 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50">
            <X className="w-4 h-4" />
          </button>

          <div className="flex-1 overflow-y-auto overscroll-contain px-8 py-6 flex flex-col gap-6">
            {activeSection === "profile" && (
              <>
                <div>
                  <label className="text-sm font-medium text-foreground mb-2 block">
                    Display <span className="text-primary">*</span>
                  </label>
                  <div className="flex items-center gap-3">
                    <div className="relative group flex-shrink-0">
                      <div className="w-10 h-10 rounded-full bg-primary/15 flex items-center justify-center overflow-hidden">
                        {!avatarFailed ? (
                          <img src={avatarUrl} alt="" className="w-full h-full object-cover" onError={() => setAvatarFailed(true)} />
                        ) : (
                          <span className="text-xs font-bold text-primary">{initials || "?"}</span>
                        )}
                      </div>
                      <button
                        onClick={() => avatarInputRef.current?.click()}
                        disabled={uploadingAvatar}
                        className="absolute inset-0 w-10 h-10 rounded-full flex items-center justify-center bg-black/50 opacity-0 group-hover:opacity-100 cursor-pointer"
                        title="Change photo"
                      >
                        {uploadingAvatar ? <Loader2 className="w-3.5 h-3.5 text-white animate-spin" /> : <Camera className="w-3.5 h-3.5 text-white" />}
                      </button>
                      <input ref={avatarInputRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarUpload} />
                    </div>
                    <input
                      type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
                      placeholder="Display name"
                      className="flex-1 bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-sm font-medium text-foreground mb-2 block">About</label>
                  <textarea
                    value={about} onChange={(e) => setAbout(e.target.value)}
                    placeholder="Tell people about yourself or your organization" rows={4}
                    className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 resize-none"
                  />
                </div>

                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium text-foreground">Theme</label>
                  <div className="relative" ref={themeDropdownRef}>
                    <button onClick={() => setThemeDropdownOpen(!themeDropdownOpen)}
                      className="flex items-center gap-2 bg-muted/30 border border-border/50 rounded-lg px-3 py-1.5 text-sm text-foreground hover:bg-muted/40">
                      {theme === "light" ? "Light" : "Dark"}
                      <ChevronDown className={`w-3.5 h-3.5 text-muted-foreground ${themeDropdownOpen ? "rotate-180" : ""}`} />
                    </button>
                    {themeDropdownOpen && (
                      <div className="absolute right-0 top-full mt-1 bg-card border border-border/60 rounded-lg shadow-xl z-10 min-w-[120px]">
                        {(["light", "dark"] as const).map((option) => (
                          <button key={option} onClick={() => { setTheme(option); setThemeDropdownOpen(false); }}
                            className={`w-full text-left px-4 py-2 text-sm flex items-center gap-2 first:rounded-t-lg last:rounded-b-lg ${theme === option ? "bg-primary/10 text-primary" : "text-foreground hover:bg-muted/30"}`}>
                            {theme === option ? <Check className="w-3 h-3 flex-shrink-0" /> : <span className="w-3" />}
                            <span>{option === "light" ? "Light" : "Dark"}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex justify-end mt-auto pt-4">
                  <button onClick={handleSave} className="px-5 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90">Save</button>
                </div>
              </>
            )}

            {activeSection === "byok" && (
              <>
                <div>
                  <h3 className="text-lg font-semibold text-foreground">Bring Your Own Key</h3>
                  <p className="text-sm text-muted-foreground mt-1">
                    Use your own API keys for hosted model providers. Your keys are encrypted and never shared.
                  </p>
                </div>

                {/* Active Model */}
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider mb-3">Active Model</p>
                  <div className="relative">
                    <button onClick={() => setModelDropdownOpen(!modelDropdownOpen)}
                      className="w-full flex items-center justify-between bg-muted/30 border border-border/50 rounded-lg px-4 py-3 text-left hover:bg-muted/40">
                      <div>
                        <p className="text-sm font-medium text-foreground">{currentModelLabel}</p>
                        <p className="text-xs text-muted-foreground">{currentProviderName}</p>
                      </div>
                      <ChevronDown className={`w-4 h-4 text-muted-foreground ${modelDropdownOpen ? "rotate-180" : ""}`} />
                    </button>
                    {modelDropdownOpen && (
                      <div className="absolute top-full left-0 right-0 mt-1 bg-card border border-border/60 rounded-lg shadow-xl z-10 max-h-[280px] overflow-y-auto overscroll-contain">
                        {selectableProviders.length === 0 ? (
                          <p className="px-4 py-3 text-sm text-muted-foreground">Add an API key or enable a subscription to see available models.</p>
                        ) : selectableProviders.map((provider) => (
                          <div key={provider.id}>
                            <p className="px-4 pt-3 pb-0.5 text-sm font-medium text-foreground">{provider.name}</p>
                            {(availableModels[provider.id] || []).map((model: ModelOption) => {
                              const isActive = currentProvider === provider.id && currentModel === model.id && !activeSubscription;
                              return (
                                <button key={model.id} onClick={() => handleSelectModel(provider.id, model.id)}
                                  className={`w-full text-left pl-8 pr-4 py-2 text-sm flex items-center gap-2 ${isActive ? "bg-primary/10 text-primary" : "text-foreground hover:bg-muted/30"}`}>
                                  {isActive ? <Check className="w-3 h-3 flex-shrink-0" /> : <span className="w-3" />}
                                  <span>{model.label}</span>
                                  {model.recommended && (
                                    <span className="ml-auto inline-flex items-center justify-center rounded bg-primary/10 text-primary p-1 flex-shrink-0" title="Recommended">
                                      <ThumbsUp className="w-3 h-3" />
                                    </span>
                                  )}
                                </button>
                              );
                            })}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Subscriptions */}
                {subscriptions.length > 0 && (
                  <div>
                    <p className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider mb-3">Subscriptions</p>
                    <div className="flex flex-col gap-1">
                      {subscriptions.map((sub) => {
                        const isDetected = detectedSubscriptions.has(sub.id);
                        const isActive = activeSubscription === sub.id;
                        return (
                          <div key={sub.id} className="flex items-center gap-3 py-2.5 px-2 rounded-lg hover:bg-muted/20">
                            <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                              <Zap className="w-4 h-4 text-primary" />
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-foreground">{sub.name}</p>
                              <p className="text-xs text-muted-foreground truncate">{sub.description}</p>
                            </div>
                            {isActive ? (
                              <StatusText icon={<Check className="w-3 h-3" />} color="green">Active</StatusText>
                            ) : isDetected ? (
                              <button onClick={() => handleActivateSubscription(sub.id)}
                                className="px-3 py-1.5 rounded-md text-xs font-semibold bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25">
                                Enable
                              </button>
                            ) : (
                              <span className="text-xs text-muted-foreground/50">Not detected</span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* API Keys */}
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wider mb-3">API Keys</p>
                  <div className="flex flex-col gap-1">
                    {LLM_PROVIDERS.map((provider) => {
                      const isConnected = connectedProviders.has(provider.id);
                      const isEditing = editingProvider === provider.id;
                      return (
                        <div key={provider.id}>
                          <div className="flex items-center gap-3 py-2.5 px-2 rounded-lg hover:bg-muted/20">
                            <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                              <span className="text-sm font-bold text-primary">{provider.initial}</span>
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-foreground">{provider.name}</p>
                              <p className="text-xs text-muted-foreground truncate">{provider.description}</p>
                            </div>
                            {isConnected && !isEditing ? (
                              <div className="flex items-center gap-2">
                                <ValidationBadge state={validation[provider.id]} />
                                <button onClick={() => startEditing(provider.id)} className="p-1 rounded text-muted-foreground/40 hover:text-foreground" title="Change key">
                                  <Pencil className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            ) : !isEditing ? (
                              <button onClick={() => startEditing(provider.id)}
                                className="px-3 py-1.5 rounded-md text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90">
                                Add Key
                              </button>
                            ) : null}
                          </div>
                          {isEditing && (
                            <div className="ml-12 mr-2 mb-2 flex flex-col gap-1.5">
                              <div className="flex items-center gap-2">
                                <div className="relative flex-1">
                                  <input
                                    type={showKey ? "text" : "password"} value={keyInput}
                                    onChange={(e) => setKeyInput(e.target.value)}
                                    placeholder={`Enter ${provider.name} API key`} autoFocus
                                    onKeyDown={(e) => { if (e.key === "Enter") handleSaveKey(provider.id); if (e.key === "Escape") cancelEditing(); }}
                                    className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 pr-9 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 font-mono"
                                  />
                                  <button onClick={() => setShowKey(!showKey)} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/50 hover:text-foreground">
                                    {showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                                  </button>
                                </div>
                                <button onClick={() => handleSaveKey(provider.id)} disabled={!keyInput.trim() || saving}
                                  className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed">
                                  {saving ? "..." : "Save"}
                                </button>
                                <button onClick={cancelEditing} className="px-3 py-2 rounded-lg text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30">Cancel</button>
                              </div>
                              {validation[provider.id] === "validating" && (
                                <StatusText icon={<Loader2 className="w-3 h-3 animate-spin" />} color="muted">Verifying...</StatusText>
                              )}
                              {validation[provider.id] && typeof validation[provider.id] === "object" && (validation[provider.id] as { valid: boolean | null; message: string }).valid === false && (
                                <StatusText icon={<AlertCircle className="w-3 h-3" />} color="red">
                                  {(validation[provider.id] as { message: string }).message}
                                </StatusText>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
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
