import type { ReactNode } from "react";

import type { Route, RoutePage } from "../lib/route";
import { titleFor } from "../lib/route";
import { Badge } from "./ui/Badge";
import { OverviewIcon, ReviewIcon, SetupIcon, TransactionsIcon } from "./icons";

type NavId = "overview" | "review" | "transactions" | "setup";

type AppShellProps = {
  route: Route;
  periodLabel: string;
  accountCount: number;
  reviewCount: number;
  reviewBlocking: boolean;
  error: string | null;
  onNavigate: (page: RoutePage) => void;
  children: ReactNode;
};

export function AppShell({
  route,
  periodLabel,
  accountCount,
  reviewCount,
  reviewBlocking,
  error,
  onNavigate,
  children,
}: AppShellProps) {
  const items = [
    { id: "overview" as const, label: "Overview", icon: <OverviewIcon /> },
    {
      id: "review" as const,
      label: "Review",
      icon: <ReviewIcon />,
      count: reviewCount,
      blocking: reviewBlocking,
    },
    {
      id: "transactions" as const,
      label: "Transactions",
      icon: <TransactionsIcon />,
    },
  ];

  return (
    <div className="app">
      <a className="sr-only" href="#stage">
        Skip to content
      </a>
      <aside className="rail" aria-label="Daily navigation">
        <div className="brand">
          <span className="mark">B</span>
          <div>
            <strong>Billzebub</strong>
            <span>Quiet Rail · local</span>
          </div>
        </div>
        <div className="rail-group">
          <p className="rail-label">Daily</p>
          {items.map((item) => (
            <RailItem
              key={item.id}
              item={item}
              current={route.page}
              onNavigate={onNavigate}
            />
          ))}
        </div>
        <div className="rail-foot">
          <p className="rail-label">Workspace</p>
          <RailItem
            item={{ id: "setup", label: "Setup", icon: <SetupIcon /> }}
            current={route.page}
            onNavigate={onNavigate}
          />
        </div>
      </aside>
      <div className="main">
        <nav className="mobile-nav" aria-label="Daily navigation">
          {items.map((item) => (
            <RailItem
              key={`mobile-${item.id}`}
              item={item}
              current={route.page}
              onNavigate={onNavigate}
            />
          ))}
          <RailItem
            item={{ id: "setup", label: "Setup", icon: <SetupIcon /> }}
            current={route.page}
            onNavigate={onNavigate}
          />
        </nav>
        <header className="topbar">
          <div>
            <p className="eyebrow">{periodLabel}</p>
            <h1>{titleFor(route.page)}</h1>
          </div>
          <p className="top-meta">
            SGD · Asia/Singapore · {accountCount} Financial Accounts
          </p>
        </header>
        <main className="stage" id="stage">
          {error !== null ? (
            <p className="error-banner" role="alert">
              {error}
            </p>
          ) : null}
          {children}
        </main>
      </div>
    </div>
  );
}

function RailItem({
  item,
  current,
  onNavigate,
}: {
  item: {
    id: NavId;
    label: string;
    icon: ReactNode;
    count?: number;
    blocking?: boolean;
  };
  current: RoutePage;
  onNavigate: (page: RoutePage) => void;
}) {
  const count = item.count ?? 0;
  return (
    <button
      className="rail-item"
      type="button"
      aria-current={current === item.id ? "page" : undefined}
      onClick={() => {
        onNavigate(item.id);
      }}
    >
      {item.icon}
      <span>{item.label}</span>
      {count > 0 ? (
        <Badge tone={item.blocking === true ? "blocking" : "attention"}>
          {count}
        </Badge>
      ) : null}
    </button>
  );
}
