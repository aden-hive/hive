import { type ReactNode } from "react";

interface NexusCardProps {
  children: ReactNode;
  className?: string;
  noPadding?: boolean;
}

export function NexusCard({ children, className = "", noPadding = false }: NexusCardProps) {
  return (
    <div className={`bg-card border border-border rounded-xl shadow-card ${noPadding ? "" : "p-5"} ${className}`}>
      {children}
    </div>
  );
}
