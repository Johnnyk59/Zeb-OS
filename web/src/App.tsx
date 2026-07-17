import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type FocusEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import {
  Routes,
  Route,
  NavLink,
  Navigate,
  useLocation,
} from "react-router-dom";
import {
  Activity,
  BarChart3,
  ChevronDown,
  Clock,
  Code,
  Cpu,
  Database,
  Eye,
  FolderOpen,
  FileText,
  Globe,
  Heart,
  KeyRound,
  Menu,
  MessageSquare,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  Puzzle,
  Radio,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
  Star,
  Terminal,
  Users,
  Webhook,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { SelectionSwitcher } from "@nous-research/ui/ui/components/selection-switcher";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Typography } from "@nous-research/ui/ui/components/typography/index";
import { cn } from "@/lib/utils";
import { SidebarFooter } from "@/components/SidebarFooter";
import { useBelowBreakpoint } from "@nous-research/ui/hooks/use-below-breakpoint";
import { useSidebarStatus } from "@/hooks/useSidebarStatus";
import { PageHeaderProvider } from "@/contexts/PageHeaderProvider";
import { ProfileProvider } from "@/contexts/ProfileProvider";
import { useProfileScope } from "@/contexts/useProfileScope";
import { ProfileSwitcher } from "@/components/ProfileSwitcher";
import { ProfileScopeBanner } from "@/components/ProfileScopeBanner";
import { ZebRoommate } from "@/components/ZebRoommate";
import ConfigPage from "@/pages/ConfigPage";
import DiagnosePage from "@/pages/DiagnosePage";
import DocsPage from "@/pages/DocsPage";
import EnvPage from "@/pages/EnvPage";
import LocalModelPage from "@/pages/LocalModelPage";
import ReposPage from "@/pages/ReposPage";
import FilesPage from "@/pages/FilesPage";
import SessionsPage from "@/pages/SessionsPage";
import LogsPage from "@/pages/LogsPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import ModelsPage from "@/pages/ModelsPage";
import CronPage from "@/pages/CronPage";
import ProfilesPage from "@/pages/ProfilesPage";
import ProfileBuilderPage from "@/pages/ProfileBuilderPage";
import SkillsPage from "@/pages/SkillsPage";
import PluginsPage from "@/pages/PluginsPage";
import McpPage from "@/pages/McpPage";
import PairingPage from "@/pages/PairingPage";
import ChannelsPage from "@/pages/ChannelsPage";
import WebhooksPage from "@/pages/WebhooksPage";
import SystemPage from "@/pages/SystemPage";
import ChatPage from "@/pages/ChatPage";
import ZebChatPage from "@/pages/ZebChatPage";
import { useI18n } from "@/i18n";
import type { Translations } from "@/i18n/types";
import { PluginPage, PluginSlot, usePlugins } from "@/plugins";
import type { PluginManifest } from "@/plugins";
import { useTheme } from "@/themes";
import { isDashboardEmbeddedChatEnabled } from "@/lib/dashboard-flags";
import { api } from "@/lib/api";
import type { DashboardSelfState } from "@/lib/api";

function RootRedirect() {
  return <Navigate to="/sessions" replace />;
}

function UnknownRouteFallback({ pluginsLoading }: { pluginsLoading: boolean }) {
  if (pluginsLoading) {
    // Render nothing during the plugin-load window — a spinner here would just flash.
    return null;
  }
  return <Navigate to="/sessions" replace />;
}

const CHAT_NAV_ITEM: NavItem = {
  path: "/chat",
  labelKey: "chat",
  label: "Chat",
  icon: Terminal,
};

/**
 * Built-in routes except /chat.  Chat is rendered persistently (outside
 * <Routes>) when embedded — see the persistent chat host block rendered
 * inline near the bottom of this file — so the PTY child, WebSocket,
 * and xterm instance survive when the user visits another tab and comes
 * back.  A `display:none` toggle hides the terminal without unmounting.
 * Routing still owns the URL so /chat deep-links, browser back/forward,
 * and nav highlight keep working.
 */
