export type RoutePage =
  "overview" | "review" | "transactions" | "imports" | "setup";

export type ReviewFilter = "" | "blocking" | "attention";

export type ConfirmationFilter = "" | "confirmed" | "provisional" | "review";

export type Route = {
  page: RoutePage;
  reviewFilter: ReviewFilter;
  confirmation: ConfirmationFilter;
  drawerId: string | null;
  importId: string | null;
};

const emptyRoute = {
  reviewFilter: "" as const,
  confirmation: "" as const,
  drawerId: null,
  importId: null,
};

export function defaultRoute(onboarded: boolean): Route {
  return {
    page: onboarded ? "overview" : "setup",
    ...emptyRoute,
  };
}

export function parseHash(hash: string, onboarded: boolean): Route {
  const raw = hash.replace(/^#\/?/, "");
  const [page, ...restParts] = raw.split("/");
  const rest = restParts.join("/");
  if (page === "onboarding" || page === "setup") {
    return { page: "setup", ...emptyRoute };
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
    };
  }
  if (page === "imports") {
    return {
      page: "imports",
      reviewFilter: "",
      confirmation: "",
      drawerId: null,
      importId: rest === "" ? null : rest,
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
    };
  }
  if (page === "overview") {
    return { page: "overview", ...emptyRoute };
  }
  return defaultRoute(onboarded);
}

export function hashFor(route: Route): string {
  if (route.page === "setup") {
    return "#/setup";
  }
  if (route.page === "review") {
    return route.reviewFilter === ""
      ? "#/review"
      : `#/review/${route.reviewFilter}`;
  }
  if (route.page === "imports") {
    return route.importId === null
      ? "#/imports"
      : `#/imports/${route.importId}`;
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
  return "#/overview";
}

export function titleFor(page: RoutePage): string {
  if (page === "review") {
    return "Pending Review";
  }
  if (page === "transactions") {
    return "Transactions";
  }
  if (page === "imports") {
    return "Imports";
  }
  if (page === "setup") {
    return "Setup";
  }
  return "Overview";
}
