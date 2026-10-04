import type { IssuedToken, IntegrationToken } from "../../api";
import { Button } from "../ui/Button";

export function TokensPanel({
  tokens,
  issuedToken,
  saving,
  onIssueToken,
  onRotateToken,
  onRevokeToken,
  onDismissIssuedToken,
  mode = "all",
  actionVariant = "primary",
}: {
  tokens: IntegrationToken[];
  issuedToken: IssuedToken | null;
  saving: string | null;
  onIssueToken: () => Promise<void>;
  onRotateToken: (tokenId: string) => Promise<void>;
  onRevokeToken: (tokenId: string) => Promise<void>;
  onDismissIssuedToken: () => void;
  mode?: "all" | "list" | "issue";
  actionVariant?: "primary" | "ghost";
}) {
  return (
    <div className="stack">
      {mode !== "issue" ? (
        tokens.length === 0 ? (
          <p className="muted">No active Shortcut tokens.</p>
        ) : (
          tokens.map((token) => (
            <div key={token.id} className="token-row">
              <span>
                <strong>{token.name}</strong>
                <span className="muted">Prefix {token.prefix}</span>
              </span>
              <span className="onboard-nav-actions">
                <Button
                  variant="outline"
                  disabled={saving === token.id}
                  onClick={() => {
                    void onRotateToken(token.id);
                  }}
                >
                  Rotate
                </Button>
                <Button
                  variant="ghost"
                  disabled={saving === token.id}
                  onClick={() => {
                    void onRevokeToken(token.id);
                  }}
                >
                  Revoke
                </Button>
              </span>
            </div>
          ))
        )
      ) : null}
      {mode !== "list" ? (
        <>
          <p className="muted settings-help">
            The token can create Shortcut Claims only. Its plaintext is shown
            once and never written to localStorage.
          </p>
          <Button
            variant={actionVariant}
            disabled={saving === "token"}
            onClick={() => {
              void onIssueToken();
            }}
          >
            {saving === "token" ? "Issuing…" : "Issue Shortcut token"}
          </Button>
          {issuedToken !== null ? (
            <div className="probe">
              <p className="probe-line">
                Copy this token now. It will not be shown again.
              </p>
              <code className="path">{issuedToken.plaintext}</code>
              <Button variant="ghost" onClick={onDismissIssuedToken}>
                Hide token
              </Button>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
