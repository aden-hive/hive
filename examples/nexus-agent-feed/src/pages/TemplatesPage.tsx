import { useState } from "react";
import { TemplateCard } from "@/components/nexus/TemplateCard";
import { TemplateDetailDialog } from "@/components/nexus/TemplateDetailDialog";
import { AGENT_TEMPLATES, type AgentTemplate } from "@/data/mock-data";
import { Search, Sparkles, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

interface TemplatesPageProps {
  activeTemplateId?: string | null;
  onApplyTemplate?: (template: AgentTemplate) => void;
}

export function TemplatesPage({ activeTemplateId, onApplyTemplate }: TemplatesPageProps) {
  const [search, setSearch] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState<AgentTemplate | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [applying, setApplying] = useState(false);

  const filtered = AGENT_TEMPLATES.filter(t =>
    t.title.toLowerCase().includes(search.toLowerCase()) ||
    t.tags.some(tag => tag.toLowerCase().includes(search.toLowerCase()))
  );

  const handleSelect = (template: AgentTemplate) => {
    setSelectedTemplate(template);
    setDialogOpen(true);
  };

  const handleApply = async (template: AgentTemplate) => {
    setApplying(true);
    // Simulate brief loading
    await new Promise(r => setTimeout(r, 600));
    onApplyTemplate?.(template);
    setApplying(false);
    setDialogOpen(false);
    toast.success(`"${template.title}" template applied`, {
      description: "Your workspace has been configured with this template.",
      icon: <CheckCircle2 size={16} className="text-success" />,
    });
  };

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-8 max-w-6xl mx-auto w-full">
      <header className="mb-8 flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-foreground tracking-tight font-display">Agent Templates</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Start with a pre-built agent and customize it for your workflow.
          </p>
        </div>
        <div className="relative w-full sm:w-64">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/50" />
          <input
            type="text"
            placeholder="Search templates..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-background border border-border rounded-lg pl-9 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary/15 focus:border-primary/30 outline-none text-foreground placeholder:text-muted-foreground/50 transition-all"
          />
        </div>
      </header>

      {filtered.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {filtered.map((template) => (
            <TemplateCard
              key={template.id}
              template={template}
              onSelect={handleSelect}
              isActive={activeTemplateId === template.id}
            />
          ))}
        </div>
      ) : (
        <div className="text-center py-20">
          <Sparkles size={28} className="mx-auto text-muted-foreground/30 mb-3" />
          <h3 className="text-sm font-semibold text-foreground mb-1 font-display">No templates found</h3>
          <p className="text-xs text-muted-foreground">Try adjusting your search query.</p>
        </div>
      )}

      <TemplateDetailDialog
        template={selectedTemplate}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onApply={handleApply}
        applying={applying}
      />
    </div>
  );
}
