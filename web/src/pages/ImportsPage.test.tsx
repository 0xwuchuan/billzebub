import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ImportRecord } from "../api";
import { ImportsPage } from "./ImportsPage";

function extraction(overrides: Partial<ImportRecord>): ImportRecord {
  return {
    id: "00000000-0000-0000-0000-000000000017",
    source_artifact_id: "00000000-0000-0000-0000-000000000015",
    financial_account_id: "acct-dbs",
    financial_account_name: "DBS Altitude",
    status: "failed",
    adapter_key: "dbs-credit-card",
    parser_version: "v1",
    statement_date: "2026-08-31",
    period_start: "2026-08-01",
    period_end: "2026-08-31",
    candidate_row_count: 0,
    claim_count: 0,
    failure_code: "account_mismatch",
    validation_report: {},
    duplicate_arrivals: 0,
    active_review_id: "review-1",
    supersedes_extraction_id: null,
    created_at: "2026-08-31T00:00:00+00:00",
    accepted_at: null,
    dismissed_at: null,
    ...overrides,
  };
}

const failed = extraction({});
const accepted = extraction({
  id: "00000000-0000-0000-0000-000000000018",
  financial_account_id: "acct-citi",
  financial_account_name: "Citi PremierMiles",
  status: "accepted",
  adapter_key: "citi-credit-card",
  claim_count: 2,
  failure_code: null,
  active_review_id: null,
  accepted_at: "2026-08-31T00:00:00+00:00",
});

function renderImports(
  imports: ImportRecord[],
  extras: Partial<Parameters<typeof ImportsPage>[0]> = {},
) {
  const onShowDismissed = vi.fn();
  const onDismissFailed = vi.fn();
  render(
    <ImportsPage
      imports={imports}
      coverage={null}
      selectedId={null}
      accountId={null}
      today={new Date("2026-09-15T00:00:00Z")}
      includeDismissed={false}
      saving={null}
      onSelect={() => undefined}
      onSelectAccount={() => undefined}
      onClearAccount={() => undefined}
      onOpenReview={() => undefined}
      onShowDismissed={onShowDismissed}
      onDismiss={() => undefined}
      onDismissFailed={onDismissFailed}
      {...extras}
    />,
  );
  return { onShowDismissed, onDismissFailed };
}

describe("ImportsPage extraction filters", () => {
  it("defaults to Failed and filters the queue without changing detail fields", () => {
    renderImports([failed, accepted]);

    expect(screen.getByRole("button", { name: "Failed" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Accepted" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getAllByText("dbs-credit-card").length).toBeGreaterThan(0);
    expect(screen.queryByText("citi-credit-card")).not.toBeInTheDocument();
    expect(screen.getAllByText("failed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("account_mismatch").length).toBeGreaterThan(0);
    expect(screen.getByText("View all import details")).toBeInTheDocument();
    expect(screen.getByText("Failure code")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open Pending Review" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Dismiss failed" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Accepted" }));
    expect(screen.getAllByText("citi-credit-card").length).toBeGreaterThan(0);
    expect(screen.queryByText("dbs-credit-card")).not.toBeInTheDocument();
    expect(screen.getAllByText("accepted").length).toBeGreaterThan(0);
    expect(screen.getByText("2 claims")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getAllByText("dbs-credit-card").length).toBeGreaterThan(0);
    expect(screen.getAllByText("citi-credit-card").length).toBeGreaterThan(0);
  });

  it("keeps Show dismissed and falls back to All when nothing failed is active", () => {
    const dismissed = extraction({
      id: "00000000-0000-0000-0000-000000000019",
      adapter_key: "paylah_shortcut",
      dismissed_at: "2026-09-01T00:00:00+00:00",
      failure_code: "invalid_payload_shape",
    });
    const { onShowDismissed } = renderImports([accepted, dismissed], {
      includeDismissed: true,
    });

    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getAllByText("citi-credit-card").length).toBeGreaterThan(0);
    expect(screen.getAllByText("PayLah").length).toBeGreaterThan(0);
    expect(screen.getAllByText("dismissed").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Failed" }));
    expect(screen.queryByText("PayLah")).not.toBeInTheDocument();
    expect(screen.queryByText("citi-credit-card")).not.toBeInTheDocument();
    expect(
      screen.getAllByText("No Extractions match this filter.").length,
    ).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Show dismissed" }));
    expect(onShowDismissed).toHaveBeenCalledWith(false);
  });
});
