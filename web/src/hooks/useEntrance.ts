import { useState } from "react";

import { takeEntrance } from "../lib/motion";

export function useEntrance(key: string): boolean {
  const [fresh] = useState(() => takeEntrance(key));
  return fresh;
}
