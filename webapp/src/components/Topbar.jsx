import { useEffect } from "react";
import { House } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { Link, useLocation } from "react-router-dom";
import logo from "../assets/asap_black.png";
import {
  ACCESS_MODE_STORAGE_KEY,
  GUEST_ACCESS_MODE,
  ResolveAccessMode,
  ResolveExpertToolbarSection,
} from "../lib/expertAccess";

export default function Topbar() {
  const reduceMotion = useReducedMotion();
  const { pathname, search } = useLocation();
  const accessMode = ResolveAccessMode(
    pathname,
    window.sessionStorage.getItem(ACCESS_MODE_STORAGE_KEY),
    search,
  );
  const isGuestMode = accessMode === GUEST_ACCESS_MODE;
  const toolbarItems = [
    { to: "/classification", label: "품목 분류" },
    { to: "/enterprise", label: "수출 프로젝트" },
  ];
  const activePath = isGuestMode
    ? ""
    : ResolveExpertToolbarSection(pathname, search);

  useEffect(() => {
    window.sessionStorage.setItem(ACCESS_MODE_STORAGE_KEY, accessMode);
  }, [accessMode]);

  return (
    <header id="app-topbar" className="sticky top-0 z-80 border-b bg-surface/95 backdrop-blur-md">
      <div className="mx-auto flex min-h-16 w-full max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2 sm:px-7">
        <Link to="/" className="inline-flex items-center" aria-label="ASAP 소개 화면">
          <span
            className="app-topbar-logo"
            role="img"
            aria-label="ASAP"
            style={{ WebkitMaskImage: `url(${logo})`, maskImage: `url(${logo})` }}
          />
        </Link>
        {isGuestMode ? (
          <span className="rounded-lg bg-muted px-3 py-2 text-sm font-semibold text-muted-foreground">
            게스트 모드
          </span>
        ) : (
          <nav className="relative flex items-center gap-1 rounded-xl border bg-muted/60 p-1" aria-label="전문가 주요 화면">
            {toolbarItems.map((item) => {
              const active = activePath === item.to;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  aria-current={active ? "page" : undefined}
                  className="relative isolate flex h-9 items-center rounded-lg px-3 text-sm font-semibold text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:text-foreground"
                >
                  {active ? (
                    <motion.span
                      layoutId="expert-pill-nav-active"
                      className="absolute inset-0 -z-10 rounded-lg border bg-surface shadow-sm"
                      transition={{ duration: reduceMotion ? 0 : 0.2, ease: "easeOut" }}
                    />
                  ) : null}
                  <span className={active ? "text-foreground" : ""}>{item.label}</span>
                </Link>
              );
            })}
          </nav>
        )}
        <Link to="/" className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
          <House aria-hidden="true" />
          처음으로
        </Link>
      </div>
    </header>
  );
}
