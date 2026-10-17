import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AmbiguousMatchReview } from "./AmbiguousMatchReview";

const originalMatchMedia = window.matchMedia;

afterEach(() => {
  window.matchMedia = originalMatchMedia;
});

function candidate(
  id: string,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    statement_claim_id: id,
    claim_id: id,
    score: 80,
    reasons: [],
    raw_description: "BLUE BOTTLE COFFEE",
    normalized_counterparty: "blue bottle",
    amount: "8.00",
    currency: "SGD",
    posted_date: "2026-10-11",
    transaction_date: "2026-10-11",
    last4: "4242",
    statement_id: `statement-${id}`,
    statement_identity: `dbs:2026-10-31:${id}-digest`,
    statement_label: "DBS WW",
    issuer: "dbs",
    period_start: "2026-10-01",
    period_end: "2026-10-31",
    amount_delta: "0.00",
    day_delta: 1,
    match_reasons: [],
    ...patch,
  };
}

function context(
  candidates: Record<string, unknown>[],
): Record<string, unknown> {
  return {
    candidate_count: candidates.length,
    provisional: {
      claim_id: "wallet-claim",
      counterparty: { raw: "Blue Bottle", normalized: "blue bottle" },
      amount: "8.00",
      currency: "SGD",
      occurred_at: {
        date: "2026-10-10",
        time: "09:41:00",
        timezone: "Asia/Singapore",
      },
      last4: "4242",
      source: "wallet",
      card_alias: "DBS Altitude",
    },
    candidates,
  };
}

function renderMatch(
  candidates: Record<string, unknown>[],
  props: Partial<Parameters<typeof AmbiguousMatchReview>[0]> = {},
) {
  const onMatch = vi.fn();
  const onReject = vi.fn();
  const onOpenTransaction = vi.fn();
  const view = render(
    <AmbiguousMatchReview
      context={context(candidates)}
      onMatch={onMatch}
      onReject={onReject}
      onOpenTransaction={onOpenTransaction}
      {...props}
    />,
  );
  return { ...view, onMatch, onReject, onOpenTransaction };
}

function visibleText(node: HTMLElement): string {
  const clone = node.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("details:not([open])").forEach((element) => {
    element.remove();
  });
  return clone.textContent ?? "";
}

describe("AmbiguousMatchReview", () => {
  it("keeps ids inside a closed Details disclosure and shows the why line", () => {
    const { container } = renderMatch([
      candidate("line-a", { score: 90 }),
      candidate("line-b", {
        score: 40,
        day_delta: 2,
        posted_date: "2026-10-12",
      }),
    ]);
    const shown = visibleText(container);
    expect(shown).not.toContain("✓");
    expect(shown).not.toContain("same amount");
    expect(shown).toContain("10 Oct · 09:41 · DBS Altitude ·· 4242 · Wallet");
    expect(shown).not.toContain("line-a-digest");
    expect(shown).not.toContain("wallet-claim");
    expect(shown).toContain("Exact amount");
    expect(shown).toContain("+1 day");
    expect(shown).toContain("Best match");
    const primary = screen.getByRole("button", { name: "Match to this" });
    expect(primary).toHaveClass("btn-primary");
    expect(screen.getAllByRole("button", { name: "This one" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "None of these" })).toHaveClass(
      "btn-ghost",
    );
    expect(
      screen.getAllByRole("button", { name: "Match to this" }),
    ).toHaveLength(1);

    const block = screen
      .getAllByText("Details")[1]
      ?.closest("details") as HTMLDetailsElement;
    expect(block.open).toBe(false);
    block.open = true;
    expect(block).toHaveTextContent("line-a-digest");
  });

  it("uses Match and Not this one when there is one candidate", () => {
    const { onMatch, onReject } = renderMatch([candidate("only")]);
    fireEvent.click(screen.getByRole("button", { name: "Match" }));
    expect(onMatch).toHaveBeenCalledWith("match:only");
    fireEvent.click(screen.getByRole("button", { name: "Not this one" }));
    expect(onReject).toHaveBeenCalled();
    expect(screen.queryByText("Best match")).not.toBeInTheDocument();
  });

  it("offers to keep a Wallet charge when nothing is left", () => {
    const { onReject, onOpenTransaction } = renderMatch([]);
    expect(
      screen.queryByText(/matched 0 statement lines/),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("No statement lines left to match."),
    ).toBeInTheDocument();
    expect(screen.getByText("Keep it as a Wallet charge?")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Keep as Wallet charge" }),
    );
    expect(onReject).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Open transaction" }));
    expect(onOpenTransaction).toHaveBeenCalled();
  });

  it("pages candidates after five and disables one already matched", () => {
    renderMatch([
      candidate("open", { score: 90 }),
      candidate("used", { score: 80, matched_to: "Blue Bottle Raffles" }),
      ...[3, 4, 5, 6, 7].map((rank) =>
        candidate(`line-${rank}`, { score: 70 - rank }),
      ),
    ]);
    expect(
      screen.getByText("Already matched to Blue Bottle Raffles (Undo there)"),
    ).toBeInTheDocument();
    expect(screen.queryByText("7th")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show 2 more" }));
    expect(screen.getByText("7th")).toBeInTheDocument();
  });

  it("selects with the keyboard and confirms on Enter", () => {
    const { onMatch } = renderMatch([
      candidate("first", { score: 90 }),
      candidate("second", { score: 40 }),
    ]);
    fireEvent.keyDown(document.body, { key: "2" });
    fireEvent.keyDown(document.body, { key: "Enter" });
    expect(onMatch).toHaveBeenCalledWith("match:second");
  });

  it("shows a category chip only when a category is passed", () => {
    const { rerender } = renderMatch([candidate("only")], {
      categoryName: "Dining",
    });
    expect(screen.getByText("Dining")).toBeInTheDocument();
    rerender(
      <AmbiguousMatchReview
        context={context([candidate("only")])}
        onMatch={() => undefined}
        onReject={() => undefined}
        onOpenTransaction={() => undefined}
      />,
    );
    expect(screen.queryByText("Dining")).not.toBeInTheDocument();
  });

  it("uses the phone dock and a radio for the selected line", () => {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })) as typeof window.matchMedia;
    const { onMatch } = renderMatch([
      candidate("first", { score: 90, posted_date: "2026-10-11" }),
      candidate("second", { score: 40, posted_date: "2026-10-12" }),
    ]);
    const radios = screen.getAllByRole("radio");
    expect(radios[0]).toBeChecked();
    expect(radios[1]).not.toBeChecked();
    expect(
      screen.queryByRole("button", { name: "This one" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/same amount/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/Exact amount/).length).toBeGreaterThan(0);
    fireEvent.click(
      screen.getByRole("button", { name: "Match to Blue Bottle · 11 Oct" }),
    );
    expect(onMatch).toHaveBeenCalledWith("match:first");
  });
});