const BUILTIN_ROUTES_CORE: Record<string, ComponentType> = {
  "/": RootRedirect,
  "/sessions": SessionsPage,
  "/files": FilesPage,
  "/analytics": AnalyticsPage,
  "/models": ModelsPage,
  "/localmodel": LocalModelPage,
  "/repos": ReposPage,
  "/diagnose": DiagnosePage,
  "/logs": LogsPage,
  "/cron": CronPage,
  "/skills": SkillsPage,
  "/plugins": PluginsPage,
  "/mcp": McpPage,
  "/pairing": PairingPage,
  "/channels": ChannelsPage,
  "/webhooks": WebhooksPage,
  "/system": SystemPage,
  "/profiles": ProfilesPage,
  "/profiles/new": ProfileBuilderPage,
  "/config": ConfigPage,
  "/env": EnvPage,
  // Reachable by URL for old bookmarks, but no longer in the sidebar.
  "/docs": DocsPage,
  // The classic embedded TUI terminal — kept reachable by URL as a
  // fallback while the bubble chat (ZebChatPage, mounted persistently
  // at /chat) is the primary surface.
  "/terminal": ChatPage,
};

// Route placeholder for /chat.  The persistent ChatPage host (rendered
// outside <Routes> when embedded chat is on) paints on top; this empty
// element just claims the path so the `*` catch-all redirect doesn't
// fire when the user navigates to /chat.
function ChatRouteSink() {
  return null;
}

/**
 * Functional tabs — the things you *use* day to day. Rendered at the top
 * of the sidebar. Configuration/admin surfaces live in the collapsible
 * group below (BUILTIN_NAV_CONFIG). Documentation was removed from the
 * nav entirely (its route still resolves for old bookmarks).
 */
const BUILTIN_NAV_MAIN: NavItem[] = [
  {
    path: "/sessions",
    labelKey: "sessions",
    label: "Sessions",
    icon: MessageSquare,
  },
  { path: "/files", label: "Files", icon: FolderOpen },
  {
    path: "/analytics",
    labelKey: "analytics",
    label: "Analytics",
    icon: BarChart3,
  },
  {
    path: "/models",
    labelKey: "models",
    label: "Models",
    icon: Cpu,
  },
  { path: "/localmodel", label: "Local Model", icon: Activity },
  { path: "/repos", label: "GitHub Repos", icon: Code },
  { path: "/skills", labelKey: "skills", label: "Skills", icon: Package },
  { path: "/cron", labelKey: "cron", label: "Cron", icon: Clock },
  { path: "/env", labelKey: "keys", label: "API Keys", icon: KeyRound },
  { path: "/diagnose", label: "Diagnose", icon: Heart },
];

/** Admin/configuration surfaces, consolidated under one collapsible
 *  "Configuration" section in the sidebar. */
const BUILTIN_NAV_CONFIG: NavItem[] = [
  { path: "/system", label: "System", icon: Wrench },
  { path: "/profiles", labelKey: "profiles", label: "Profiles", icon: Users },
  { path: "/pairing", label: "Pairing", icon: ShieldCheck },
  { path: "/webhooks", label: "Webhooks", icon: Webhook },
  { path: "/channels", label: "Channels", icon: Radio },
  { path: "/mcp", label: "MCP", icon: Plug },
  { path: "/logs", labelKey: "logs", label: "Logs", icon: FileText },
  { path: "/config", labelKey: "config", label: "Config", icon: Settings },
];

const CONFIG_NAV_PATHS = new Set(BUILTIN_NAV_CONFIG.map((i) => i.path));

const BUILTIN_NAV_REST: NavItem[] = [
  ...BUILTIN_NAV_MAIN,
  ...BUILTIN_NAV_CONFIG,
];

const ICON_MAP: Record<string, ComponentType<{ className?: string }>> = {
  Activity,
  BarChart3,
  Clock,
  Cpu,
  FileText,
  FolderOpen,
  KeyRound,
  MessageSquare,
  Package,
  Settings,
  Puzzle,
  Sparkles,
  Terminal,
  Globe,
  Database,
  Shield,
  Users,
  Wrench,
  Zap,
  Heart,
  Star,
  Code,
  Eye,
};

function resolveIcon(name: string): ComponentType<{ className?: string }> {
  return ICON_MAP[name] ?? Puzzle;
}

