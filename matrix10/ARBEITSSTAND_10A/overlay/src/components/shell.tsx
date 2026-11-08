import { Link, useRouterState } from "@tanstack/react-router";
import { NAV, NAV_MORE } from "@/lib/matrix/nav";
import { BUILD_ID } from "@/lib/matrix/types";
import { useMatrix, rebindStoredActor } from "@/lib/matrix/store";
import { readStoredActor } from "@/lib/matrix/api";
import { useHydrated, useMccReaderError } from "@/lib/matrix/use-hydrated";
import { cn } from "@/lib/cn";
import { refusalText } from "@/lib/matrix/confirm-reset";
import { useEffect, useRef } from "react";

// V65I (AMASTER §65 Diagnose zeigt Buildstand; dein Lauf 28.10. 15:31): a page that runs
// other app code than the server (cached before an update, or open across a restart)
// says so instead of acting silently on old code. Checked on load and whenever the page
// becomes visible again; /api/health reads VERSION.txt. Same snippet in the shell chunk.
function checkClientBuild() {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  fetch("/api/health", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((j: { build?: string } | null) => {
      const server = String(j?.build || "");
      if (!server || server === "UNKNOWN" || server === BUILD_ID || document.getElementById("m10-stale")) return;
      const box = document.createElement("div");
      box.id = "m10-stale";
      box.setAttribute("role", "alert");
      box.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:9999;padding:12px 16px;background:#b91c1c;color:#fff;font:15px/1.4 system-ui,sans-serif;overflow-wrap:anywhere";
      box.textContent = `Diese Seite läuft mit anderem App-Code (${BUILD_ID}) als der Server (${server}). Bitte neu laden.`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Neu laden";
      btn.style.cssText = "margin-left:12px;min-height:44px;padding:0 16px;border:0;border-radius:8px;background:#fff;color:#b91c1c;font-weight:600";
      btn.onclick = () => window.location.reload();
      box.appendChild(btn);
      document.body.appendChild(box);
    })
    .catch(() => undefined);
}
// Stand 10a (Android-Ausfall 08.11., AMASTER §65): the Rust consent core is checked by the server at start; when it
// cannot load, every page says so with the server's reason - not only the first touch input with a bare 503.
function checkRustKern() {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  fetch("/api/health", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((j: { rustKern?: { ok?: boolean; grund?: string; abhilfe?: string } } | null) => {
      const rk = j?.rustKern;
      const old = document.getElementById("m10-rust");
      if (!rk || rk.ok !== false) {
        old?.remove();
        return;
      }
      if (old) return;
      const box = document.createElement("div");
      box.id = "m10-rust";
      box.setAttribute("role", "alert");
      box.style.cssText = "position:fixed;left:0;right:0;top:0;z-index:9999;padding:12px 16px;background:#b91c1c;color:#fff;font:15px/1.4 system-ui,sans-serif;overflow-wrap:anywhere";
      box.textContent = `Rust-Einwilligungskern NICHT geladen: ${rk.grund || "unbekannt"}.${rk.abhilfe ? ` Abhilfe: ${rk.abhilfe}.` : ""} Berührungs-Eingaben werden bis dahin nicht gespeichert.`;
      document.body.appendChild(box);
    })
    .catch(() => undefined);
}
if (typeof window !== "undefined") {
  checkClientBuild();
  checkRustKern();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      checkClientBuild();
      checkRustKern();
    }
  });
}

