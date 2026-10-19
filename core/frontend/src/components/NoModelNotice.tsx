import { Cpu } from "lucide-react";
import { useModelOptional } from "@/context/ModelContext";
import { openSettings } from "@/lib/settings-events";

/**
 * Sits above a chat's composer while no AI model is set up: the queen can't
 * reply until one is, so say so and link straight to the model settings.
 * Renders nothing while the model config is loading, or once a model works.
 */
export default function NoModelNotice() {
  const model = useModelOptional();
  if (!model || model.loading || model.hasApiKey) return null;
  return (
    <div
      role="status"
      className="mx-4 mt-3 flex items-center gap-3 rounded-lg border border-primary/25 bg-primary/[0.06] px-3.5 py-2.5 text-xs"
    >
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
        <Cpu className="h-3.5 w-3.5" />
      </span>
      <span className="min-w-0 text-muted-foreground">
        <span className="font-medium text-foreground">No AI model yet.</span> Connect one and your queens can reply.
      </span>
      <button
        type="button"
        onClick={() => openSettings("byok")}
        className="ml-auto shrink-0 font-medium text-primary underline-offset-2 hover:underline"
      >
        Set up a model →
      </button>
    </div>
  );
}
