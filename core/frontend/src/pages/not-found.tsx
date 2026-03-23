import { useNavigate } from "react-router-dom";
import { Hexagon, ArrowLeft } from "lucide-react";
import TopBar from "@/components/TopBar";

export default function NotFound() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <TopBar />

      <div className="flex-1 flex flex-col items-center justify-center p-6">
        <div className="text-center max-w-md">
          <div
            className="inline-flex w-14 h-14 rounded-2xl items-center justify-center mb-6"
            style={{
              backgroundColor: "hsl(45,95%,58%,0.1)",
              border: "1.5px solid hsl(45,95%,58%,0.25)",
              boxShadow: "0 0 24px hsl(45,95%,58%,0.08)",
            }}
          >
            <Hexagon className="w-7 h-7 text-primary" />
          </div>

          <h1 className="text-5xl font-bold text-foreground mb-2">404</h1>
          <p className="text-lg text-muted-foreground mb-6">
            This page doesn't exist in the hive.
          </p>

          <button
            onClick={() => navigate("/")}
            className="inline-flex items-center gap-2 text-sm font-medium px-5 py-2.5 rounded-lg border border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/30 hover:bg-primary/[0.03] transition-all"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Back to Home</span>
          </button>
        </div>
      </div>
    </div>
  );
}
