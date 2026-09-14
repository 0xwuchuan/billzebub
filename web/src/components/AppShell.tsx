import { useEffect, useId, useState, type ReactNode } from "react";

import type { Route, RoutePage } from "../lib/route";
import { titleFor } from "../lib/route";
import { Badge } from "./ui/Badge";
import {
  CloseIcon,
  MenuIcon,
  OverviewIcon,
  ReviewIcon,
  SetupIcon,
  TransactionsIcon,
} from "./icons";

type NavId = "overview" | "review" | "transactions" | "setup";

type NavItem = {
  id: NavId;
  label: string;
  icon: ReactNode;
  count?: number;
  blocking?: boolean;
};

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
  const [navOpen, setNavOpen] = useState(false);
  const titleId = useId();
  const dailyItems: NavItem[] = [
    { id: "overview", label: "Overview", icon: <OverviewIcon /> },
    {
      id: "review",
      label: "Review",
      icon: <ReviewIcon />,
      count: reviewCount,
      blocking: reviewBlocking,
    },
    {
      id: "transactions",
      label: "Transactions",
      icon: <TransactionsIcon />,
    },
  ];
  const setupItem: NavItem = {
    id: "setup",
    label: "Setup",
    icon: <SetupIcon />,
  };

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setNavOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  function go(page: RoutePage) {
    setNavOpen(false);
    onNavigate(page);
  }

  return (
    <div className="app">
      <a className="sr-only" href="#stage">
        Skip to content
      </a>
      <aside className="rail" aria-label="Daily navigation">
        <RailContent
          dailyItems={dailyItems}
          setupItem={setupItem}
          current={route.page}
          onNavigate={go}
        />
      </aside>
      <div className="main">
        <header className="topbar">
          <button
            className="icon-btn menu-btn"
            type="button"
            aria-expanded={navOpen}
            aria-controls="mobile-nav"
            onClick={() => {
              setNavOpen(true);
            }}
          >
            <MenuIcon />
            <span className="sr-only">Open navigation</span>
          </button>
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
      {navOpen ? (
        <>
          <button
            className="nav-backdrop open"
            type="button"
            aria-label="Close navigation"
            onClick={() => {
              setNavOpen(false);
            }}
          />
          <nav
            className="nav-drawer open"
            id="mobile-nav"
            aria-labelledby={titleId}
          >
            <div className="nav-drawer-head">
              <p id={titleId} className="eyebrow">
                Navigation
              </p>
              <button
                className="icon-btn"
                type="button"
                onClick={() => {
                  setNavOpen(false);
                }}
              >
                <CloseIcon />
                <span className="sr-only">Close navigation</span>
              </button>
            </div>
            <RailContent
              dailyItems={dailyItems}
              setupItem={setupItem}
              current={route.page}
              onNavigate={go}
            />
          </nav>
        </>
      ) : null}
    </div>
  );
}

function RailContent({
  dailyItems,
  setupItem,
  current,
  onNavigate,
}: {
  dailyItems: NavItem[];
  setupItem: NavItem;
  current: RoutePage;
  onNavigate: (page: RoutePage) => void;
}) {
  return (
    <>
      <div className="brand">
        <span className="mark">B</span>
        <div>
          <strong>Billzebub</strong>
          <span>Quiet Rail · local</span>
        </div>
      </div>
      <div className="rail-group">
        <p className="rail-label">Daily</p>
        {dailyItems.map((item) => (
          <RailItem
            key={item.id}
            item={item}
            current={current}
            onNavigate={onNavigate}
          />
        ))}
      </div>
      <div className="rail-foot">
        <p className="rail-label">Workspace</p>
        <RailItem item={setupItem} current={current} onNavigate={onNavigate} />
      </div>
    </>
  );
}

function RailItem({
  item,
  current,
  onNavigate,
}: {
  item: NavItem;
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
