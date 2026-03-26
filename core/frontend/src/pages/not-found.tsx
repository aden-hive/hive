import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center px-6 text-center">
      <h1 className="text-5xl font-semibold text-foreground">404</h1>
      <p className="mt-3 text-sm text-muted-foreground">Page not found</p>
      <p className="mt-1 text-sm text-muted-foreground/80">
        The page you’re looking for doesn’t exist.
      </p>
      <Link
        to="/"
        className="mt-6 inline-flex items-center rounded-lg border border-border/40 px-4 py-2 text-sm font-medium text-foreground hover:bg-muted/40 transition-colors"
      >
        Back to Home
      </Link>
    </div>
  );
}
