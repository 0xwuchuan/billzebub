import type { ImportRecord, StatementCoverageReport } from "../api";
import { StatementCoveragePanel } from "../components/StatementCoveragePanel";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { useEntrance } from "../hooks/useEntrance";
import { openedLabel } from "../lib/labels";

export function ImportsPage({
  imports,
  coverage,
  selectedId,
  accountId,
  today,
  includeDismissed,
  saving,
  onSelect,
  onSelectAccount,
  onClearAccount,
  onOpenReview,
  onShowDismissed,
  onDismiss,
  onDismissFailed,
}: {
  imports: ImportRecord[];
  coverage: StatementCoverageReport | null;
  selectedId: string | null;
  accountId: string | null;
  today: Date;
  includeDismissed: boolean;
  saving: string | null;
  onSelect: (id: string) => void;
  onSelectAccount: (accountId: string) => void;
  onClearAccount: () => void;
  onOpenReview: (reviewId: string) => void;
  onShowDismissed: (show: boolean) => void;
  onDismiss: (id: string) => void;
  onDismissFailed: () => void;
}) {
  const fresh = useEntrance("imports");
  const visible =
    accountId === null
      ? imports
      : imports.filter((item) => item.financial_account_id === accountId);
  const selected =
    visible.find((item) => item.id === selectedId) ?? visible[0] ?? null;
  const failedVisible = visible.filter(
    (item) => item.status === "failed" && item.dismissed_at === null,
  );
  return (
    <div className={`imports-stage${fresh ? " stage-enter" : ""}`}>
      <StatementCoveragePanel
        coverage={coverage}
        selectedAccountId={accountId}
        onSelectAccount={onSelectAccount}
        onClearAccount={onClearAccount}
      />
      <div className="desk">
        <section className="card queue-pane" aria-label="Import history">
          <div className="panel-head">
            <h2>Extractions</h2>
            <span
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                flexWrap: "wrap",
                justifyContent: "flex-end",
              }}
            >
              <span className="muted" style={{ fontSize: "var(--bz-text-sm)" }}>
                {visible.length} recorded
              </span>
              <button
                className="chip"
                type="button"
                aria-pressed={includeDismissed}
                onClick={() => {
                  onShowDismissed(!includeDismissed);
                }}
              >
                Show dismissed
              </button>
              {failedVisible.length > 0 ? (
                <Button
                  variant="ghost"
                  disabled={saving !== null}
                  onClick={onDismissFailed}
                >
                  Dismiss failed
                </Button>
              ) : null}
            </span>
          </div>
          {visible.length === 0 ? (
            <p className="empty">
              {accountId === null
                ? "No Extractions yet. Accepted statements and Shortcut ingest appear here."
                : "No Extractions for this Financial Account yet."}
            </p>
          ) : (
            <div className="queue-list">
              {visible.map((item) => (
                <ImportRow
                  key={item.id}
                  item={item}
                  current={selected !== null && selected.id === item.id}
                  onSelect={onSelect}
                />
              ))}
            </div>
          )}
        </section>
        <section className="card evidence-pane" aria-live="polite">
          {selected === null ? (
            <p className="empty">
              Process a statement or Shortcut ingest to inspect Extraction
              status.
            </p>
          ) : (
            <ImportDetail
              item={selected}
              today={today}
              saving={saving}
              onOpenReview={onOpenReview}
              onDismiss={onDismiss}
            />
          )}
        </section>
      </div>
    </div>
  );
}

