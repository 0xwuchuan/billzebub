import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const tokens = readFileSync("src/styles/tokens.css", "utf8");
const shell = readFileSync("src/styles/shell.css", "utf8");
const base = readFileSync("src/styles/base.css", "utf8");

const light = tokens.slice(tokens.indexOf(':root[data-theme="light"]'));

describe("design tokens", () => {
  it("steps surfaces from bg to elevated to card in both themes", () => {
    for (const source of [tokens, light]) {
      expect(source).toMatch(/--bz-bg:/);
      expect(source).toMatch(/--bz-bg-elevated:/);
      expect(source).toMatch(/--bz-bg-card:/);
    }
    expect(tokens).toMatch(/--bz-surface:\s*var\(--bz-bg-card\)/);
    expect(tokens).toMatch(/--bz-rail-bg:\s*var\(--bz-bg\)/);
  });

  it("names the type, radius, and status roles", () => {
    expect(tokens).toMatch(/--bz-text-display:/);
    expect(tokens).toMatch(/--bz-text-title:/);
    expect(tokens).toMatch(/--bz-text-body:/);
    expect(tokens).toMatch(/--bz-text-meta:/);
    expect(tokens).toMatch(/--bz-nums:\s*tabular-nums/);
    expect(tokens).toMatch(/--bz-radius-card:\s*8px/);
    expect(tokens).toMatch(/--bz-radius-control:\s*6px/);
    expect(tokens).toMatch(/--bz-radius-pill:\s*999px/);
    expect(tokens).toMatch(/--bz-space-1:\s*4px/);
    expect(tokens).toMatch(/--bz-action:/);
    expect(tokens).toMatch(/--bz-confirmed:/);
    expect(tokens).toMatch(/--bz-provisional:/);
    expect(tokens).toMatch(
      /--bz-status-provisional:\s*var\(--bz-provisional\)/,
    );
    expect(tokens).toMatch(/--bz-status-confirmed:\s*var\(--bz-confirmed\)/);
    expect(tokens).toMatch(/--bz-attention:/);
    expect(tokens).toMatch(/--bz-blocking:/);
    expect(tokens).toMatch(/--bz-hue-pink:/);
  });

  it("keeps the light theme on the same token names", () => {
    expect(light).toMatch(/--bz-action:/);
    expect(light).toMatch(/--bz-confirmed:/);
    expect(light).toMatch(/--bz-attention:/);
    expect(light).toMatch(/--bz-blocking:/);
    expect(light).toMatch(/--bz-hue-lime:/);
    expect(light).not.toMatch(/--bz-hue-cyan:/);
    expect(light).not.toMatch(/--bz-accent:\s*#/);
  });

  it("splits status hexes off category hues and retires teal", () => {
    const dark = tokens.slice(0, tokens.indexOf(':root[data-theme="light"]'));
    expect(tokens).not.toMatch(/#3aa99f|#24837b/i);
    expect(tokens).not.toMatch(/--bz-hue-cyan:/);
    expect(dark).toMatch(/--bz-cat-groceries:\s*var\(--bz-hue-lime\)/);
    expect(dark).toMatch(
      /--bz-confirmed:\s*color-mix\(in srgb, var\(--bz-text\) 55%, transparent\)/,
    );
    expect(light).toMatch(
      /--bz-confirmed:\s*color-mix\(in srgb, var\(--bz-text\) 55%, transparent\)/,
    );

    for (const [block, expected] of [
      [
        dark,
        {
          action: "#cecdc3",
          provisional: "#c4a574",
          attention: "#6e8cae",
          blocking: "#b85c58",
          lime: "#7d9a56",
        },
      ],
      [
        light,
        {
          action: "#100f0f",
          provisional: "#8c6d3a",
          attention: "#3d5f86",
          blocking: "#8f3d3a",
          lime: "#5c7a32",
        },
      ],
    ] as const) {
      const hues = [
        ...block.matchAll(/--bz-hue-[\w-]+:\s*(#[0-9a-fA-F]{6})/g),
      ].flatMap((match) => {
        const hex = match[1];
        return hex === undefined ? [] : [hex.toLowerCase()];
      });
      for (const token of [
        "bz-action",
        "bz-provisional",
        "bz-attention",
        "bz-blocking",
      ]) {
        const hex = block.match(
          new RegExp(`--${token}:\\s*(#[0-9a-fA-F]{6})`),
        )?.[1];
        expect(hex?.toLowerCase()).toBe(
          expected[
            token.slice(3) as
              "action" | "provisional" | "attention" | "blocking"
          ],
        );
        expect(hues).not.toContain(hex?.toLowerCase());
      }
      expect(hues).toContain(expected.lime);
      expect(hues).not.toContain(expected.action);
    }
  });
});

describe("desktop shell tokens", () => {
  it("paints the rail active state as a quiet fill", () => {
    expect(shell).toMatch(/--bz-nav-active/);
    expect(shell).not.toMatch(/box-shadow:\s*inset/);
    expect(shell).toMatch(/background:\s*var\(--bz-bg-elevated\)/);
    expect(shell).toMatch(/background:\s*var\(--bz-bg-card\)/);
  });

  it("does not hardcode colors in the shell stylesheet", () => {
    expect(shell).not.toMatch(/#[0-9a-fA-F]{3,8}/);
  });

  it("paints account rail dots with muted ink", () => {
    expect(shell).toMatch(
      /\.rail-account-dot\s*\{[^}]*background:\s*var\(--bz-muted\)/,
    );
    const shellSource = readFileSync("src/components/AppShell.tsx", "utf8");
    expect(shellSource).not.toMatch(/accountKindColor/);
    expect(shellSource).not.toMatch(/rail-account-dot[\s\S]{0,80}style=/);
  });
});

describe("category chip tokens", () => {
  it("paints chips and the provisional badge from Phase 0 tokens", () => {
    const chip = base.slice(
      base.indexOf(".cat-chip {"),
      base.indexOf(".review-dot"),
    );
    expect(chip).toMatch(/--bz-bg-card/);
    expect(chip).toMatch(/--bz-text-meta/);
    expect(chip).toMatch(/--bz-provisional/);
    expect(chip).toMatch(/16%/);
    expect(chip).not.toMatch(/#[0-9a-fA-F]{3,8}/);
  });
});
