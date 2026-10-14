export type Money = {
  amount: string;
  currency: string;
};

export type Category = {
  id: string;
  name: string;
  parent_id: string | null;
  active: boolean;
  description?: string | null;
};

export type MerchantRule = {
  normalized_key: string;
  category_id: string;
  category_name: string;
  source: "owner" | "jev";
  label?: string;
};

export type MerchantGroupTransaction = {
  transaction_id: string;
  review_id: string;
  version: number;
  counterparty: string;
  amount: string;
  currency: string;
  effective_date: string;
  kind: string;
};

export type MerchantGroup = {
  normalized_key: string;
  label: string;
  count: number;
  etag: string;
  transactions: MerchantGroupTransaction[];
};

export type MerchantApplyResult = {
  normalized_key: string;
  label: string;
  category_id: string;
  applied: { transaction_id: string; version: number }[];
  excluded_transaction_ids: string[];
  memory: MerchantRule | null;
  undo_etag: string;
};

export type OwnerIdentity = {
  login: string;
  name: string;
};

export type FinancialAccountAlias = {
  id: string;
  alias_kind: string;
  display_label: string;
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
  dismissed_at: string | null;
};

export type ImportPage = {
  items: ImportRecord[];
};

export type CoverageStatus = "present" | "missing" | "partial";

export type StatementCoverageMonth = {
  month: string;
  status: CoverageStatus;
};

export type StatementCoverageAccount = {
  id: string;
  display_name: string;
  slug: string;
  months: StatementCoverageMonth[];
};

export type StatementCoverageReport = {
  as_of: string;
  timezone: string;
  window_months: number;
  accounts: StatementCoverageAccount[];
};

export type RecurringCadence = "weekly" | "monthly" | "yearly" | "custom_days";

export type RecurringStatus =
  "proposed" | "active" | "paused" | "ended" | "dismissed";

export type RecurringSource = "detected" | "manual";

export type RecurringSeries = {
  id: string;
  counterparty: string;
  amount: Money;
  amount_min: Money | null;
  amount_max: Money | null;
  cadence: RecurringCadence;
  interval_days: number | null;
  next_expected_date: string;
  category_id: string | null;
  primary_account_id: string | null;
  status: RecurringStatus;
  source: RecurringSource;
  confidence: string | null;
  last_matched_tx_id: string | null;
  last_amount: Money;
  linked_count: number;
  missed: boolean;
  notes: string | null;
  cluster_key: string;
};

export type RecurringSummary = {
  month: string;
  total: Money;
  upcoming: RecurringSeries[];
};

export type RecurringPatch = {
  counterparty?: string;
  amount?: string;
  currency?: string;
  cadence?: RecurringCadence;
  interval_days?: number | null;
  next_expected_date?: string;
  category_id?: string | null;
  primary_account_id?: string | null;
  status?: "active" | "paused" | "ended";
};

export type RecurringCreateInput = {
  counterparty: string;
  amount: string;
  currency: string;
  cadence: RecurringCadence;
  next_expected_date: string;
  interval_days?: number;
  category_id?: string;
  primary_account_id?: string;
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

export async function getImports(
  includeDismissed = false,
): Promise<ImportPage> {
  const query = includeDismissed ? "?include_dismissed=true" : "";
  return request<ImportPage>(`/api/v1/imports${query}`);
}

export async function getStatementCoverage(): Promise<StatementCoverageReport> {
  return request<StatementCoverageReport>("/api/v1/statement-coverage");
}

export async function getImport(extractionId: string): Promise<ImportRecord> {
  return request<ImportRecord>(
    `/api/v1/imports/${encodeURIComponent(extractionId)}`,
  );
}

export async function dismissImport(
  extractionId: string,
): Promise<ImportRecord> {
  return request<ImportRecord>(
    `/api/v1/imports/${encodeURIComponent(extractionId)}/dismiss`,
    {
      method: "POST",
      headers: mutationHeaders(),
      body: JSON.stringify({}),
    },
  );
}

export async function dismissFailedImports(): Promise<{
  dismissed_count: number;
}> {
  return request<{ dismissed_count: number }>(
    "/api/v1/imports/dismiss-failed",
    {
      method: "POST",
      headers: mutationHeaders(),
      body: JSON.stringify({}),
    },
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

export async function getRecurrings(
  status?: RecurringStatus,
): Promise<{ items: RecurringSeries[] }> {
  const query =
    status === undefined ? "" : `?status=${encodeURIComponent(status)}`;
  return request<{ items: RecurringSeries[] }>(`/api/v1/recurrings${query}`);
}

export async function getProposedRecurrings(): Promise<{
  items: RecurringSeries[];
}> {
  return request<{ items: RecurringSeries[] }>("/api/v1/recurrings/proposed");
}

export async function getRecurringSummary(
  limit = 3,
): Promise<RecurringSummary> {
  return request<RecurringSummary>(`/api/v1/recurrings/summary?limit=${limit}`);
}

export async function createRecurring(
  input: RecurringCreateInput,
): Promise<RecurringSeries> {
  return request<RecurringSeries>("/api/v1/recurrings", {
    method: "POST",
    headers: mutationHeaders(),
    body: JSON.stringify(input),
  });
}

export async function updateRecurring(
  seriesId: string,
  patch: RecurringPatch,
): Promise<RecurringSeries> {
  return request<RecurringSeries>(
    `/api/v1/recurrings/${encodeURIComponent(seriesId)}`,
    {
      method: "PATCH",
      headers: mutationHeaders(),
      body: JSON.stringify(patch),
    },
  );
}

export async function dismissRecurring(
  seriesId: string,
): Promise<RecurringSeries> {
  return request<RecurringSeries>(
    `/api/v1/recurrings/${encodeURIComponent(seriesId)}/dismiss`,
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

export async function listMerchantGroups(): Promise<{
  items: MerchantGroup[];
}> {
  return request<{ items: MerchantGroup[] }>("/api/v1/reviews/merchant-groups");
}

export async function listMerchantRules(): Promise<{ items: MerchantRule[] }> {
  return request<{ items: MerchantRule[] }>("/api/v1/merchant-memory");
}

export async function applyMerchantGroup(input: {
  normalizedKey: string;
  categoryId: string;
  excludeTransactionIds: string[];
  etag: string;
}): Promise<MerchantApplyResult> {
  return request<MerchantApplyResult>("/api/v1/reviews/merchant-groups/apply", {
    method: "POST",
    headers: mutationHeaders(input.etag),
    body: JSON.stringify({
      normalized_key: input.normalizedKey,
      category_id: input.categoryId,
      exclude_transaction_ids: input.excludeTransactionIds,
    }),
  });
}

export async function undoMerchantGroup(input: {
  normalizedKey: string;
  categoryId: string;
  transactions: { transaction_id: string; version: number }[];
  excludedTransactionIds: string[];
  etag: string;
}): Promise<{
  restored_transaction_ids: string[];
  memory: MerchantRule | null;
}> {
  return request("/api/v1/reviews/merchant-groups/undo", {
    method: "POST",
    headers: mutationHeaders(input.etag),
    body: JSON.stringify({
      normalized_key: input.normalizedKey,
      category_id: input.categoryId,
      transactions: input.transactions,
      excluded_transaction_ids: input.excludedTransactionIds,
    }),
  });
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
        return new ApiError(`${body.title}. Open Settings to continue.`);
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
