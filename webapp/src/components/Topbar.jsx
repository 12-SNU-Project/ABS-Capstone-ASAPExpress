import { useEffect } from "react";
import { House } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import logo from "../assets/asap_black.png";
import {
  ACCESS_MODE_STORAGE_KEY,
  GUEST_ACCESS_MODE,
  ResolveAccessMode,
  ResolveExpertToolbarSection,
} from "../lib/expertAccess";

export default function Topbar() {
  const { pathname, search } = useLocation();
  const accessMode = ResolveAccessMode(
    pathname,
    window.sessionStorage.getItem(ACCESS_MODE_STORAGE_KEY),
    search,
  );
  const isGuestMode = accessMode === GUEST_ACCESS_MODE;
  const toolbarItems = isGuestMode
    ? [{ to: "/consumer", label: "소비자 화면" }]
    : [
        { to: "/classification", label: "관리자 화면" },
        { to: "/enterprise", label: "기업 서비스" },
      ];
  const activePath = isGuestMode
    ? "/consumer"
    : ResolveExpertToolbarSection(pathname, search);

  useEffect(() => {
    window.sessionStorage.setItem(ACCESS_MODE_STORAGE_KEY, accessMode);
  }, [accessMode]);

  return (
    <header id="app-topbar" className="app-topbar">
      <div className="app-topbar-inner">
        <Link to={toolbarItems[0].to} className="app-topbar-logo-link" aria-label="ASAP 작업공간">
          <span
            className="app-topbar-logo"
            role="img"
            aria-label="ASAP"
            style={{ WebkitMaskImage: `url(${logo})`, maskImage: `url(${logo})` }}
          />
        </Link>
        <nav className="app-topbar-tabs" aria-label="주요 화면">
          {toolbarItems.map((item) => {
            const active = activePath === item.to;
            return (
              <Link
                key={item.to}
                to={item.to}
                aria-current={active ? "page" : undefined}
                className={`app-topbar-tab ${active ? "active" : ""}`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <Link to="/" className="app-topbar-tab app-topbar-home">
          <House aria-hidden="true" />
          처음으로
        </Link>
      </div>
    </header>
  );
}
