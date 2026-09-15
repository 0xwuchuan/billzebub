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
}: {
  tokens: IntegrationToken[];
  issuedToken: IssuedToken | null;
  saving: string | null;
  onIssueToken: () => Promise<void>;
  onRotateToken: (tokenId: string) => Promise<void>;
  onRevokeToken: (tokenId: string) => Promise<void>;
  onDismissIssuedToken: () => void;
}) {
  return (
    <div className="stack">
      <p className="muted" style={{ fontSize: "var(--bz-text-xs)" }}>
        Scope shortcut:claims:create. Plaintext is shown once and is not written
        to localStorage.
      </p>
      {tokens.map((token) => (
        <div key={token.id} className="token-row">
          <span>
            {token.name} · {token.prefix}
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
      ))}
      <Button
        variant="outline"
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
    </div>
  );
}
