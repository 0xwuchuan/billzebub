import {
  SETUP_CATEGORIES,
  WATCH_ACCOUNTS,
  type WatchAccount,
} from "./accounts";

export const SETUP_STORAGE_KEY = "bz.quietRail.setup.v1";

export const SETUP_STEP_COUNT = 5;

export type ProbeStatus = "idle" | "running" | "ok";
export type ExtractStatus = "idle" | "running" | "done";

export type SetupState = {
  onboarded: boolean;
  step: number;
  selectedAccountIds: string[];
  shortcut: boolean;
  extraCategory: string;
  enabledCategories: string[];
  probe: ProbeStatus;
  extract: ExtractStatus;
};

export const defaultSetupState: SetupState = {
  onboarded: false,
  step: 0,
  selectedAccountIds: WATCH_ACCOUNTS.map((account) => account.id),
  shortcut: true,
  extraCategory: "",
  enabledCategories: [...SETUP_CATEGORIES],
  probe: "idle",
  extract: "idle",
};

export type SetupAction =
  | { type: "hydrate"; state: SetupState }
  | { type: "goStep"; step: number }
  | { type: "back" }
  | { type: "advance" }
  | { type: "finish" }
  | { type: "toggleAccount"; id: string }
  | { type: "toggleCategory"; name: string }
  | { type: "setExtraCategory"; name: string }
  | { type: "toggleShortcut" }
  | { type: "probeStart" }
  | { type: "probeOk" }
  | { type: "extractStart" }
  | { type: "extractDone" };

export function activeCategoryNames(state: SetupState): string[] {
  const extra = state.extraCategory.trim();
  const allowed = new Set<string>(SETUP_CATEGORIES);
  const base = state.enabledCategories.filter((name) => allowed.has(name));
  return extra !== "" && !base.includes(extra) ? [...base, extra] : base;
}

export function watchedAccounts(state: SetupState): WatchAccount[] {
  return WATCH_ACCOUNTS.filter((account) =>
    state.selectedAccountIds.includes(account.id),
  );
}

export function stepValid(state: SetupState, step: number): boolean {
  if (step === 0) {
    return true;
  }
  if (step === 1) {
    return state.selectedAccountIds.length >= 1;
  }
  if (step === 2) {
    return state.probe === "ok";
  }
  if (step === 3) {
    return activeCategoryNames(state).length >= 1;
  }
  if (step === 4) {
    return state.extract === "done";
  }
  return false;
}

export function firstBlockedStep(state: SetupState): number {
  for (let index = 0; index < SETUP_STEP_COUNT; index += 1) {
    if (!stepValid(state, index)) {
      return index;
    }
  }
  return SETUP_STEP_COUNT - 1;
}

export function reduceSetup(
  state: SetupState,
  action: SetupAction,
): SetupState {
  switch (action.type) {
    case "hydrate":
      return action.state;
    case "goStep":
      if (action.step < 0 || action.step > firstBlockedStep(state)) {
        return state;
      }
      return { ...state, step: action.step };
    case "back":
      return { ...state, step: Math.max(0, state.step - 1) };
    case "advance":
      if (!stepValid(state, state.step)) {
        return state;
      }
      if (state.step >= SETUP_STEP_COUNT - 1) {
        return { ...state, onboarded: true };
      }
      return { ...state, step: state.step + 1 };
    case "finish":
      return { ...state, onboarded: true };
    case "toggleAccount": {
      const selected = state.selectedAccountIds.includes(action.id)
        ? state.selectedAccountIds.filter((id) => id !== action.id)
        : [...state.selectedAccountIds, action.id];
      return {
        ...state,
        selectedAccountIds: selected,
        probe: "idle",
        extract: "idle",
      };
    }
    case "toggleCategory": {
      const enabled = state.enabledCategories.includes(action.name)
        ? state.enabledCategories.filter((name) => name !== action.name)
        : [...state.enabledCategories, action.name];
      return { ...state, enabledCategories: enabled };
    }
    case "setExtraCategory":
      return { ...state, extraCategory: action.name };
    case "toggleShortcut":
      return { ...state, shortcut: !state.shortcut };
    case "probeStart":
      return { ...state, probe: "running" };
    case "probeOk":
      return { ...state, probe: "ok" };
    case "extractStart":
      return { ...state, extract: "running" };
    case "extractDone":
      return { ...state, extract: "done" };
    default: {
      const _exhaustive: never = action;
      return _exhaustive;
    }
  }
}