function buildNavItems(
  builtIn: NavItem[],
  manifests: PluginManifest[],
): NavItem[] {
  const items = [...builtIn];

  for (const manifest of manifests) {
    if (manifest.tab.override) continue;
    if (manifest.tab.hidden) continue;

    const pluginItem: NavItem = {
      path: manifest.tab.path,
      label: manifest.label,
      icon: resolveIcon(manifest.icon),
    };

    const pos = manifest.tab.position ?? "end";
    if (pos === "end") {
      items.push(pluginItem);
    } else if (pos.startsWith("after:")) {
      const target = "/" + pos.slice(6);
      const idx = items.findIndex((i) => i.path === target);
      items.splice(idx >= 0 ? idx + 1 : items.length, 0, pluginItem);
    } else if (pos.startsWith("before:")) {
      const target = "/" + pos.slice(7);
      const idx = items.findIndex((i) => i.path === target);
      items.splice(idx >= 0 ? idx : items.length, 0, pluginItem);
    } else {
      items.push(pluginItem);
    }
  }

  return items;
}

/** Split merged nav into built-in sidebar entries vs plugin tabs, preserving plugin order hints. */
function partitionSidebarNav(
  builtIn: NavItem[],
  manifests: PluginManifest[],
): { coreItems: NavItem[]; pluginItems: NavItem[] } {
  const merged = buildNavItems(builtIn, manifests);
  const builtinPaths = new Set(builtIn.map((i) => i.path));
  const coreItems: NavItem[] = [];
  for (const item of merged) {
    if (builtinPaths.has(item.path)) coreItems.push(item);
  }
  // Clean slate: plugin-provided tabs (e.g. Kanban) are kept OUT of the
  // sidebar. Their routes still resolve by URL, but the nav shows only Zeb's
  // own functional surfaces — no plugin clutter.
  return { coreItems, pluginItems: [] };
}

function buildRoutes(
  builtinRoutes: Record<string, ComponentType>,
  manifests: PluginManifest[],
): Array<{
  key: string;
  path: string;
  element: ReactNode;
}> {
  const byOverride = new Map<string, PluginManifest>();
  const addons: PluginManifest[] = [];

  for (const m of manifests) {
    if (m.tab.override) {
      byOverride.set(m.tab.override, m);
    } else {
      addons.push(m);
    }
  }

  const routes: Array<{
    key: string;
    path: string;
    element: ReactNode;
  }> = [];

  for (const [path, Component] of Object.entries(builtinRoutes)) {
    const om = byOverride.get(path);
    if (om) {
      routes.push({
        key: `override:${om.name}`,
        path,
        element: <PluginPage name={om.name} />,
      });
    } else {
      routes.push({ key: `builtin:${path}`, path, element: <Component /> });
    }
  }

  for (const m of addons) {
    if (m.tab.hidden) continue;
    if (m.tab.path === "/plugins") continue;
    if (builtinRoutes[m.tab.path]) continue;
    routes.push({
      key: `plugin:${m.name}`,
      path: m.tab.path,
      element: <PluginPage name={m.name} />,
    });
  }

  for (const m of manifests) {
    if (!m.tab.hidden) continue;
    if (m.tab.path === "/plugins") continue;
    if (builtinRoutes[m.tab.path] || m.tab.override) continue;
    routes.push({
      key: `plugin:hidden:${m.name}`,
      path: m.tab.path,
      element: <PluginPage name={m.name} />,
    });
  }

  return routes;
}

const SIDEBAR_COLLAPSED_KEY = "zeb-sidebar-collapsed";
const CONFIG_GROUP_OPEN_KEY = "zeb-nav-config-open";

function readConfigGroupOpenPreference() {
  try {
    return localStorage.getItem(CONFIG_GROUP_OPEN_KEY) === "true";
  } catch {
    return false;
  }
}

