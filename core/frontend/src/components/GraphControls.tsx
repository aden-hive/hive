import { memo, useState, useRef, useEffect } from "react";
import { ZoomIn, ZoomOut, Move, Download, Search, X, ChevronDown, Maximize2 } from "lucide-react";

interface GraphControlsProps {
  /** Current zoom scale (0.3 to 3) */
  scale: number;
  /** Callback when zoom in is clicked */
  onZoomIn: () => void;
  /** Callback when zoom out is clicked */
  onZoomOut: () => void;
  /** Callback when reset view is clicked */
  onResetView: () => void;
  /** Callback when export is requested */
  onExport: (format: "png" | "svg") => void;
  /** Whether search is active */
  searchActive?: boolean;
  /** Callback when search toggle is clicked */
  onSearchToggle?: () => void;
  /** Current search term */
  searchTerm?: string;
  /** Callback when search term changes */
  onSearchChange?: (term: string) => void;
  /** Number of search results */
  searchResultCount?: number;
  /** Current result index (0-based) */
  currentResultIndex?: number;
  /** Callback for next result */
  onNextResult?: () => void;
  /** Callback for previous result */
  onPrevResult?: () => void;
  /** Callback to clear search */
  onClearSearch?: () => void;
  /** Optional additional controls */
  children?: React.ReactNode;
  /** Whether the graph is in building state */
  building?: boolean;
  /** Version string to display */
  version?: string;
  /** Title of the graph */
  title?: string;
  /** Run button (optional, can be passed from parent) */
  runButton?: React.ReactNode;
}

export const GraphControls = memo(function GraphControls({
  scale,
  onZoomIn,
  onZoomOut,
  onResetView,
  onExport,
  searchActive = false,
  onSearchToggle,
  searchTerm = "",
  onSearchChange,
  searchResultCount = 0,
  currentResultIndex = 0,
  onNextResult,
  onPrevResult,
  onClearSearch,
  children,
  building,
  version,
  title,
  runButton,
}: GraphControlsProps) {
  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Close export menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(event.target as Node)) {
        setShowExportMenu(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Focus search input when search becomes active
  useEffect(() => {
    if (searchActive && searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, [searchActive]);

  const handleExportClick = (format: "png" | "svg") => {
    onExport(format);
    setShowExportMenu(false);
  };

  return (
    <div className="px-5 pt-4 pb-2 flex items-center justify-between">
      {/* Left side - title and version */}
      <div className="flex items-center gap-2">
        <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">
          {title || "Pipeline"}
        </p>
        {version && (
          <span className="text-[10px] font-mono font-medium text-muted-foreground/60 border border-border/30 rounded px-1 py-0.5 leading-none">
            {version}
          </span>
        )}
        {building && (
          <span className="text-[10px] text-primary/60 animate-pulse">Building...</span>
        )}
      </div>

      {/* Right side - controls */}
      <div className="flex items-center gap-1">
        {/* Search button */}
        {onSearchToggle && (
          <button
            onClick={onSearchToggle}
            className={`p-1.5 rounded-md transition-colors ${
              searchActive
                ? "bg-primary/20 text-primary"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
            }`}
            title="Search nodes"
          >
            <Search className="w-3.5 h-3.5" />
          </button>
        )}

        {/* Zoom out button */}
        <button
          onClick={onZoomOut}
          className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          title="Zoom out (Ctrl+Scroll)"
        >
          <ZoomOut className="w-3.5 h-3.5" />
        </button>

        {/* Zoom percentage */}
        <span className="text-[10px] text-muted-foreground min-w-[40px] text-center">
          {Math.round(scale * 100)}%
        </span>

        {/* Zoom in button */}
        <button
          onClick={onZoomIn}
          className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          title="Zoom in (Ctrl+Scroll)"
        >
          <ZoomIn className="w-3.5 h-3.5" />
        </button>

        {/* Reset view button */}
        <button
          onClick={onResetView}
          className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          title="Reset view"
        >
          <Move className="w-3.5 h-3.5" />
        </button>

        {/* Export dropdown */}
        <div className="relative" ref={exportMenuRef}>
          <button
            onClick={() => setShowExportMenu(!showExportMenu)}
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            title="Export graph"
          >
            <Download className="w-3.5 h-3.5" />
          </button>
          {showExportMenu && (
            <div className="absolute right-0 top-full mt-1 bg-card border border-border rounded-md shadow-lg z-10 py-1 min-w-[120px]">
              <button
                onClick={() => handleExportClick("png")}
                className="block w-full text-left px-3 py-1.5 text-xs hover:bg-muted/50 transition-colors"
              >
                Export as PNG
              </button>
              <button
                onClick={() => handleExportClick("svg")}
                className="block w-full text-left px-3 py-1.5 text-xs hover:bg-muted/50 transition-colors"
              >
                Export as SVG
              </button>
            </div>
          )}
        </div>

        {/* Run button (optional) */}
        {runButton}

        {/* Additional controls */}
        {children}
      </div>

      {/* Search bar (collapsible) */}
      {searchActive && onSearchChange && (
        <div className="absolute top-12 left-5 right-5 z-20 animate-in fade-in slide-in-from-top-2 duration-200">
          <div className="bg-card border border-primary/30 rounded-lg shadow-lg">
            <div className="flex items-center gap-2 px-3 py-2">
              <Search className="w-4 h-4 text-muted-foreground flex-shrink-0" />
              <input
                ref={searchInputRef}
                type="text"
                value={searchTerm}
                onChange={(e) => onSearchChange(e.target.value)}
                placeholder="Search nodes by name or ID..."
                className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
              {searchResultCount > 0 && (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-muted-foreground">
                    {currentResultIndex + 1}/{searchResultCount}
                  </span>
                  <button
                    onClick={onPrevResult}
                    className="p-1 rounded hover:bg-muted/50 transition-colors"
                    title="Previous result"
                  >
                    ←
                  </button>
                  <button
                    onClick={onNextResult}
                    className="p-1 rounded hover:bg-muted/50 transition-colors"
                    title="Next result"
                  >
                    →
                  </button>
                </div>
              )}
              <button
                onClick={onClearSearch}
                className="p-1 rounded hover:bg-muted/50 transition-colors text-muted-foreground hover:text-foreground"
                title="Clear search"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            {searchResultCount === 0 && searchTerm && (
              <div className="px-3 pb-2 text-xs text-muted-foreground">
                No nodes matching "{searchTerm}"
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
});

export default GraphControls;