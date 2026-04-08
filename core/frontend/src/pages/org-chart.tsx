import { Network } from "lucide-react";

export default function OrgChart() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-6">
      <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
        <Network className="w-8 h-8 text-primary/60" />
      </div>
      <h1 className="text-lg font-semibold text-foreground mb-2">Org Chart</h1>
      <p className="text-sm text-muted-foreground text-center max-w-sm">
        Visualize your colony structure, queen assignments, and worker relationships. Coming soon.
      </p>
    </div>
  );
}
