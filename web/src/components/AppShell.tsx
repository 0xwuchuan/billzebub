import { useEffect, useId, useState, type ReactNode } from "react";

import type { FinancialAccount } from "../api";
import { accountKindColor, groupedAccounts } from "../lib/accounts";
import type { Theme } from "../lib/theme";
import type { Route, RoutePage } from "../lib/route";
import { titleFor } from "../lib/route";
import { ThemeToggle } from "./ThemeToggle";
import { Badge } from "./ui/Badge";
import {
  CloseIcon,
  ImportsIcon,
  MenuIcon,
  OverviewIcon,
  ReviewIcon,
  SettingsIcon,
  SpendingIcon,
  TransactionsIcon,
} from "./icons";

type NavId =
  "overview" | "spending" | "review" | "transactions" | "imports" | "settings";

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
  reviewCount: number;
  reviewBlocking: boolean;
  accounts: FinancialAccount[];
  selectedAccountId: string;
  theme: Theme;
  error: string | null;
  detailOpen?: boolean;
  onNavigate: (page: RoutePage) => void;
  onSelectAccount: (accountId: string) => void;
  onToggleTheme: () => void;
  children: ReactNode;
  detail?: ReactNode;
};

export function AppShell({
  route,
  periodLabel,
  reviewCount,
  reviewBlocking,
  accounts,
  selectedAccountId,
  theme,
  error,
  detailOpen = false,
  onNavigate,
  onSelectAccount,
  onToggleTheme,
  children,
  detail,
}: AppShellProps) {
  const [navOpen, setNavOpen] = useState(false);
  const titleId = useId();
  const dailyItems: NavItem[] = [
    { id: "overview", label: "Overview", icon: <OverviewIcon /> },
    { id: "spending", label: "Spending", icon: <SpendingIcon /> },
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
    {
      id: "imports",
      label: "Imports",
      icon: <ImportsIcon />,
    },
  ];
  const settingsItem: NavItem = {
    id: "settings",
    label: "Settings",
    icon: <SettingsIcon />,
  };

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setNavOpen(false);
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key === ",") {
        event.preventDefault();
        setNavOpen(false);
        onNavigate("settings");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onNavigate]);

  function go(page: RoutePage) {
    setNavOpen(false);
    onNavigate(page);
  }

  return (
    <div className={`app${detailOpen ? " has-detail" : ""}`}>
      <a className="sr-only" href="#stage">
        Skip to content
      </a>
      <aside className="rail" aria-label="Daily navigation">
        <RailContent
          dailyItems={dailyItems}
          settingsItem={settingsItem}
          accounts={accounts}
          current={route.page}
          selectedAccountId={selectedAccountId}
          onNavigate={go}
          onSelectAccount={(accountId) => {
            setNavOpen(false);
            onSelectAccount(accountId);
          }}
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
          <div className="topbar-actions">
            <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          </div>
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
      {detail}
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
              settingsItem={settingsItem}
              accounts={accounts}
              current={route.page}
              selectedAccountId={selectedAccountId}
              onNavigate={go}
              onSelectAccount={(accountId) => {
                setNavOpen(false);
                onSelectAccount(accountId);
              }}
            />
          </nav>
        </>
      ) : null}
    </div>
  );
}

function RailContent({
  dailyItems,
  settingsItem,
  accounts,
  current,
  selectedAccountId,
  onNavigate,
  onSelectAccount,
}: {
  dailyItems: NavItem[];
  settingsItem: NavItem;
  accounts: FinancialAccount[];
  current: RoutePage;
  selectedAccountId: string;
  onNavigate: (page: RoutePage) => void;
  onSelectAccount: (accountId: string) => void;
}) {
  const groups = groupedAccounts(accounts);
  return (
    <>
      <div className="rail-body">
        <div className="brand">
          <span className="mark">
            <img src="/baby-beel.svg" alt="" />
          </span>
          <strong>Billzebub</strong>
        </div>
        <div className="rail-group">
          {dailyItems.map((item) => (
            <RailItem
              key={item.id}
              item={item}
              current={current}
              onNavigate={onNavigate}
            />
          ))}
        </div>
        {groups.map((group) => (
          <div className="rail-accounts" key={group.kind}>
            <p className="rail-label">{group.label}</p>
            {group.accounts.map((account) => (
              <button
                className="rail-account"
                type="button"
                key={account.id}
                aria-current={
                  current === "transactions" && selectedAccountId === account.id
                    ? "true"
                    : undefined
                }
                onClick={() => {
                  onSelectAccount(account.id);
                }}
              >
                <i
                  className="rail-account-dot"
                  style={{ background: accountKindColor(account.kind) }}
                />
                <span className="rail-account-name">
                  {account.display_name}
                </span>
              </button>
            ))}
          </div>
        ))}
      </div>
      <div className="rail-foot">
        <RailItem
          item={settingsItem}
          current={current}
          onNavigate={onNavigate}
        />
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
      aria-label={item.label}
      aria-current={current === item.id ? "page" : undefined}
      onClick={() => {
        onNavigate(item.id);
      }}
    >
      {item.icon}
      <span>{item.label}</span>
      {item.id === "settings" ? <kbd className="rail-shortcut">⌘,</kbd> : null}
      {count > 0 ? (
        <Badge tone={item.blocking === true ? "blocking" : "attention"}>
          {count}
        </Badge>
      ) : null}
    </button>
  );
}
