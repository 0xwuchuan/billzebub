import type { DitherSeries } from "../components/dither-kit/DitherCharts";

export const CONFIRMATION_SERIES: DitherSeries[] = [
  {
    key: "confirmed",
    label: "Confirmed",
    color: "var(--bz-status-confirmed)",
    variant: "soft",
  },
  {
    key: "provisional",
    label: "Provisional",
    color: "var(--bz-status-provisional)",
    variant: "soft",
  },
];