function ImportRow({
  item,
  current,
  onSelect,
}: {
  item: ImportRecord;
  current: boolean;
  onSelect: (id: string) => void;
}) {
  const failed = item.status === "failed";
  const dismissed = item.dismissed_at !== null;
  return (
    <button
      className={`queue-item${failed && !dismissed ? " is-blocking" : ""}`}
      type="button"
      aria-current={current}
      onClick={() => {
        onSelect(item.id);
      }}
    >
      <span>
        <span className="queue-title">{adapterLabel(item)}</span>
        <span className="queue-reason">{periodLabel(item)}</span>
      </span>
      <span className="queue-right">
        <Badge tone={dismissed ? "count" : failed ? "blocking" : "confirmed"}>
          {dismissed ? "dismissed" : item.status}
        </Badge>
        <span className="queue-age">
          {item.failure_code === null
            ? `${item.claim_count} Claims`
            : item.failure_code}
        </span>
      </span>
    </button>
  );
}

function ImportDetail({
  item,
  today,
  saving,
  onOpenReview,
  onDismiss,
}: {
  item: ImportRecord;
  today: Date;
  saving: string | null;
  onOpenReview: (reviewId: string) => void;
  onDismiss: (id: string) => void;
}) {
  const fresh = useEntrance(`import:${item.id}`);
  const failed = item.status === "failed";
  const dismissed = item.dismissed_at !== null;
  return (
    <>
      <div className="panel-head">
        <div>
          <Badge tone={dismissed ? "count" : failed ? "blocking" : "confirmed"}>
            {dismissed ? "dismissed" : item.status}
          </Badge>
          <h2 style={{ marginTop: 8 }}>{adapterLabel(item)}</h2>
        </div>
        <span
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
            flexWrap: "wrap",
            justifyContent: "flex-end",
          }}
        >
          {failed && !dismissed ? (
            <Button
              variant="ghost"
              disabled={saving !== null}
              onClick={() => {
                onDismiss(item.id);
              }}
            >
              Dismiss
            </Button>
          ) : null}
          {item.active_review_id !== null ? (
            <Button
              variant="ghost"
              onClick={() => {
                onOpenReview(item.active_review_id ?? "");
              }}
            >
              Open Pending Review
            </Button>
          ) : null}
        </span>
      </div>
      <div className={`evidence-body${fresh ? " stage-enter" : ""}`}>
        <p className={`prompt${failed && !dismissed ? " is-blocking" : ""}`}>
          {dismissed
            ? `This failed Extraction is hidden from the default Imports list${item.failure_code === null ? "" : ` (${item.failure_code})`}.`
            : failed
              ? `This Extraction failed${item.failure_code === null ? "" : ` (${item.failure_code})`} and created no Claims.`
              : `Accepted Extraction with ${item.claim_count} Claims.`}
        </p>
        <dl className="kv">
          <dt>Financial Account</dt>
          <dd>{item.financial_account_name ?? "Unmapped"}</dd>
          <dt>Adapter</dt>
          <dd>{adapterLabel(item)}</dd>
          <dt>Period</dt>
          <dd>{periodLabel(item)}</dd>
          <dt>Failure code</dt>
          <dd>{item.failure_code ?? "None"}</dd>
          <dt>Parser version</dt>
          <dd>{item.parser_version}</dd>
          <dt>Claims</dt>
          <dd>{item.claim_count}</dd>
          <dt>Candidate rows</dt>
          <dd>
            {item.candidate_row_count === null
              ? "Not recorded"
              : String(item.candidate_row_count)}
          </dd>
          <dt>Duplicate arrivals</dt>
          <dd>{item.duplicate_arrivals}</dd>
          <dt>Active review</dt>
          <dd>{item.active_review_id === null ? "None" : "Pending"}</dd>
          <dt>Recorded</dt>
          <dd>{openedLabel(item.created_at, today)}</dd>
        </dl>
      </div>
    </>
  );
}

function adapterLabel(item: ImportRecord): string {
  return item.adapter_key ?? "Unknown adapter";
}

function periodLabel(item: ImportRecord): string {
  if (item.period_start !== null && item.period_end !== null) {
    return `${item.period_start} – ${item.period_end}`;
  }
  if (item.statement_date !== null) {
    return item.statement_date;
  }
  return "No statement period";
}
