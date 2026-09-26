import { useEffect, useMemo, useRef, useState } from "react";

// Adapted from Dither Kit's MIT-licensed ordered-dither canvas painter:
// https://github.com/Boring-Software-Inc/dither-kit
const BAYER = [
  [0, 8, 2, 10],
  [12, 4, 14, 6],
  [3, 11, 1, 9],
  [15, 7, 13, 5],
].map((row) => row.map((value) => (value + 0.5) / 16));

const CELL_SIZE = 2;

type Variant = "gradient" | "dotted" | "hatched" | "solid" | "soft";

type BarDatum = {
  label: string;
  [key: string]: string | number;
};

export type DitherSeries = {
  key: string;
  label: string;
  color: string;
  variant?: Variant;
};

export function DitherBarChart({
  data,
  series,
  height = 132,
  ariaLabel,
  valueFormatter = (value) => value.toLocaleString(),
  stacked = false,
}: {
  data: BarDatum[];
  series: DitherSeries[];
  height?: number;
  ariaLabel: string;
  valueFormatter?: (value: number) => string;
  stacked?: boolean;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const themeEpoch = useThemeEpoch();
  const [width, setWidth] = useState(0);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const max = useMemo(
    () =>
      Math.max(
        1,
        ...data.map((row) =>
          stacked
            ? series.reduce((sum, item) => sum + numericValue(row[item.key]), 0)
            : Math.max(...series.map((item) => numericValue(row[item.key])), 0),
        ),
      ),
    [data, series, stacked],
  );

  useEffect(() => {
    const element = wrapRef.current;
    if (element === null) {
      return;
    }
    const measure = () => {
      setWidth(element.clientWidth);
    };
    if (typeof ResizeObserver === "undefined") {
      measure();
      return;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    measure();
    return () => {
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (
      canvas === null ||
      width === 0 ||
      data.length === 0 ||
      typeof CanvasRenderingContext2D === "undefined"
    ) {
      return;
    }
    const columns = Math.max(24, Math.round(width / CELL_SIZE));
    const rows = Math.max(24, Math.round(height / CELL_SIZE));
    canvas.width = columns;
    canvas.height = rows;
    const context = canvas.getContext("2d");
    if (context === null) {
      return;
    }
    context.clearRect(0, 0, columns, rows);
    const paints = series.map((item) => ({
      ...item,
      color: resolveCssColor(item.color),
    }));
    const groupWidth = columns / data.length;
    const seriesWidth = Math.max(
      2,
      (groupWidth * 0.76) / Math.max(series.length, 1),
    );
    const floor = rows - 2;

    data.forEach((datum, datumIndex) => {
      const groupDim =
        hoverIndex !== null && hoverIndex !== datumIndex ? 0.35 : 1;
      let cumulative = 0;
      paints.forEach((item, seriesIndex) => {
        const value = numericValue(datum[item.key]);
        const baseValue = stacked ? cumulative : 0;
        cumulative += value;
        const topValue = stacked ? cumulative : value;
        const top = floor - (topValue / max) * (rows - 6);
        const base = floor - (baseValue / max) * (rows - 6);
        const left = stacked
          ? datumIndex * groupWidth + groupWidth * 0.18
          : datumIndex * groupWidth +
            groupWidth * 0.12 +
            seriesIndex * seriesWidth;
        const right = stacked
          ? datumIndex * groupWidth + groupWidth * 0.82
          : Math.min(columns, left + Math.max(1, seriesWidth - 1));
        for (let x = Math.round(left); x < Math.round(right); x += 1) {
          paintColumn(
            context,
            x,
            top,
            Math.max(top + (value > 0 ? 1 : 0), base),
            item.color,
            item.variant ?? "gradient",
            groupDim,
          );
        }
      });
    });
  }, [data, height, hoverIndex, max, series, stacked, themeEpoch, width]);

  const hovered = hoverIndex === null ? null : (data[hoverIndex] ?? null);
  const accessibleSummary = data
    .map(
      (row) =>
        `${row.label}: ${series
          .map(
            (item) =>
              `${item.label} ${valueFormatter(numericValue(row[item.key]))}`,
          )
          .join(", ")}`,
    )
    .join(". ");

  return (
    <div className="dither-chart" role="img" aria-label={ariaLabel}>
      <div className="dither-legend" aria-hidden="true">
        {series.map((item) => (
          <span key={item.key}>
            <i style={{ backgroundColor: item.color }} />
            {item.label}
          </span>
        ))}
      </div>
      <div
        ref={wrapRef}
        className="dither-plot"
        style={{ height }}
        onPointerMove={(event) => {
          if (data.length === 0) {
            return;
          }
          const rect = event.currentTarget.getBoundingClientRect();
          const next = Math.min(
            data.length - 1,
            Math.max(
              0,
              Math.floor(
                ((event.clientX - rect.left) / rect.width) * data.length,
              ),
            ),
          );
          setHoverIndex(next);
        }}
        onPointerLeave={() => {
          setHoverIndex(null);
        }}
      >
        <canvas ref={canvasRef} aria-hidden="true" />
        {hovered !== null ? (
          <div
            className="dither-tooltip"
            style={{
              left: `${((hoverIndex ?? 0) + 0.5) * (100 / data.length)}%`,
            }}
          >
            <strong>{hovered.label}</strong>
            {series.map((item) => (
              <span key={item.key}>
                {item.label} {valueFormatter(numericValue(hovered[item.key]))}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <div
        className="dither-axis"
        style={{
          gridTemplateColumns: `repeat(${Math.max(data.length, 1)}, 1fr)`,
        }}
        aria-hidden="true"
      >
        {data.map((row) => (
          <span key={row.label}>{row.label}</span>
        ))}
      </div>
      <span className="sr-only">{accessibleSummary}</span>
    </div>
  );
}

export function DitherDonutChart({
  data,
  size = 152,
  ariaLabel,
}: {
  data: Array<{ label: string; value: number; color: string }>;
  size?: number;
  ariaLabel: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const themeEpoch = useThemeEpoch();
  const total = data.reduce((sum, item) => sum + item.value, 0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null || typeof CanvasRenderingContext2D === "undefined") {
      return;
    }
    const pixels = Math.max(32, Math.round(size / CELL_SIZE));
    canvas.width = pixels;
    canvas.height = pixels;
    const context = canvas.getContext("2d");
    if (context === null) {
      return;
    }
    context.clearRect(0, 0, pixels, pixels);
    if (total <= 0) {
      return;
    }
    const center = pixels / 2;
    const outerRadius = pixels * 0.46;
    const innerRadius = pixels * 0.28;
    const slices = data.map((item) => ({
      ...item,
      color: resolveCssColor(item.color),
    }));
    const boundaries: number[] = [];
    let cursor = 0;
    for (const item of slices) {
      cursor += item.value / total;
      boundaries.push(cursor);
    }

    for (let y = 0; y < pixels; y += 1) {
      for (let x = 0; x < pixels; x += 1) {
        const dx = x + 0.5 - center;
        const dy = y + 0.5 - center;
        const radius = Math.hypot(dx, dy);
        if (radius < innerRadius || radius > outerRadius) {
          continue;
        }
        const angle = (Math.atan2(dy, dx) + Math.PI * 2.5) % (Math.PI * 2);
        const position = angle / (Math.PI * 2);
        const index = boundaries.findIndex((boundary) => position <= boundary);
        const item = slices[index === -1 ? slices.length - 1 : index];
        if (item === undefined) {
          continue;
        }
        context.fillStyle = withAlpha(item.color, 0.9);
        context.fillRect(x, y, 1, 1);
      }
    }
  }, [data, size, themeEpoch, total]);

  return (
    <div className="dither-donut" role="img" aria-label={ariaLabel}>
      <canvas
        ref={canvasRef}
        style={{ width: size, height: size }}
        aria-hidden="true"
      />
      <span className="sr-only">
        {data.map((item) => `${item.label}: ${item.value}`).join(". ")}
      </span>
    </div>
  );
}

function paintColumn(
  context: CanvasRenderingContext2D,
  x: number,
  top: number,
  floor: number,
  color: string,
  variant: Variant,
  dim: number,
) {
  const start = Math.max(0, Math.round(top));
  const end = Math.max(start + 1, Math.round(floor));
  if (variant === "soft") {
    context.fillStyle = withAlpha(color, 0.78 * dim);
    for (let y = start; y < end; y += 1) {
      context.fillRect(x, y, 1, 1);
    }
    context.fillStyle = withAlpha(color, Math.min(1, 0.95 * dim));
    context.fillRect(x, start, 1, 1);
    return;
  }
  const depth = end - start;
  for (let y = start; y < end; y += 1) {
    const density = (y - start) / Math.max(depth, 1);
    const threshold = BAYER[y & 3]?.[x & 3] ?? 0;
    if (variant === "hatched" && ((x + y) & 3) >= 2) {
      continue;
    }
    const lit =
      variant === "solid" ||
      density > threshold - (variant === "dotted" ? -0.12 : 0);
    if (variant === "dotted" && !lit) {
      continue;
    }
    const alpha = (lit ? 0.35 + density * 0.65 : 0.16 + density * 0.24) * dim;
    context.fillStyle = withAlpha(color, alpha);
    context.fillRect(x, y, 1, 1);
  }
  context.fillStyle = withAlpha(color, 0.82 * dim);
  context.fillRect(x, start, 1, 1);
}

function numericValue(value: string | number | undefined): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, value)
    : 0;
}

function useThemeEpoch(): number {
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    if (typeof MutationObserver === "undefined") {
      return;
    }
    const root = document.documentElement;
    const observer = new MutationObserver(() => {
      setEpoch((value) => value + 1);
    });
    observer.observe(root, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => {
      observer.disconnect();
    };
  }, []);
  return epoch;
}

function resolveCssColor(color: string): string {
  if (typeof document === "undefined" || !color.startsWith("var(")) {
    return color;
  }
  const probe = document.createElement("span");
  probe.style.color = color;
  document.documentElement.append(probe);
  const resolved = getComputedStyle(probe).color;
  probe.remove();
  return resolved === "" ? color : resolved;
}

function channelsOf(color: string): [number, number, number] | null {
  const match = /^rgba?\(\s*([0-9.]+)[,\s]+([0-9.]+)[,\s]+([0-9.]+)/.exec(
    color.trim(),
  );
  if (
    match?.[1] !== undefined &&
    match[2] !== undefined &&
    match[3] !== undefined
  ) {
    return [Number(match[1]), Number(match[2]), Number(match[3])];
  }
  if (color.startsWith("#")) {
    const hex = color.slice(1);
    if (hex.length === 6 && /^[0-9a-f]+$/i.test(hex)) {
      return [
        Number.parseInt(hex.slice(0, 2), 16),
        Number.parseInt(hex.slice(2, 4), 16),
        Number.parseInt(hex.slice(4, 6), 16),
      ];
    }
  }
  return null;
}

function withAlpha(color: string, alpha: number): string {
  const channels = channelsOf(color);
  if (channels === null) {
    return color;
  }
  return `rgba(${channels[0]}, ${channels[1]}, ${channels[2]}, ${alpha})`;
}
