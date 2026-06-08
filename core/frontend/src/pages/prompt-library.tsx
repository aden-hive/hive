import { useState, useMemo, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Copy, Check, Sparkles, MessageSquarePlus, Plus, X, Trash2, ChevronLeft, ChevronRight } from "lucide-react";
import { prompts, promptCategories, categoryToQueen, queenNames, type Prompt } from "@/data/prompts";
import { promptsApi, type CustomPrompt } from "@/api/prompts";

const PAGE_SIZE = 24;

function PromptCard({
  prompt,
  onUse,
  onDelete,
}: {
  prompt: Prompt | CustomPrompt;
  onUse: (content: string, category: string) => void;
  onDelete?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const queenId = categoryToQueen[prompt.category];
  const queenName = queenNames[queenId] || "Queen";
  const isCustom = "custom" in prompt && prompt.custom;

  const handleCopy = async () => {
    await navigator.clipboard.writeText(prompt.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="group rounded-lg border border-border/60 bg-card p-4 hover:border-primary/30 hover:shadow-sm transition-all flex flex-col">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <h3 className="text-sm font-medium text-foreground line-clamp-1">{prompt.title}</h3>
          {isCustom && (
            <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium bg-primary/10 text-primary">My Prompt</span>
          )}
        </div>
        <div className="flex items-center gap-0.5 flex-shrink-0 opacity-0 group-hover:opacity-100">
          <button onClick={handleCopy} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60" title="Copy prompt">
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
          {isCustom && onDelete && (
            <button onClick={onDelete} className="p-1.5 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10" title="Delete prompt">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
      <p className="text-xs text-muted-foreground line-clamp-3 leading-relaxed mb-3 flex-1">{prompt.content}</p>
      <button
        onClick={() => onUse(prompt.content, prompt.category)}
        className="w-full flex items-center justify-center gap-1.5 rounded-md border border-primary/20 bg-primary/[0.04] py-1.5 text-xs font-medium text-primary hover:bg-primary/[0.08]"
      >
        <MessageSquarePlus className="w-3.5 h-3.5" />
        Ask {queenName}
      </button>
    </div>
  );
}

function AddPromptModal({ open, onClose, onSave }: { open: boolean; onClose: () => void; onSave: (title: string, category: string, content: string) => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("");
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);

  if (!open) return null;

  const handleSubmit = async () => {
    if (!title.trim() || !content.trim()) return;
    setSaving(true);
    await onSave(title.trim(), category.trim(), content.trim());
    setSaving(false);
    setTitle("");
    setCategory("");
    setContent("");
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-card border border-border/60 rounded-2xl shadow-2xl w-full max-w-[520px] p-6">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-lg font-semibold text-foreground">Add Custom Prompt</h3>
          <button onClick={onClose} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex flex-col gap-4">
          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">Title <span className="text-primary">*</span></label>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Weekly Report Generator"
              className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40" />
          </div>

          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">Category</label>
            <select value={category} onChange={(e) => setCategory(e.target.value)}
              className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40">
              <option value="">Custom</option>
              {promptCategories.map((cat) => (
                <option key={cat.id} value={cat.id}>{cat.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">Prompt Content <span className="text-primary">*</span></label>
            <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={8}
              placeholder="Enter your prompt..."
              className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 resize-none" />
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30">Cancel</button>
            <button onClick={handleSubmit} disabled={saving || !title.trim() || !content.trim()}
              className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed">
              {saving ? "Saving..." : "Add Prompt"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PromptLibrary() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [customPrompts, setCustomPrompts] = useState<CustomPrompt[]>([]);

  const inactiveCategoryClass = "bg-muted/60 text-foreground/75 hover:bg-muted/80 hover:text-foreground";

  useEffect(() => {
    promptsApi.list().then((r) => setCustomPrompts(r.prompts)).catch(() => {});
  }, []);

  // Filtered custom (my) prompts
  const filteredCustom = useMemo(() => {
    let result: (Prompt | CustomPrompt)[] = customPrompts;
    if (selectedCategory && selectedCategory !== "custom") {
      result = result.filter((p) => p.category === selectedCategory);
    }
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (p) => p.title.toLowerCase().includes(query) || p.content.toLowerCase().includes(query),
      );
    }
    return result;
  }, [customPrompts, searchQuery, selectedCategory]);

  // Filtered built-in (community) prompts
  const filteredBuiltIn = useMemo(() => {
    let result: Prompt[] = prompts;
    if (selectedCategory === "custom") {
      result = [];
    } else if (selectedCategory) {
      result = result.filter((p) => p.category === selectedCategory);
    }
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (p) => p.title.toLowerCase().includes(query) || p.content.toLowerCase().includes(query),
      );
    }
    return result;
  }, [searchQuery, selectedCategory]);

  // Reset page when filters change
  useEffect(() => setPage(0), [searchQuery, selectedCategory]);

  const totalPages = Math.max(1, Math.ceil(filteredBuiltIn.length / PAGE_SIZE));
  const pagedBuiltIn = filteredBuiltIn.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const handleUsePrompt = (content: string, category: string) => {
    const queenId = categoryToQueen[category];
    if (!queenId) return;
    sessionStorage.setItem(`queenFirstMessage:${queenId}`, content);
    navigate(`/queen/${queenId}?new=1`);
  };

  const handleAddPrompt = useCallback(async (title: string, category: string, content: string) => {
    const created = await promptsApi.create(title, category, content);
    setCustomPrompts((prev) => [created, ...prev]);
  }, []);

  const handleDeletePrompt = useCallback(async (id: string) => {
    await promptsApi.delete(id);
    setCustomPrompts((prev) => prev.filter((p) => p.id !== id));
  }, []);

  const customCount = customPrompts.length;

  return (
    <div className="flex-1 flex overflow-hidden">
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border/60">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-baseline gap-3">
              <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-primary" />
                Prompt Library
              </h2>
              <span className="text-xs text-muted-foreground">
                {customCount > 0 ? `${customCount} custom · ` : ""}{prompts.length} community prompts
              </span>
            </div>
            <button onClick={() => setAddModalOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90">
              <Plus className="w-3.5 h-3.5" />
              Add Prompt
            </button>
          </div>

          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text" placeholder="Search prompts by title or content..." value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 rounded-lg border border-border/60 bg-background text-sm focus:outline-none focus:border-primary/40 focus:ring-1 focus:ring-primary/20"
            />
          </div>
        </div>

        {/* Category filter */}
        <div className="px-6 py-3 border-b border-border/60 bg-muted/20">
          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={() => setSelectedCategory(null)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium ${selectedCategory === null ? "bg-primary text-primary-foreground" : inactiveCategoryClass}`}>
              All Categories
            </button>
            {customCount > 0 && (
              <button onClick={() => setSelectedCategory("custom")}
                className={`px-3 py-1.5 rounded-full text-xs font-medium ${selectedCategory === "custom" ? "bg-primary text-primary-foreground" : inactiveCategoryClass}`}>
                My Prompts <span className="ml-1.5 opacity-60">({customCount})</span>
              </button>
            )}
            {promptCategories.map((cat) => (
              <button key={cat.id} onClick={() => setSelectedCategory(cat.id)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium ${selectedCategory === cat.id ? "bg-primary text-primary-foreground" : inactiveCategoryClass}`}>
                {cat.name} <span className="ml-1.5 opacity-60">({cat.count})</span>
              </button>
            ))}
          </div>
        </div>

        {/* Prompts grid */}
        <div className="flex-1 overflow-y-auto p-6">
          {filteredCustom.length === 0 && pagedBuiltIn.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <Sparkles className="w-10 h-10 text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">No prompts found</p>
              <p className="text-xs text-muted-foreground/60 mt-1">Try adjusting your search or category filter</p>
            </div>
          ) : (
            <>
              {/* My Prompts section */}
              {filteredCustom.length > 0 && (
                <div className="mb-8">
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">My Prompts</h3>
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
                    {filteredCustom.map((prompt) => (
                      <PromptCard
                        key={prompt.id as string}
                        prompt={prompt}
                        onUse={handleUsePrompt}
                        onDelete={"custom" in prompt && prompt.custom ? () => handleDeletePrompt(prompt.id as string) : undefined}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Community Prompts section */}
              {pagedBuiltIn.length > 0 && selectedCategory !== "custom" && (
                <div>
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Community Prompts</h3>
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
                    {pagedBuiltIn.map((prompt) => (
                      <PromptCard
                        key={`builtin-${prompt.id}`}
                        prompt={prompt}
                        onUse={handleUsePrompt}
                      />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="px-6 py-3 border-t border-border/60 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, filteredBuiltIn.length)} of {filteredBuiltIn.length}
            </span>
            <div className="flex items-center gap-1">
              <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 disabled:opacity-30 disabled:cursor-not-allowed">
                <ChevronLeft className="w-4 h-4" />
              </button>
              {Array.from({ length: totalPages }, (_, i) => i)
                .filter((i) => i === 0 || i === totalPages - 1 || Math.abs(i - page) <= 1)
                .reduce<(number | "...")[]>((acc, i) => {
                  if (acc.length > 0) {
                    const last = acc[acc.length - 1];
                    if (typeof last === "number" && i - last > 1) acc.push("...");
                  }
                  acc.push(i);
                  return acc;
                }, [])
                .map((item, idx) =>
                  item === "..." ? (
                    <span key={`ellipsis-${idx}`} className="px-1 text-xs text-muted-foreground">...</span>
                  ) : (
                    <button key={item} onClick={() => setPage(item as number)}
                      className={`min-w-[28px] h-7 rounded-md text-xs font-medium ${page === item ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground hover:bg-muted/60"}`}>
                      {(item as number) + 1}
                    </button>
                  ),
                )}
              <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 disabled:opacity-30 disabled:cursor-not-allowed">
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      <AddPromptModal open={addModalOpen} onClose={() => setAddModalOpen(false)} onSave={handleAddPrompt} />
    </div>
  );
}
