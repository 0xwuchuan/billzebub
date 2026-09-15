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

export type OwnerIdentity = {
  login: string;
  name: string;
};

export type FinancialAccountAlias = {
  id: string;
  alias_kind: string;
  masked_value: string;
};

export type FinancialAccount = {
  id: string;
  slug: string;
  display_name: string;
  institution: string;
  kind: "credit_card" | "paylah" | string;
  default_currency: string;
  statement_adapter_key: string | null;
  active: boolean;
  password_configured: boolean;
  inbox_ready: boolean;
  aliases: FinancialAccountAlias[];
};

export type StatementAdapter = {
  key: string;
  institution: string;
  kind: string;
};

export type IntegrationToken = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
};

export type IssuedToken = IntegrationToken & {
  plaintext: string;
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

export type ImportRecord = {
  id: string;
  source_artifact_id: string;
  financial_account_id: string | null;
  financial_account_name: string | null;
  status: string;
  adapter_key: string | null;
  parser_version: string;
  statement_date: string | null;
  period_start: string | null;
  period_end: string | null;
  candidate_row_count: number | null;
  claim_count: number;
  failure_code: string | null;
  validation_report: Record<string, unknown>;
  duplicate_arrivals: number;
  active_review_id: string | null;
  supersedes_extraction_id: string | null;
  created_at: string;
  accepted_at: string | null;
};

export type ImportPage = {
  items: ImportRecord[];
};

export type CreateFinancialAccountInput = {
  slug: string;
  display_name: string;
  institution: string;
  kind: "credit_card" | "paylah";
  default_currency: string;
  statement_adapter_key?: string;
  statement_account_identifier?: string;
  statement_password_secret?: string;
};

export class ApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function getWhoami(): Promise<OwnerIdentity> {
  return request<OwnerIdentity>("/api/v1/whoami");
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

export async function getImports(): Promise<ImportPage> {
  return request<ImportPage>("/api/v1/imports");
}

export async function getImport(extractionId: string): Promise<ImportRecord> {
  return request<ImportRecord>(
    `/api/v1/imports/${encodeURIComponent(extractionId)}`,
  );
}

export async function getCategories(): Promise<{ items: Category[] }> {
  return request<{ items: Category[] }>("/api/v1/categories");
}

export async function createCategory(
  name: string,
  parentId?: string,
): Promise<Category> {
  return request<Category>("/api/v1/categories", {
    method: "POST",
    headers: mutationHeaders(),
    body: JSON.stringify({
      name,
      parent_id: parentId === undefined ? null : parentId,
    }),
  });
}

export async function getFinancialAccounts(): Promise<{
  items: FinancialAccount[];
}> {
  return request<{ items: FinancialAccount[] }>("/api/v1/financial-accounts");
}

export async function createFinancialAccount(
  input: CreateFinancialAccountInput,
): Promise<FinancialAccount> {
  return request<FinancialAccount>("/api/v1/financial-accounts", {
    method: "POST",
    headers: mutationHeaders(),
    body: JSON.stringify(input),
  });
}

export async function createWalletAlias(
  accountId: string,
  cardLabel: string,
): Promise<FinancialAccountAlias> {
  return request<FinancialAccountAlias>(
    `/api/v1/financial-accounts/${accountId}/aliases`,
    {
      method: "POST",
      headers: mutationHeaders(),
      body: JSON.stringify({
        kind: "apple_wallet_card",
        card_label: cardLabel,
      }),
    },
  );
}

export async function getStatementAdapters(): Promise<{
  items: StatementAdapter[];
}> {
  return request<{ items: StatementAdapter[] }>("/api/v1/statement-adapters");
}

export async function getTokens(): Promise<{ items: IntegrationToken[] }> {
  return request<{ items: IntegrationToken[] }>("/api/v1/tokens");
}

export async function issueToken(input: {
  name: string;
  kind: "integration" | "agent";
  scopes: string[];
}): Promise<IssuedToken> {
  return request<IssuedToken>("/api/v1/tokens", {
    method: "POST",
    headers: mutationHeaders(),
    body: JSON.stringify(input),
  });
}

export async function rotateToken(tokenId: string): Promise<IssuedToken> {
  return request<IssuedToken>(`/api/v1/tokens/${tokenId}/rotate`, {
    method: "POST",
    headers: mutationHeaders(),
    body: JSON.stringify({}),
  });
}

export async function revokeToken(
  tokenId: string,
): Promise<{ id: string; revoked: boolean }> {
  return request<{ id: string; revoked: boolean }>(
    `/api/v1/tokens/${tokenId}/revoke`,
    {
      method: "POST",
      headers: mutationHeaders(),
      body: JSON.stringify({}),
    },
  );
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

function mutationHeaders(ifMatch?: string): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Billzebub-CSRF": "bzb-spa",
  };
  if (ifMatch !== undefined) {
    headers["If-Match"] = ifMatch;
  }
  return headers;
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
    throw await apiErrorFrom(response);
  }
  return (await response.json()) as T;
}

async function apiErrorFrom(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as {
      title?: unknown;
      next_step?: unknown;
    };
    if (typeof body.title === "string" && body.title !== "") {
      if (body.next_step === "configure_via_setup") {
        return new ApiError(`${body.title}. Open Setup to continue.`);
      }
      return new ApiError(body.title);
    }
  } catch {
    return new ApiError(
      "The workspace could not complete that request. Refresh and try again.",
    );
  }
  return new ApiError(
    "The workspace could not complete that request. Refresh and try again.",
  );
}
