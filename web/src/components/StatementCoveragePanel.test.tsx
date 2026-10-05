import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { StatementCoverageReport } from "../api";
import { StatementCoveragePanel } from "./StatementCoveragePanel";

const coverage: StatementCoverageReport = {
  as_of: "2026-09-15",
  timezone: "Asia/Singapore",
  window_months: 6,
  accounts: [
    {
      id: "acct-citi",
      display_name: "Citi PremierMiles",
      slug: "citi-premiermiles",
      months: [
        { month: "2026-04", status: "present" },
        { month: "2026-05", status: "partial" },
        { month: "2026-06", status: "missing" },
      ],
    },
  ],
};

afterEach(() => {
  window.sessionStorage.clear();
});

describe("StatementCoveragePanel", () => {
  it("stays collapsed until the strip is opened", () => {
    const onSelectAccount = vi.fn();
    render(
      <StatementCoveragePanel
        coverage={coverage}
        selectedAccountId={null}
        onSelectAccount={onSelectAccount}
      />,
    );

    const toggle = screen.getByRole("button", { name: /Statement coverage/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(/1 missing/)).toBeInTheDocument();
    expect(screen.getByText(/1 partial/)).toBeInTheDocument();
    expect(screen.getByText("last 6 mo")).toBeInTheDocument();
    expect(screen.getByText("Asia/Singapore")).toBeInTheDocument();
    expect(
      screen.queryByText(/Missing months have no accepted/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Jun · missing/ }),
    ).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText(/Missing months have no accepted/),
    ).toBeInTheDocument();
    const month = screen.getByRole("button", {
      name: "Citi PremierMiles · Jun · missing",
    });
    expect(month).toHaveTextContent("Jun");
    expect(month).not.toHaveTextContent("missing");
    expect(
      screen.getByTitle("Citi PremierMiles · Apr · present"),
    ).toHaveTextContent("Apr");
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("present")).toBeInTheDocument();
    expect(screen.getByText("partial")).toBeInTheDocument();
    expect(screen.getByText("missing")).toBeInTheDocument();

    fireEvent.click(month);
    expect(onSelectAccount).toHaveBeenCalledWith("acct-citi");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("button", { name: /Jun · missing/ }),
    ).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem("bz.imports.coverageExpanded")).toBe(
      "false",
    );
  });

  it("restores an expanded strip from the session", () => {
    window.sessionStorage.setItem("bz.imports.coverageExpanded", "true");
    render(
      <StatementCoveragePanel
        coverage={coverage}
        selectedAccountId="acct-citi"
        onSelectAccount={() => undefined}
        onClearAccount={() => undefined}
      />,
    );

    expect(
      screen.getByRole("button", { name: /Statement coverage/ }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", { name: "All accounts" }),
    ).toBeInTheDocument();
    expect(screen.getByText("May")).toBeInTheDocument();
  });

  it("says all present when every month is covered", () => {
    render(
      <StatementCoveragePanel
        coverage={{
          ...coverage,
          accounts: [
            {
              id: "acct-citi",
              display_name: "Citi PremierMiles",
              slug: "citi-premiermiles",
              months: [{ month: "2026-04", status: "present" }],
            },
          ],
        }}
        selectedAccountId={null}
        onSelectAccount={() => undefined}
      />,
    );

    expect(screen.getByText("all present")).toBeInTheDocument();
    expect(screen.queryByText(/missing/)).not.toBeInTheDocument();
  });
});
