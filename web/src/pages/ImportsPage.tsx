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
  onSelect,
  onSelectAccount,
  onClearAccount,
  onOpenReview,
}: {
  imports: ImportRecord[];
  coverage: StatementCoverageReport | null;
  selectedId: string | null;
  accountId: string | null;
  today: Date;
  onSelect: (id: string) => void;
  onSelectAccount: (accountId: string) => void;
  onClearAccount: () => void;
  onOpenReview: (reviewId: string) => void;
}) {
  const fresh = useEntrance("imports");
  const visible =
    accountId === null
      ? imports
      : imports.filter((item) => item.financial_account_id === accountId);
  const selected =
    visible.find((item) => item.id === selectedId) ?? visible[0] ?? null;
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
            <span className="muted" style={{ fontSize: "var(--bz-text-sm)" }}>
              {visible.length} recorded
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
              onOpenReview={onOpenReview}
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
  return (
    <button
      className={`queue-item${failed ? " is-blocking" : ""}`}
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
        <Badge tone={failed ? "blocking" : "confirmed"}>{item.status}</Badge>
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
  onOpenReview,
}: {
  item: ImportRecord;
  today: Date;
  onOpenReview: (reviewId: string) => void;
}) {
  const fresh = useEntrance(`import:${item.id}`);
  const failed = item.status === "failed";
  return (
    <>
      <div className="panel-head">
        <div>
          <Badge tone={failed ? "blocking" : "confirmed"}>{item.status}</Badge>
          <h2 style={{ marginTop: 8 }}>{adapterLabel(item)}</h2>
        </div>
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
      </div>
      <div className={`evidence-body${fresh ? " stage-enter" : ""}`}>
        <p className={`prompt${failed ? " is-blocking" : ""}`}>
          {failed
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
