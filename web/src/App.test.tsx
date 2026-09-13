import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const transaction = {
  id: "00000000-0000-0000-0000-000000000010",
  version: 1,
  financial_account: {
    id: "00000000-0000-0000-0000-000000000011",
    name: "Synthetic Card",
  },
  counterparty: "Synthetic Coffee",
  posted_amount: { amount: "-12.34", currency: "SGD" },
  authorized_amount: null,
  effective_date: "2026-01-10",
  kind: "expense",
  category_splits: [
    {
      id: "00000000-0000-0000-0000-000000000012",
      name: "Uncategorized",
      amount: { amount: "12.34", currency: "SGD" },
    },
  ],
  reviews: [
    {
      id: "00000000-0000-0000-0000-000000000013",
      condition_code: "categorization_needed",
      severity: "attention",
      version: 1,
      allowed_decisions: ["categorize"],
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("loads a workspace and categorizes a Transaction through the protected owner resource", async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/v1/transactions") {
          return response({ items: [transaction], next_cursor: null });
        }
        if (url === "/api/v1/reviews") {
          return response({
            items: [
              {
                id: "00000000-0000-0000-0000-000000000013",
                subject_type: "transaction",
                subject_id: transaction.id,
                condition_code: "categorization_needed",
                severity: "attention",
                status: "pending",
                version: 1,
                allowed_decisions: ["categorize"],
                context: {},
                created_at: "2026-01-10T00:00:00+00:00",
                updated_at: "2026-01-10T00:00:00+00:00",
              },
            ],
            next_cursor: null,
          });
        }
        if (url === "/api/v1/categories") {
          return response({
            items: [
              {
                id: "00000000-0000-0000-0000-000000000099",
                name: "Synthetic Food",
                parent_id: null,
                active: true,
              },
            ],
          });
        }
        if (url.endsWith("/category") && init?.method === "PUT") {
          return response({
            ...transaction,
            version: 2,
            category_splits: [
              {
                id: "00000000-0000-0000-0000-000000000099",
                name: "Synthetic Food",
                amount: { amount: "12.34", currency: "SGD" },
              },
            ],
            reviews: [],
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Billzebub" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Synthetic Coffee")).toBeInTheDocument();
    expect(screen.getByText("−SGD 12.34")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Category for Synthetic Coffee"), {
      target: { value: "00000000-0000-0000-0000-000000000099" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Categorize" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/transactions/00000000-0000-0000-0000-000000000010/category",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({
            category_id: "00000000-0000-0000-0000-000000000099",
          }),
        }),
      );
    });
    expect(await screen.findByText("Categorized")).toBeInTheDocument();
  });
});

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
