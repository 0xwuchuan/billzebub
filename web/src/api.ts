export type Money = {
  amount: string;
  currency: string;
};

export type Category = {
  id: string;
  name: string;
  parent_id: string | null;
  active: boolean;
};

export type TransactionReview = {
  id: string;
  condition_code: string;
  severity: "attention" | "blocking";
  version: number;
  allowed_decisions: string[];
};

export type Transaction = {
  id: string;
  version: number;
  financial_account: { id: string; name: string };
  counterparty: string;
  posted_amount: Money;
  authorized_amount: Money | null;
  effective_date: string;
  kind: string;
  category_splits: Array<{ id: string; name: string; amount: Money }>;
  reviews: TransactionReview[];
};

export type TransactionPage = {
  items: Transaction[];
  next_cursor: string | null;
};

export type Review = {
  id: string;
  subject_type: string;
  subject_id: string;
  condition_code: string;
  severity: "attention" | "blocking";
  status: "pending" | "resolved" | "cancelled";
  version: number;
  allowed_decisions: string[];
  context: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ReviewPage = {
  items: Review[];
  next_cursor: string | null;
};

export class ApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function getTransactions(
  cursor?: string,
): Promise<TransactionPage> {
  const query =
    cursor === undefined ? "" : `?cursor=${encodeURIComponent(cursor)}`;
  return request<TransactionPage>(`/api/v1/transactions${query}`);
}

export async function getReviews(): Promise<ReviewPage> {
  return request<ReviewPage>("/api/v1/reviews");
}

export async function getCategories(): Promise<{ items: Category[] }> {
  return request<{ items: Category[] }>("/api/v1/categories");
}

export async function categorizeTransaction(
  transaction: Transaction,
  categoryId: string,
): Promise<Transaction> {
  return request<Transaction>(
    `/api/v1/transactions/${transaction.id}/category`,
    {
      method: "PUT",
      headers: mutationHeaders(transactionEtag(transaction)),
      body: JSON.stringify({ category_id: categoryId }),
    },
  );
}

export async function decideReview(
  review: Review,
  choice: string,
): Promise<Review> {
  return request<Review>(`/api/v1/reviews/${review.id}/decisions`, {
    method: "POST",
    headers: mutationHeaders(reviewEtag(review)),
    body: JSON.stringify({ choice }),
  });
}

function mutationHeaders(ifMatch: string): HeadersInit {
  return {
    "Content-Type": "application/json",
    "If-Match": ifMatch,
    "X-Billzebub-CSRF": "bzb-spa",
  };
}

function transactionEtag(transaction: Transaction): string {
  return `"transaction:${transaction.id}:v${transaction.version}"`;
}

function reviewEtag(review: Review): string {
  return `"review:${review.id}:v${review.version}"`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { Accept: "application/json", ...init?.headers },
  });
  if (!response.ok) {
    throw new ApiError(
      "The workspace could not complete that request. Refresh and try again.",
    );
  }
  return (await response.json()) as T;
}
