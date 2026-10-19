import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { PartyPopper, X } from "lucide-react";
import { ProviderLogo } from "@/components/ProviderLogo";
import { getProviderLogo } from "@/data/providerLogos";

/** Render the provider icon/logo with a small chip background — same
 * style as CredentialsModal's CredIconInline (intentionally simple
 * copy rather than export gymnastics; the icon is one of five). */
function ProviderIcon({ provider, size = 18 }: { provider: string; size?: number }) {
  const logo = getProviderLogo(provider);
  if (!logo) return <PartyPopper width={size} height={size} />;
  return <ProviderLogo provider={provider} size={size} />;
}

interface Props {
  open: boolean;
  provider: string;
  accountEmail: string | null;
  onClose: () => void;
}

/** Shown once an OAuth provider finishes connecting. Every queen whose
 * role default includes the provider's tools receives them automatically
 * — no per-queen action needed — so this is a plain confirmation, with a
 * quiet link to the Tool Library for anyone who wants to fine-tune which
 * queens get what. */
export default function QueensAuthorizationDialog({
  open,
  provider,
  accountEmail,
  onClose,
}: Props) {
  const navigate = useNavigate();

  const providerLabel = useMemo(() => {
    const logo = getProviderLogo(provider);
    return logo?.name || provider.charAt(0).toUpperCase() + provider.slice(1);
  }, [provider]);

  if (!open) return null;

  const goToToolLibrary = () => {
    onClose();
    navigate("/skills-library?tab=mcp");
  };

  return (
    <>
      <div
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md pointer-events-auto flex flex-col">
          {/* Close */}
          <div className="flex items-center justify-end px-3 pt-3">
            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="px-6 pb-4 flex flex-col items-center text-center">
            <div className="relative mb-4">
              <div className="w-16 h-16 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center">
                <ProviderIcon provider={provider} size={32} />
              </div>
              <div className="absolute -bottom-1.5 -right-1.5 w-7 h-7 rounded-full bg-primary text-primary-foreground flex items-center justify-center shadow-md">
                <PartyPopper className="w-4 h-4" />
              </div>
            </div>

            <h2 className="text-base font-semibold text-foreground">
              {providerLabel} connected
            </h2>
            {accountEmail && (
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Authorized as {accountEmail}
              </p>
            )}
            <p className="text-sm text-muted-foreground mt-3 max-w-xs">
              All your queens now have access to the {providerLabel} tool suite.
              You're ready to go.
            </p>
          </div>

          {/* Footer */}
          <div className="flex flex-col items-center gap-2.5 px-6 pb-6">
            <button
              onClick={onClose}
              className="w-full px-3 py-2 rounded-md text-sm font-semibold bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Done
            </button>
            <button
              onClick={goToToolLibrary}
              className="text-[11px] text-muted-foreground hover:text-foreground underline underline-offset-2 transition-colors"
            >
              Configure tools per queen
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
