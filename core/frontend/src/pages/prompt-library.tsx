import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Copy, Check, Sparkles, MessageSquarePlus, AlertCircle } from "lucide-react";
import { prompts, promptCategories, categoryToQueen, queenNames } from "@/data/prompts";

function PromptCard({ prompt, onUse }: { prompt: typeof prompts[0]; onUse: (content: string, category: string) => void }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(false);
  const queenId = categoryToQueen[prompt.category];
  const queenName = queenNames[queenId] || "Queen";

  const handleCopy = async () => {
    try {
      setError(false);
      await navigator.clipboard.writeText(prompt.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Clipboard copy failed:", err);
      setError(true);
      setTimeout(() => setError(false), 3000);
    }
  };

  return (
    <div className="group rounded-lg border border-border/60 bg-card p-4 hover:border-primary/30 hover:shadow-sm transition-all">
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="text-sm font-medium text-foreground line-clamp-1">
          {prompt.title}
        </h3>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={handleCopy}
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
            title={error ? "Copy failed" : "Copy prompt"}
          >
            {error ? (
              <AlertCircle className="w-3.5 h-3.5 text-destructive" />
            ) : copied ? (
              <Check className="w-3.5 h-3.5 text-emerald-500" />
            ) : (
              <Copy className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground line-clamp-3 leading-relaxed mb-3">
        {prompt.content}
      </p>
      <button
        onClick={() => onUse(prompt.content, prompt.category)}
        className="w-full flex items-center justify-center gap-1.5 rounded-md border border-primary/20 bg-primary/[0.04] py-1.5 text-xs font-medium text-primary hover:bg-primary/[0.08] transition-colors"
      >
        <MessageSquarePlus className="w-3.5 h-3.5" />
        Ask {queenName}
      </button>
    </div>
  );
}

export default function PromptLibrary() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const inactiveCategoryClass =
    "bg-muted/60 text-foreground/75 hover:bg-muted/80 hover:text-foreground";

  const filteredPrompts = useMemo(() => {
    let result = prompts;
    
    if (selectedCategory) {
      result = result.filter((p) => p.category === selectedCategory);
    }
    
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (p) =>
          p.title.toLowerCase().includes(query) ||
          p.content.toLowerCase().includes(query)
      );
    }
    
    return result;
  }, [searchQuery, selectedCategory]);

  const handleUsePrompt = (content: string, category: string) => {
    const queenId = categoryToQueen[category];
    sessionStorage.setItem(`queenFirstMessage:${queenId}`, content);
    navigate(`/queen/${queenId}?new=1`);
  };

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border/60">
          <div className="flex items-baseline gap-3 mb-4">
            <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-primary" />
              Prompt Library
            </h2>
            <span className="text-xs text-muted-foreground">
              {prompts.length} prompts across {promptCategories.length} categories
            </span>
          </div>
          
          {/* Search bar */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search prompts by title or content..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 rounded-lg border border-border/60 bg-background text-sm focus:outline-none focus:border-primary/40 focus:ring-1 focus:ring-primary/20"
            />
          </div>
        </div>

        {/* Category filter */}
        <div className="px-6 py-3 border-b border-border/60 bg-muted/20">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => setSelectedCategory(null)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                selectedCategory === null
                  ? "bg-primary text-primary-foreground"
                  : inactiveCategoryClass
              }`}
            >
              All Categories
            </button>
            {promptCategories.map((cat) => (
              <button
                key={cat.id}
                onClick={() => setSelectedCategory(cat.id)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                  selectedCategory === cat.id
                    ? "bg-primary text-primary-foreground"
                    : inactiveCategoryClass
                }`}
              >
                {cat.name}
                <span className="ml-1.5 opacity-60">({cat.count})</span>
              </button>
            ))}
          </div>
        </div>

        {/* Prompts grid */}
        <div className="flex-1 overflow-y-auto p-6">
          {filteredPrompts.length > 0 ? (
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
              {filteredPrompts.map((prompt) => (
                <PromptCard key={prompt.id} prompt={prompt} onUse={handleUsePrompt} />
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <Sparkles className="w-10 h-10 text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">No prompts found</p>
              <p className="text-xs text-muted-foreground/60 mt-1">
                Try adjusting your search or category filter
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