export function persistableSetup(state: SetupState): SetupState {
  return {
    ...state,
    probe: state.probe === "ok" ? "ok" : "idle",
    extract: state.extract === "done" ? "done" : "idle",
  };
}

export function loadSetup(): SetupState {
  try {
    const raw = window.localStorage.getItem(SETUP_STORAGE_KEY);
    if (raw === null) {
      return defaultSetupState;
    }
    return parseSetup(JSON.parse(raw));
  } catch {
    return defaultSetupState;
  }
}

export function saveSetup(state: SetupState): void {
  window.localStorage.setItem(
    SETUP_STORAGE_KEY,
    JSON.stringify(persistableSetup(state)),
  );
}

function parseSetup(value: unknown): SetupState {
  if (typeof value !== "object" || value === null) {
    return defaultSetupState;
  }
  const record = value as Record<string, unknown>;
  const selected = Array.isArray(record.selectedAccountIds)
    ? record.selectedAccountIds.filter(
        (id): id is string =>
          typeof id === "string" &&
          WATCH_ACCOUNTS.some((account) => account.id === id),
      )
    : defaultSetupState.selectedAccountIds;
  const enabled = Array.isArray(record.enabledCategories)
    ? record.enabledCategories.filter(
        (name): name is string => typeof name === "string",
      )
    : defaultSetupState.enabledCategories;
  const step =
    typeof record.step === "number" && Number.isInteger(record.step)
      ? Math.min(Math.max(record.step, 0), SETUP_STEP_COUNT - 1)
      : 0;
  return {
    onboarded: record.onboarded === true,
    step,
    selectedAccountIds: selected,
    shortcut: record.shortcut !== false,
    extraCategory:
      typeof record.extraCategory === "string" ? record.extraCategory : "",
    enabledCategories: enabled,
    probe: record.probe === "ok" ? "ok" : "idle",
    extract: record.extract === "done" ? "done" : "idle",
  };
}

export const SETUP_STEPS = [
  {
    id: "workspace",
    title: "This machine keeps the history",
    lede: "Billzebub builds a local financial history from statements, PayLah mail, and Apple Pay. Reporting Currency is SGD. Nothing on this screen talks to a NAS wizard or a compose file.",
    hint: "",
  },
  {
    id: "accounts",
    title: "Watch these Financial Accounts",
    lede: "Each card is its own Financial Account. PayLah is a wallet. v1 reads DBS, Citi, and UOB statements plus PayLah mail.",
    hint: "Watch at least one Financial Account.",
  },
  {
    id: "sources",
    title: "Where Source Artifacts land",
    lede: "Drop statements into an inbox folder per Financial Account. A failed Extraction creates a Pending Review and no Claims.",
    hint: "Read the inbox folders once so Billzebub can see the Source Artifacts.",
  },
  {
    id: "categories",
    title: "Categories for Expenses",
    lede: "A Category is a reporting label. It is not Transaction Kind. Transfers stay out of spending totals on purpose.",
    hint: "Keep at least one Category for Expense reporting.",
  },
  {
    id: "ready",
    title: "September is already on disk",
    lede: "The next screen is Overview. Review stays one click away with a badge. Setup remains in the rail if you need to replay it.",
    hint: "Run the first Extraction so September has Claims and Transactions.",
  },
] as const;
