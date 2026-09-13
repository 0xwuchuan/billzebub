import { useCallback, useEffect, useState } from "react";

import { defaultRoute, hashFor, parseHash, type Route } from "../lib/route";

function readRoute(onboarded: boolean): Route {
  if (window.location.hash === "") {
    const next = defaultRoute(onboarded);
    window.history.replaceState(null, "", hashFor(next));
    return next;
  }
  return parseHash(window.location.hash, onboarded);
}

export function useRoute(onboarded: boolean) {
  const [route, setRoute] = useState<Route>(() => readRoute(onboarded));

  useEffect(() => {
    function onHashChange() {
      setRoute(parseHash(window.location.hash, onboarded));
    }
    window.addEventListener("hashchange", onHashChange);
    return () => {
      window.removeEventListener("hashchange", onHashChange);
    };
  }, [onboarded]);

  const go = useCallback((next: Route) => {
    const hash = hashFor(next);
    if (window.location.hash !== hash) {
      window.location.hash = hash;
      return;
    }
    setRoute(next);
  }, []);

  return { route, go };
}