export default function App() {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const { manifests, loading: pluginsLoading } = usePlugins();
  const { theme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const closeMobile = useCallback(() => setMobileOpen(false), []);

  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
    } catch {
      return false;
    }
  });
  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      } catch { /* localStorage may be unavailable in private browsing */ }
      return next;
    });
  }, []);
  const isMobile = useBelowBreakpoint(1024);
  const isDesktopCollapsed = collapsed && !isMobile;
  const configRouteActive = BUILTIN_NAV_CONFIG.some(
    ({ path }) => pathname === path || pathname.startsWith(`${path}/`),
  );
  const [sidebarConfigOpen, setSidebarConfigOpen] = useState(
    () => configRouteActive || readConfigGroupOpenPreference(),
  );
  const handleSidebarConfigOpenChange = useCallback((open: boolean) => {
    setSidebarConfigOpen(open);
  }, []);
  const tooltipWarmRef = useRef(0);
  const sidebarStatus = useSidebarStatus();

  // Live dashboard state Zeb can rewrite in real time (brand, tagline, a
  // pinned note). Polled so Zeb's own edits — Zeb reshaping its own face —
  // show up within a few seconds while the user is watching.
  const [dashSelf, setDashSelf] = useState<DashboardSelfState>({});
  useEffect(() => {
    let alive = true;
    const poll = () => {
      if (document.hidden) return;
      api
        .getDashboardSelf()
        .then((s) => {
          if (alive) setDashSelf(s || {});
        })
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  const brandName =
    (dashSelf.brand && dashSelf.brand.trim()) || t.app.brand || "Zeb";
  const isDocsRoute = pathname === "/docs" || pathname === "/docs/";
  const normalizedPath = pathname.replace(/\/$/, "") || "/";
  const isChatRoute = normalizedPath === "/chat";
  const embeddedChat = isDashboardEmbeddedChatEnabled();

  // `dashboard.show_token_analytics` gates the Analytics nav item.  The
  // page itself remains reachable by URL (it renders an explanation when
  // the flag is off — see AnalyticsPage), but hiding the nav entry avoids
  // surfacing misleading token/cost numbers in the sidebar.  Default off.
  const [showTokenAnalytics, setShowTokenAnalytics] = useState(false);
  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        const dash = (cfg?.dashboard ?? {}) as {
          show_token_analytics?: unknown;
        };
        setShowTokenAnalytics(dash.show_token_analytics === true);
      })
      .catch(() => setShowTokenAnalytics(false));
  }, []);

  // A plugin can replace the built-in /chat page via `tab.override: "/chat"`
  // in its manifest.  When one does, `buildRoutes` already swaps the route
  // element for <PluginPage /> — but we also have to suppress the
  // persistent ChatPage host below, or the plugin's page and the built-in
  // terminal would paint on top of each other.  The override is niche
  // (nothing ships overriding /chat today) but it's an advertised
  // extension point, so preserve the pre-persistence contract: when a
  // plugin owns /chat, the built-in chat UI is entirely absent.
  //
  // Waiting on `pluginsLoading` is load-bearing: manifests arrive
  // asynchronously from /api/dashboard/plugins, so on initial render
  // `chatOverriddenByPlugin` is always false.  Without the loading
  // gate, the persistent host would mount, spawn a PTY, and THEN get
  // yanked out from under the user when the plugin's manifest resolves
  // — killing the session mid-paint.  Delaying host mount by the
  // plugin-load window (typically <50ms, worst case 2s safety timeout)
  // is the cheaper trade-off.
  const chatOverriddenByPlugin = useMemo(
    () => manifests.some((m) => m.tab.override === "/chat"),
    [manifests],
  );

  const builtinRoutes = useMemo(
    () => ({
      ...BUILTIN_ROUTES_CORE,
      ...(embeddedChat ? { "/chat": ChatRouteSink } : {}),
    }),
    [embeddedChat],
  );

  const builtinNav = useMemo(() => {
    const base = embeddedChat
      ? [CHAT_NAV_ITEM, ...BUILTIN_NAV_REST]
      : BUILTIN_NAV_REST;
    return showTokenAnalytics
      ? base
      : base.filter((n) => n.path !== "/analytics");
  }, [embeddedChat, showTokenAnalytics]);

  const sidebarNav = useMemo(
    () => partitionSidebarNav(builtinNav, manifests),
    [builtinNav, manifests],
  );
  const routes = useMemo(
    () => buildRoutes(builtinRoutes, manifests),
    [builtinRoutes, manifests],
  );
  const pluginTabMeta = useMemo(
    () =>
      manifests
        .filter((m) => !m.tab.hidden)
        .map((m) => ({
          path: m.tab.override ?? m.tab.path,
          label: m.label,
        })),
    [manifests],
  );

  const layoutVariant = theme.layoutVariant ?? "standard";

  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [mobileOpen]);

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 1024px)");
    const onChange = (e: MediaQueryListEvent) => {
      if (e.matches) setMobileOpen(false);
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return (
    <ProfileProvider>
    <div
      data-layout-variant={layoutVariant}
      className="zeb-app-shell flex h-dvh max-h-dvh min-h-0 flex-col overflow-hidden bg-background-base text-text-primary antialiased"
    >
      <SelectionSwitcher />

      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-0"
      >
        <PluginSlot name="backdrop" />
      </div>

      <header
        className={cn(
          "lg:hidden fixed top-0 left-0 right-0 z-40 min-h-14",
          "flex items-center gap-2 px-4 py-2",
          "border-b border-current/20",
          "bg-background-base",
        )}
        style={{
          background: "var(--component-header-background)",
          borderImage: "var(--component-header-border-image)",
          clipPath: "var(--component-header-clip-path)",
        }}
      >
        <Button
          ghost
          size="icon"
          onClick={() => setMobileOpen(true)}
          aria-label={t.app.openNavigation}
          aria-expanded={mobileOpen}
          aria-controls="app-sidebar"
          className="text-text-secondary hover:text-midground"
        >
          <Menu />
        </Button>

        <Typography className="font-bold text-[0.95rem] leading-[0.95] tracking-[0.05em] text-midground">
          {t.app.brand}
        </Typography>
      </header>

      {mobileOpen && (
        <Button
          ghost
          aria-label={t.app.closeNavigation}
          onClick={closeMobile}
          className={cn(
            "lg:hidden fixed inset-0 z-40 p-0 block",
            "bg-black/70",
          )}
        />
      )}

      <PluginSlot name="header-banner" />
      <ProfileScopeBanner />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden pt-14 lg:pt-0">
        <div className="flex min-h-0 min-w-0 flex-1">
          <aside
            id="app-sidebar"
            aria-label={t.app.navigation}
            className={cn(
              "zeb-sidebar fixed top-0 left-0 z-50 flex h-dvh max-h-dvh w-64 min-h-0 flex-col font-sans",
              "border-r border-current/20",
              "bg-background-base",
              "transition-[transform] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)]",
              mobileOpen ? "translate-x-0" : "-translate-x-full",
              "lg:sticky lg:top-0 lg:translate-x-0 lg:shrink-0 lg:overflow-hidden",
              "lg:transition-[width] lg:duration-300 lg:ease-[cubic-bezier(0.23,1,0.32,1)]",
              collapsed && "lg:w-14",
            )}
            style={{
              background: "var(--component-sidebar-background)",
              clipPath: "var(--component-sidebar-clip-path)",
              borderImage: "var(--component-sidebar-border-image)",
            }}
          >
            <div
              className={cn(
                "flex h-14 shrink-0 items-center gap-2",
                "border-b border-current/20",
                collapsed ? "lg:justify-center lg:px-0" : "px-4 justify-between",
              )}
            >
              <div
                className={cn(
                  "flex items-center gap-2",
                  collapsed && "lg:hidden",
                )}
              >
                <PluginSlot name="header-left" />

                {/* One name. This whole system — dashboard, OS, local model,
                    every connected provider, the VPS — IS Zeb. Not "ZebOS",
                    not a tool that runs Zeb: one unified being. The label is
                    live: Zeb can rename its own brand via /api/dashboard/self. */}
                <Typography className="font-bold text-[1.125rem] leading-[0.95] tracking-[0.14em] text-midground uppercase">
                  {brandName}
                </Typography>
              </div>

              <Button
                ghost
                size="icon"
                onClick={closeMobile}
                aria-label={t.app.closeNavigation}
                className="lg:hidden text-text-secondary hover:text-midground"
              >
                <X />
              </Button>

              <Button
                ghost
                size="icon"
                onClick={toggleCollapsed}
                aria-label={
                  collapsed ? t.common.expand : t.common.collapse
                }
                className="hidden lg:flex text-text-secondary hover:text-midground"
              >
                {collapsed ? (
                  <PanelLeftOpen className="h-4 w-4" />
                ) : (
                  <PanelLeftClose className="h-4 w-4" />
                )}
              </Button>
            </div>

            <ProfileSwitcher collapsed={isDesktopCollapsed} />

            <nav
              className={cn(
                "flex min-h-0 w-full flex-col overflow-x-hidden border-t border-current/10 py-2",
                isDesktopCollapsed
                  ? "flex-1 overflow-y-auto"
                  : sidebarConfigOpen
                    ? "flex-auto overflow-y-auto overscroll-contain"
                    : "shrink-0 overflow-y-hidden",
              )}
              aria-label={t.app.navigation}
            >
              <ul className="flex shrink-0 flex-col">
                {sidebarNav.coreItems
                  .filter((item) => !CONFIG_NAV_PATHS.has(item.path))
                  .map((item) => (
                    <SidebarNavLink
                      closeMobile={closeMobile}
                      collapsed={isDesktopCollapsed}
                      item={item}
                      key={item.path}
                      t={t}
                      tooltipWarmRef={tooltipWarmRef}
                    />
                  ))}
              </ul>

              <SidebarConfigGroup
                closeMobile={closeMobile}
                collapsed={isDesktopCollapsed}
                items={sidebarNav.coreItems.filter((item) =>
                  CONFIG_NAV_PATHS.has(item.path),
                )}
                onOpenChange={handleSidebarConfigOpenChange}
                t={t}
                tooltipWarmRef={tooltipWarmRef}
              />

              {sidebarNav.pluginItems.length > 0 && (
                <div
                  aria-labelledby="zeb-sidebar-plugin-nav-heading"
                  className="flex flex-col border-t border-current/10 pb-2"
                  role="group"
                >
                  <span
                    className={cn(
                      "px-5 pt-2.5 pb-1",
                      "font-sans text-display text-xs tracking-[0.12em] text-text-tertiary",
                      isDesktopCollapsed && "lg:hidden",
                    )}
                    id="zeb-sidebar-plugin-nav-heading"
                  >
                    {t.app.pluginNavSection}
                  </span>

                  <ul className="flex flex-col">
                    {sidebarNav.pluginItems.map((item) => (
                      <SidebarNavLink
                        closeMobile={closeMobile}
                        collapsed={isDesktopCollapsed}
                        item={item}
                        key={item.path}
                        t={t}
                        tooltipWarmRef={tooltipWarmRef}
                      />
                    ))}
                  </ul>
                </div>
              )}
            </nav>

            <div
              className={cn(
                "mt-auto h-[clamp(8rem,22dvh,10.5rem)] min-h-0 shrink overflow-hidden",
                "[&_.zeb-roommate]:min-h-0",
                isDesktopCollapsed && "lg:hidden",
              )}
            >
              <ZebRoommate />
            </div>

            {/* Clean sidebar — only functional navigation remains. The admin
                actions panel (restart/update), sign-out, theme toggle (Zeb is
                always dark), and language selector were intentionally removed:
                Zeb is one being with one look, on a single-user box. Just a
                minimal live-status strip stays at the bottom. */}
            <div
              className={cn(
                "flex shrink-0 flex-col",
                isDesktopCollapsed && "lg:hidden",
              )}
            >
              <SidebarFooter status={sidebarStatus} />
            </div>
          </aside>

          <PageHeaderProvider pluginTabs={pluginTabMeta}>
            <div
              className={cn(
                "relative z-2 flex min-w-0 min-h-0 flex-1 flex-col",
                // Chat is full-bleed: its top bar and composer span the whole
                // content area edge-to-edge; every other page keeps gutters.
                isChatRoute ? "p-0" : "px-3 sm:px-6 pt-2 sm:pt-4 lg:pt-6",
                isDocsRoute && "min-h-0 flex-1",
              )}
            >
              <PluginSlot name="pre-main" />
              {/* Live pinned note — Zeb can post a message to itself/the user
                  via /api/dashboard/self and it appears here within seconds. */}
              {dashSelf.pinned_note && dashSelf.pinned_note.trim() ? (
                <div className="m-3 flex items-start gap-2 rounded-[var(--radius)] border border-[#a884ff]/30 bg-[#a884ff]/10 px-3 py-2 text-sm text-[#c4a9ff]">
                  <span className="mt-0.5 shrink-0 font-mono text-[0.65rem] uppercase tracking-[0.12em] opacity-70">
                    {brandName}
                  </span>
                  <span className="min-w-0">{dashSelf.pinned_note}</span>
                </div>
              ) : null}
              <div
                className={cn(
                  "w-full min-w-0",
                  !isChatRoute &&
                    "pb-[calc(2rem+env(safe-area-inset-bottom,0px))] lg:pb-8",
                  (isDocsRoute || isChatRoute) &&
                    "min-h-0 flex flex-1 flex-col",
                )}
              >
                <ProfileKeyedRoutes>
                  <Routes>
                    {routes.map(({ key, path, element }) => (
                      <Route key={key} path={path} element={element} />
                    ))}
                    <Route
                      path="*"
                      element={
                        <UnknownRouteFallback pluginsLoading={pluginsLoading} />
                      }
                    />
                  </Routes>
                </ProfileKeyedRoutes>

                {embeddedChat &&
                  !chatOverriddenByPlugin &&
                  (pluginsLoading ? (
                    isChatRoute ? (
                      <div
                        className="flex min-h-0 min-w-0 flex-1 items-center justify-center"
                        aria-busy="true"
                        aria-live="polite"
                      >
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          <Spinner />
                          <span>Loading chat…</span>
                        </div>
                      </div>
                    ) : null
                  ) : (
                    <div
                      data-chat-active={isChatRoute ? "true" : "false"}
                      className={cn(
                        "min-h-0 min-w-0",
                        isChatRoute ? "flex flex-1 flex-col" : "hidden",
                      )}
                      aria-hidden={!isChatRoute}
                    >
                      <ZebChatPage
                        isActive={isChatRoute}
                        sidebarCollapsed={isDesktopCollapsed}
                      />
                    </div>
                  ))}
              </div>
              <PluginSlot name="post-main" />
            </div>
          </PageHeaderProvider>
        </div>
      </div>

      <PluginSlot name="overlay" />
    </div>
    </ProfileProvider>
  );
}

