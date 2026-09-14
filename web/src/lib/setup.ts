export const SETUP_STORAGE_KEY = "bz.quietRail.setup.v2";

export const SETUP_STEP_COUNT = 5;

export type SetupState = {
  onboarded: boolean;
  step: number;
};

export const defaultSetupState: SetupState = {
  onboarded: false,
  step: 0,
};

export type SetupAction =
  | { type: "hydrate"; state: SetupState }
  | { type: "goStep"; step: number }
  | { type: "back" }
  | { type: "advance" }
  | { type: "finish" };

export type SetupGates = {
  accountCount: number;
  categoryCount: number;
};

export function stepValid(state: SetupState, gates: SetupGates): boolean {
  return stepIndexValid(state.step, gates);
}

export function stepIndexValid(step: number, gates: SetupGates): boolean {
  if (step === 0) {
    return true;
  }
  if (step === 1 || step === 2) {
    return gates.accountCount >= 1;
  }
  if (step === 3) {
    return gates.categoryCount >= 1;
  }
  if (step === 4) {
    return gates.accountCount >= 1 && gates.categoryCount >= 1;
  }
  return false;
}

export function firstBlockedStep(state: SetupState, gates: SetupGates): number {
  for (let index = 0; index < SETUP_STEP_COUNT; index += 1) {
    if (!stepIndexValid(index, gates)) {
      return index;
    }
  }
  return SETUP_STEP_COUNT - 1;
}

export function reduceSetup(
  state: SetupState,
  action: SetupAction,
  gates: SetupGates,
): SetupState {
  switch (action.type) {
    case "hydrate":
      return action.state;
    case "goStep":
      if (action.step < 0 || action.step > firstBlockedStep(state, gates)) {
        return state;
      }
      return { ...state, step: action.step };
    case "back":
      return { ...state, step: Math.max(0, state.step - 1) };
    case "advance":
      if (!stepIndexValid(state.step, gates)) {
        return state;
      }
      if (state.step >= SETUP_STEP_COUNT - 1) {
        return { ...state, onboarded: true };
      }
      return { ...state, step: state.step + 1 };
    case "finish":
      return { ...state, onboarded: true };
    default: {
      const _exhaustive: never = action;
      return _exhaustive;
    }
  }
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
    JSON.stringify({ onboarded: state.onboarded, step: state.step }),
  );
}

function parseSetup(value: unknown): SetupState {
  if (typeof value !== "object" || value === null) {
    return defaultSetupState;
  }
  const record = value as Record<string, unknown>;
  const step =
    typeof record.step === "number" && Number.isInteger(record.step)
      ? Math.min(Math.max(record.step, 0), SETUP_STEP_COUNT - 1)
      : 0;
  return {
    onboarded: record.onboarded === true,
    step,
  };
}

export const SETUP_STEPS = [
  {
    id: "workspace",
    title: "This machine keeps the history",
    lede: "Billzebub builds a local financial history from statements and Shortcut Real-time Claims. Reporting Currency is SGD. Owner identity comes from Tailscale.",
    hint: "",
  },
  {
    id: "accounts",
    title: "Watch these Financial Accounts",
    lede: "Each card is its own Financial Account. PayLah is a wallet, kind paylah — not a deposit account.",
    hint: "Create at least one Financial Account.",
  },
  {
    id: "sources",
    title: "Where Source Artifacts land",
    lede: "Credit-card statements drop into an inbox folder per Financial Account. Wallet card labels map privately. Shortcut tokens are revealed once.",
    hint: "Create at least one Financial Account before mapping sources.",
  },
  {
    id: "categories",
    title: "Categories for Expenses",
    lede: "A Category is a reporting label. It is not Transaction Kind. Transfers stay out of spending totals on purpose.",
    hint: "Keep at least one Category for Expense reporting.",
  },
  {
    id: "ready",
    title: "Setup is the owner workspace",
    lede: "Overview is home. Review stays one click away. Setup remains in the rail when you need to add an account, alias, Category, or token.",
    hint: "Create at least one Financial Account and one Category.",
  },
] as const;
