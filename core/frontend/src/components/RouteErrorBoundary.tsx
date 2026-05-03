import { Component, type ErrorInfo, type ReactNode } from "react";

interface RouteErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

interface RouteErrorBoundaryProps {
  children: ReactNode;
}

export default class RouteErrorBoundary extends Component<
  RouteErrorBoundaryProps,
  RouteErrorBoundaryState
> {
  state: RouteErrorBoundaryState = {
    hasError: false,
    error: null,
  };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Route load error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-background px-4 py-12 text-center text-foreground">
          <div className="max-w-md rounded-3xl border border-border bg-card p-8 shadow-lg shadow-black/5">
            <h1 className="text-xl font-semibold">Unable to load this page</h1>
            <p className="mt-3 text-sm text-muted-foreground">
              Something went wrong while loading the requested route.
            </p>
            <pre className="mt-4 overflow-x-auto rounded-xl bg-muted p-4 text-xs text-muted-foreground">
              {this.state.error?.message}
            </pre>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-6 inline-flex rounded-full bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground transition hover:bg-primary/90"
            >
              Reload page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}