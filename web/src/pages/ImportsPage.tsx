import type { ImportRecord } from "../api";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { useEntrance } from "../hooks/useEntrance";
import { openedLabel } from "../lib/labels";

export function ImportsPage({
  imports,
  selectedId,
  today,
  onSelect,
  onOpenReview,
}: {
  imports: ImportRecord[];
  selectedId: string | null;
  today: Date;
  onSelect: (id: string) => void;
  onOpenReview: (reviewId: string) => void;
}) {
  const fresh = useEntrance("imports");
  const selected =
    imports.find((item) => item.id === selectedId) ?? imports[0] ?? null;
  return (
    <div className={`desk${fresh ? " stage-enter" : ""}`}>
      <section className="card queue-pane" aria-label="Import history">
        <div className="panel-head">
          <h2>Extractions</h2>
          <span className="muted" style={{ fontSize: "var(--bz-text-sm)" }}>
            {imports.length} recorded
          </span>
        </div>
        {imports.length === 0 ? (
          <p className="empty">
            No Extractions yet. Accepted statements and Shortcut ingest appear
            here.
          </p>
        ) : (
          <div className="queue-list">
            {imports.map((item) => (
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
            Process a statement or Shortcut ingest to inspect Extraction status.
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