/**
 * Remounts the entire routed page tree when the global management profile
 * changes. Pages load their data on mount; without this, a page opened
 * under profile A would keep showing A's state while writes (via the
 * fetchJSON ?profile= injection) silently targeted the newly selected
 * profile B — the exact stale-target footgun the switcher exists to kill.
 * Keying by profile resets every page's local state so it refetches under
 * the new scope. The persistent ChatPage host below handles its own
 * remount (channel keyed on scopedProfile).
 */
function ProfileKeyedRoutes({ children }: { children: ReactNode }) {
  const { profile } = useProfileScope();
  return <div key={profile || "__own__"} className="contents">{children}</div>;
}

function SidebarNavLink({
  closeMobile,
  collapsed,
  item,
  tooltipWarmRef,
  t,
}: SidebarNavLinkProps) {
  const { path, label, labelKey, icon: Icon } = item;
  const [hovered, setHovered] = useState(false);
  const [tooltipAnchor, setTooltipAnchor] = useState<HTMLElement | null>(null);

  const navLabel = labelKey
    ? ((t.app.nav as Record<string, string>)[labelKey] ?? label)
    : label;
  const showTooltip = (event: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>) => {
    setHovered(true);
    setTooltipAnchor(event.currentTarget);
  };
  const hideTooltip = () => {
    setHovered(false);
    setTooltipAnchor(null);
  };

  return (
    <li
      onMouseEnter={collapsed ? showTooltip : undefined}
      onMouseLeave={collapsed ? hideTooltip : undefined}
    >
      <NavLink
        to={path}
        end={path === "/sessions"}
        onClick={closeMobile}
        aria-label={collapsed ? navLabel : undefined}
        onFocus={collapsed ? showTooltip : undefined}
        onBlur={collapsed ? hideTooltip : undefined}
        className={({ isActive }) =>
          cn(
            "group/nav relative flex items-center gap-3",
            "px-5 py-2.5",
            "font-sans text-display uppercase text-sm tracking-[0.12em]",
            "whitespace-nowrap transition-colors cursor-pointer",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
            isActive
              ? "text-midground"
              : "text-text-secondary hover:text-midground",
          )
        }
        style={{
          clipPath: "var(--component-tab-clip-path)",
        }}
      >
        {({ isActive }) => (
          <>
            <Icon className="h-3.5 w-3.5 shrink-0" />

            <span
              className={cn(
                "truncate transition-opacity duration-300",
                collapsed ? "lg:opacity-0" : "lg:opacity-100",
              )}
            >
              {navLabel}
            </span>

            <span
              aria-hidden
              className="absolute inset-y-0.5 left-1.5 right-1.5 bg-midground opacity-0 pointer-events-none transition-opacity duration-200 group-hover/nav:opacity-5"
            />

            {isActive && (
              <span
                aria-hidden
                className="absolute left-0 top-0 bottom-0 w-px bg-midground"
              />
            )}
          </>
        )}
      </NavLink>

      {collapsed && hovered && tooltipAnchor && (
        <SidebarTooltip anchor={tooltipAnchor} label={navLabel} warmRef={tooltipWarmRef} />
      )}
    </li>
  );
}

