export type RoutePage =
  | "overview"
  | "spending"
  | "review"
  | "transactions"
  | "recurrings"
  | "imports"
  | "onboarding"
  | "settings";

export type ReviewFilter = "" | "blocking" | "attention";

export type ConfirmationFilter = "" | "confirmed" | "provisional" | "review";

export type RecurringTab = "" | "proposed" | "active";

export type Route = {
  page: RoutePage;
  reviewFilter: ReviewFilter;
  confirmation: ConfirmationFilter;
  drawerId: string | null;
  importId: string | null;
  accountId: string | null;
  recurringTab: RecurringTab;
};

export const emptyRoute = {
  reviewFilter: "" as const,
  confirmation: "" as const,
  drawerId: null,
  importId: null,
  accountId: null,
  recurringTab: "" as const,
};

export function defaultRoute(onboarded: boolean): Route {
  return {
    page: onboarded ? "overview" : "onboarding",
    ...emptyRoute,
  };
}

export function parseHash(hash: string, onboarded: boolean): Route {
  const raw = hash.replace(/^#\/?/, "");
  const [pathPart, queryPart] = raw.split("?");
  const path = pathPart ?? "";
  const params = new URLSearchParams(queryPart ?? "");
  const accountParam = params.get("account");
  const accountId =
    accountParam !== null && accountParam !== "" ? accountParam : null;
  const [page, ...restParts] = path.split("/");
  const rest = restParts.join("/");
  if (page === "onboarding" || page === "setup") {
    return {
      page: onboarded ? "settings" : "onboarding",
      ...emptyRoute,
    };
  }
  if (page === "settings") {
    return { page: "settings", ...emptyRoute };
  }
  if (page === "review") {
    const reviewFilter =
      rest === "blocking" || rest === "attention" ? rest : "";
    return {
      page: "review",
      reviewFilter,
      confirmation: "",
      drawerId: null,
      importId: null,
      accountId: null,
      recurringTab: "",
    };
  }
  if (page === "imports") {
    return {
      page: "imports",
      reviewFilter: "",
      confirmation: "",
      drawerId: null,
      importId: rest === "" ? null : rest,
      accountId,
      recurringTab: "",
    };
  }
  if (page === "recurrings") {
    const recurringTab = rest === "proposed" || rest === "active" ? rest : "";
    return {
      page: "recurrings",
      ...emptyRoute,
      recurringTab,
    };
  }
  if (page === "transactions") {
    if (rest.startsWith("open/")) {
      const drawerId = rest.slice("open/".length);
      return {
        page: "transactions",
        reviewFilter: "",
        confirmation: "",
        drawerId: drawerId === "" ? null : drawerId,
        importId: null,
        accountId: null,
        recurringTab: "",
      };
    }
    const confirmation =
      rest === "confirmed" || rest === "provisional" || rest === "review"
        ? rest
        : "";
    return {
      page: "transactions",
      reviewFilter: "",
      confirmation,
      drawerId: null,
      importId: null,
      accountId: null,
      recurringTab: "",
    };
  }
  if (page === "overview") {
    return { page: "overview", ...emptyRoute };
  }
  if (page === "spending" || page === "analytics") {
    return { page: "spending", ...emptyRoute };
  }
  return defaultRoute(onboarded);
}

export function hashFor(route: Route): string {
  if (route.page === "onboarding") {
    return "#/onboarding";
  }
  if (route.page === "settings") {
    return "#/settings";
  }
  if (route.page === "review") {
    return route.reviewFilter === ""
      ? "#/review"
      : `#/review/${route.reviewFilter}`;
  }
  if (route.page === "imports") {
    const path =
      route.importId === null ? "#/imports" : `#/imports/${route.importId}`;
    if (route.accountId === null) {
      return path;
    }
    return `${path}?account=${encodeURIComponent(route.accountId)}`;
  }
  if (route.page === "recurrings") {
    if (route.recurringTab === "proposed" || route.recurringTab === "active") {
      return `#/recurrings/${route.recurringTab}`;
    }
    return "#/recurrings";
  }
  if (route.page === "transactions") {
    if (route.drawerId !== null) {
      return `#/transactions/open/${route.drawerId}`;
    }
    if (route.confirmation !== "") {
      return `#/transactions/${route.confirmation}`;
    }
    return "#/transactions";
  }
  if (route.page === "spending") {
    return "#/spending";
  }
  return "#/overview";
}

export function titleFor(page: RoutePage): string {
  if (page === "review") {
    return "Pending Review";
  }
  if (page === "transactions") {
    return "Transactions";
  }
  if (page === "recurrings") {
    return "Recurrings";
  }
  if (page === "spending") {
    return "Spending";
  }
  if (page === "imports") {
    return "Imports";
  }
  if (page === "onboarding") {
    return "Onboarding";
  }
  if (page === "settings") {
    return "Settings";
  }
  return "Overview";
}
