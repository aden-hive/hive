export default function PageLoader() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
      <div className="flex flex-col items-center gap-2 rounded-3xl border border-border bg-card p-8 shadow-lg shadow-black/5">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary/20 border-t-primary" />
        <p className="text-sm font-medium text-secondary-foreground">Loading page…</p>
      </div>
    </div>
  );
}