/**
 * Collapsible "Configuration" section grouping the admin surfaces
 * (System, Profiles, Pairing, Webhooks, Channels, MCP, Plugins, Logs,
 * Config). Auto-expands when the active route lives inside it so deep
 * links always show where you are; the manual open/close preference is
 * remembered across reloads.
 */
function SidebarConfigGroup({
  closeMobile,
  collapsed,
  items,
  onOpenChange,
  t,
  tooltipWarmRef,
}: {
  closeMobile: () => void;
  collapsed: boolean;
  items: NavItem[];
  onOpenChange: (open: boolean) => void;
  t: Translations;
  tooltipWarmRef: TooltipWarmRef;
}) {
  const { pathname } = useLocation();
  const routeInside = items.some(
    (i) => pathname === i.path || pathname.startsWith(i.path + "/"),
  );
  const [openRaw, setOpenRaw] = useState(readConfigGroupOpenPreference);
  const open = openRaw || routeInside;
  useEffect(() => {
    onOpenChange(open);
  }, [onOpenChange, open]);
  const toggle = () => {
    setOpenRaw((prev) => {
      // When the route forces the group open, the first click should CLOSE
      // it — but that only sticks until navigation back inside the group.
      const next = routeInside ? false : !prev;
      try {
        localStorage.setItem(CONFIG_GROUP_OPEN_KEY, String(next));
      } catch {
        /* private browsing */
      }
      return next;
    });
  };

  if (items.length === 0) return null;

  // Icon-collapsed sidebar: no room for a group header — render the items
  // inline after a divider, keeping every page one click away.
  if (collapsed) {
    return (
      <ul className="mt-1 flex flex-col border-t border-current/10 pt-1">
        {items.map((item) => (
          <SidebarNavLink
            closeMobile={closeMobile}
            collapsed={collapsed}
            item={item}
            key={item.path}
            t={t}
            tooltipWarmRef={tooltipWarmRef}
          />
        ))}
      </ul>
    );
  }

  return (
    <div
      className="mt-1 flex shrink-0 flex-col border-t border-current/10 pt-1"
    >
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className={cn(
          "group/cfg relative flex w-full shrink-0 items-center gap-3",
          "px-5 py-2.5",
          "font-sans text-display uppercase text-xs tracking-[0.14em]",
          "whitespace-nowrap transition-colors cursor-pointer",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
          open ? "text-midground" : "text-text-tertiary hover:text-midground",
        )}
      >
        <Settings className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">Configuration</span>
        <ChevronDown
          className={cn(
            "ml-auto h-3.5 w-3.5 shrink-0 transition-transform duration-200",
            open ? "rotate-0" : "-rotate-90",
          )}
        />
        <span
          aria-hidden
          className="absolute inset-y-0.5 left-1.5 right-1.5 bg-midground opacity-0 pointer-events-none transition-opacity duration-200 group-hover/cfg:opacity-5"
        />
      </button>

      {open && (
        <ul className="flex flex-col">
          {items.map((item) => (
            <SidebarNavLink
              closeMobile={closeMobile}
              collapsed={collapsed}
              item={item}
              key={item.path}
              t={t}
              tooltipWarmRef={tooltipWarmRef}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function SidebarTooltip({ anchor, label, warmRef }: SidebarTooltipProps) {
  const rect = anchor.getBoundingClientRect();
  const sidebar = document.getElementById("app-sidebar");
  const sidebarRight = sidebar?.getBoundingClientRect().right ?? rect.right;
  const [isWarm, setIsWarm] = useState(false);

  useEffect(() => {
    if (!warmRef) {
      setIsWarm(false);
      return;
    }
    const now = Date.now();
    setIsWarm(now - warmRef.current < 300);
    warmRef.current = now;
    return () => {
      if (warmRef) warmRef.current = Date.now();
    };
  }, [warmRef]);

  return createPortal(
    <span
      className={cn(
        "fixed z-[100] pointer-events-none",
        "px-2 py-1",
        "bg-background-base border border-current/20 shadow-lg",
        "font-sans text-display text-xs tracking-[0.1em] text-midground uppercase",
      )}
      style={{
        top: rect.top + rect.height / 2,
        left: sidebarRight + 8,
        transform: "translateY(-50%)",
        opacity: isWarm ? 1 : undefined,
        animation: isWarm ? "none" : "sidebar-tooltip-in 120ms ease-out",
      }}
    >
      {label}
    </span>,
    document.body,
  );
}

type TooltipWarmRef = React.RefObject<number>;

interface NavItem {
  icon: ComponentType<{ className?: string }>;
  label: string;
  labelKey?: string;
  path: string;
}

interface SidebarNavLinkProps {
  closeMobile: () => void;
  collapsed: boolean;
  item: NavItem;
  t: Translations;
  tooltipWarmRef: TooltipWarmRef;
}

interface SidebarTooltipProps {
  anchor: HTMLElement;
  label: string;
  warmRef?: TooltipWarmRef;
}