export function Shell({ children, title, flush }: { children: React.ReactNode; title?: string; flush?: boolean }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const hydrated = useHydrated();
  const readerError = useMccReaderError();
  const users = useMatrix((s) => s.users);
  const activeUserId = useMatrix((s) => s.activeUserId);
  const persistFail = useMatrix((s) => {
    const e = s.logs.find((l) => l.code === "PERSIST_FAILED");
    if (!e) return undefined;
    const t = Date.parse(e.at);
    if (!Number.isFinite(t) || Date.now() - t > 90_000) return undefined;
    return e;
  });
  const user = users.find((u) => u.id === activeUserId);
  const large = hydrated && user?.largeType;
  const contrast = hydrated && user?.highContrast;
  const reboundFor = useRef("");

  useEffect(() => {
    if (!hydrated) return;
    const stored = readStoredActor();
    if (activeUserId && user) return;
    if (!stored) return;
    const key = `${stored}:${activeUserId}:${user?.id || ""}`;
    if (reboundFor.current === key) return;
    reboundFor.current = key;
    void rebindStoredActor().catch(() => undefined);
  }, [hydrated, activeUserId, user]);

  const actorShown = activeUserId || (hydrated ? readStoredActor() : "");
  const moreActive = NAV_MORE.some((item) => pathname === item.to || pathname.startsWith(`${item.to}/`));

  return (
    <div
      className={cn("min-h-dvh overflow-x-hidden bg-bg text-fg", large && "large-type text-[17px]", contrast && "hi-c")}
      data-hydrated={hydrated ? "1" : "0"}
      data-hydrate-error={readerError ? "1" : "0"}
      data-actor={hydrated ? actorShown : ""}
      data-user-name={hydrated ? (user?.name ?? "") : ""}
    >
      <a href="#inhalt" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-fg">
        Zum Inhalt
      </a>
      <header className="sticky top-0 z-30 border-b border-border bg-bg/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-[1680px] items-center justify-between gap-3 px-3 py-2.5 sm:px-4">
          <Link to="/" className="shrink-0">
            <span className="font-display text-base font-semibold tracking-tight">ChatHere</span>
          </Link>
          <p className="hidden min-w-0 truncate text-xs text-muted md:block">{title}</p>
          <div className="flex items-center gap-3 text-[11px] text-muted">
            <span className="hidden tabular-nums lg:inline">{BUILD_ID}</span>
            <Link to="/user" className="text-accent hover:underline">
              {!hydrated ? "User" : user?.name ?? (!activeUserId ? "Gast" : "User")}
            </Link>
          </div>
        </div>
        <nav className="border-t border-border" aria-label="Hauptnavigation">
          <div className="mx-auto flex max-w-[1680px] items-center gap-1 overflow-x-auto px-2 py-1.5 sm:px-4">
            {NAV.map((item) => {
              const active = item.to === "/" ? pathname === "/" : pathname === item.to || pathname.startsWith(`${item.to}/`);
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={cn(
                    "flex min-h-11 shrink-0 items-center rounded-[8px] px-3 text-sm font-medium transition-colors duration-150",
                    active ? "bg-subtle text-accent" : "text-muted hover:bg-elevated hover:text-fg",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
            <a href="/__matrix_speicher" className="flex min-h-11 shrink-0 items-center rounded-[8px] px-3 text-sm font-medium text-accent" aria-label="Sessions löschen und Datenbank prüfen">Löschen / Speicher</a>
            <details className="relative shrink-0">
              <summary
                className={cn(
                  "flex min-h-11 cursor-pointer list-none items-center rounded-[8px] px-3 text-sm font-medium",
                  moreActive ? "bg-subtle text-accent" : "text-muted hover:bg-elevated hover:text-fg",
                )}
              >
                Mehr
              </summary>
              <div className="absolute left-0 z-40 mt-1 min-w-[11rem] rounded-[12px] border border-border bg-elevated p-1 shadow-lg">
                {NAV_MORE.map((item) => (
                  <Link
                    key={item.to}
                    to={item.to}
                    className={cn(
                      "block min-h-11 rounded-[8px] px-3 py-2.5 text-sm",
                      pathname === item.to || pathname.startsWith(`${item.to}/`) ? "bg-subtle text-accent" : "text-muted hover:text-fg",
                    )}
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
            </details>
          </div>
        </nav>
      </header>
      {persistFail ? (
        <div className="border-b border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
          {(() => {
            const r = refusalText(persistFail.message);
            return (
              <>
                <strong>{r.title}</strong>
                {r.text ? <span>: {r.text}</span> : null}
                <span className="block text-xs opacity-80">Technische Angabe: {r.detail}</span>
              </>
            );
          })()}
        </div>
      ) : null}
      <div id="inhalt" tabIndex={-1} className={cn("mx-auto w-full", flush ? "max-w-none px-0 py-0" : "max-w-[1680px] px-3 py-5 sm:px-4")}>
        {children}
      </div>
    </div>
  );
}

export function Panel({ children, className, title }: { children: React.ReactNode; className?: string; title?: string }) {
  return (
    <section className={cn("rounded-[16px] border border-border bg-elevated p-4", className)}>
      {title ? <h2 className="mb-3 text-sm font-semibold text-fg">{title}</h2> : null}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="py-8 text-center text-sm text-muted">{children}</p>;
}

/** V25: Tabs — barrierearm (role=tablist, große Ziele ≥44px, Tastatur) — AMASTERv2 §61. */
export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (id: T) => void; items: Array<{ id: T; label: string }> }) {
  return (
    <div role="tablist" aria-label="Bereiche" className="mb-4 flex flex-wrap gap-2">
      {items.map((item) => {
        const active = item.id === value;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.id)}
            className={cn(
              "min-h-11 rounded-[10px] border px-4 text-sm font-medium transition-colors duration-150",
              active ? "border-accent bg-subtle text-accent" : "border-border bg-elevated text-muted hover:text-fg",
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

export function PageHead({ kicker, title, lede, actions }: { kicker?: string; title: string; lede?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        {kicker ? <p className="text-[11px] uppercase tracking-[0.18em] text-faint">{kicker}</p> : null}
        <h1 className="font-display text-3xl font-semibold tracking-tight">{title}</h1>
        {lede ? <p className="mt-1 max-w-[72ch] text-sm text-muted">{lede}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
