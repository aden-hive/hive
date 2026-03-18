import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { CheckCircle2, Sparkles, Wrench, Lightbulb, Tag, Zap } from "lucide-react";
import type { AgentTemplate } from "@/data/mock-data";

interface TemplateDetailDialogProps {
  template: AgentTemplate | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApply: (template: AgentTemplate) => void;
  applying?: boolean;
}

export function TemplateDetailDialog({ template, open, onOpenChange, onApply, applying }: TemplateDetailDialogProps) {
  if (!template) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto bg-card border-border p-0 gap-0">
        {/* Header */}
        <DialogHeader className="px-6 pt-6 pb-4 border-b border-border/50">
          <div className="flex items-center gap-2 mb-1">
            {template.tags.map((tag) => (
              <span key={tag} className="text-[10px] font-semibold px-2 py-0.5 bg-primary/8 text-primary rounded-full">{tag}</span>
            ))}
          </div>
          <DialogTitle className="text-lg font-bold font-display tracking-tight text-foreground">{template.title}</DialogTitle>
          <p className="text-sm text-muted-foreground leading-relaxed mt-1">{template.description}</p>
        </DialogHeader>

        <div className="px-6 py-5 space-y-6">
          {/* Capabilities */}
          <section>
            <h4 className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
              <Sparkles size={12} className="text-primary" /> Capabilities
            </h4>
            <div className="space-y-2">
              {template.capabilities.map((cap, i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <CheckCircle2 size={14} className="text-success shrink-0 mt-0.5" />
                  <span className="text-[13px] text-foreground/85">{cap}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Use Cases */}
          <section>
            <h4 className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
              <Lightbulb size={12} className="text-warning" /> Example Use Cases
            </h4>
            <div className="grid grid-cols-1 gap-2">
              {template.useCases.map((uc, i) => (
                <div key={i} className="px-3 py-2.5 bg-muted/40 border border-border/50 rounded-lg text-[12px] text-foreground/80">
                  {uc}
                </div>
              ))}
            </div>
          </section>

          {/* Enabled Tools */}
          <section>
            <h4 className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
              <Wrench size={12} className="text-primary" /> Enabled Tools
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {template.config.enabledTools.map((tool) => (
                <span key={tool} className="flex items-center gap-1.5 px-2.5 py-1.5 bg-muted/60 border border-border/50 rounded-lg text-[11px] font-medium text-foreground/75">
                  <Wrench size={10} className="text-muted-foreground" /> {tool}
                </span>
              ))}
            </div>
          </section>

          {/* Settings Preview */}
          <section>
            <h4 className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
              <Zap size={12} className="text-primary" /> Configuration
            </h4>
            <div className="bg-muted/30 border border-border/50 rounded-lg p-4 space-y-2.5">
              <div className="flex justify-between text-[12px]">
                <span className="text-muted-foreground">Model</span>
                <span className="font-medium text-foreground font-mono text-[11px]">{template.config.model.split("/")[1]}</span>
              </div>
              <div className="flex justify-between text-[12px]">
                <span className="text-muted-foreground">Max Steps</span>
                <span className="font-medium text-foreground tabular-nums">{template.config.maxSteps}</span>
              </div>
              <div className="flex justify-between text-[12px]">
                <span className="text-muted-foreground">Response Style</span>
                <span className="font-medium text-foreground">{template.config.responseStyle}</span>
              </div>
              <div className="flex justify-between text-[12px]">
                <span className="text-muted-foreground">Memory</span>
                <span className="font-medium text-foreground">{template.config.memoryEnabled ? "Enabled" : "Disabled"}</span>
              </div>
            </div>
          </section>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border/50 bg-muted/20">
          <button
            onClick={() => onApply(template)}
            disabled={applying}
            className="w-full py-2.5 bg-primary text-primary-foreground rounded-lg text-[13px] font-semibold hover:opacity-90 transition-all shadow-sm disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {applying ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" />
                Applying…
              </>
            ) : (
              <>
                <Zap size={14} /> Use Template
              </>
            )}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
