import { useEffect, useReducer } from "react";

import {
  loadSetup,
  reduceSetup,
  saveSetup,
  type SetupAction,
  type SetupGates,
  type SetupState,
} from "../lib/setup";

const emptyGates: SetupGates = { accountCount: 0, categoryCount: 0 };

export function useSetup(gates: SetupGates = emptyGates) {
  const [state, dispatchState] = useReducer(
    (current: SetupState, action: SetupAction) =>
      reduceSetup(current, action, gates),
    undefined,
    loadSetup,
  );

  useEffect(() => {
    saveSetup(state);
  }, [state]);

  useEffect(() => {
    if (gates.accountCount >= 1 && !state.onboarded) {
      dispatchState({ type: "finish" });
    }
  }, [gates.accountCount, state.onboarded]);

  return { state, dispatch: dispatchState };
}

export type { SetupState };
