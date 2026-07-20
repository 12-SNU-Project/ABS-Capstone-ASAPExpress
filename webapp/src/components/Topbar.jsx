import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import logo from "../assets/asap_black.png";
import {
  ACCESS_MODE_STORAGE_KEY,
  GUEST_ACCESS_MODE,
  ResolveAccessMode,
} from "../lib/expertAccess";

export default function Topbar() {
  const { pathname } = useLocation();
  const accessMode = ResolveAccessMode(
    pathname,
    window.sessionStorage.getItem(ACCESS_MODE_STORAGE_KEY),
  );
  const isGuestMode = accessMode === GUEST_ACCESS_MODE;
  const toolbarItems = isGuestMode
    ? [{ to: "/consumer", label: "소비자 화면" }]
    : [
        { to: "/classification", label: "관리자 화면" },
        { to: "/enterprise", label: "기업 서비스" },
      ];

  useEffect(() => {
    window.sessionStorage.setItem(ACCESS_MODE_STORAGE_KEY, accessMode);
  }, [accessMode]);

  return (
    <header id="app-topbar" className="app-topbar">
      <Link to={toolbarItems[0].to} className="app-topbar-logo-link">
        <span
          className="app-topbar-logo"
          role="img"
          aria-label="ASAP"
          style={{ WebkitMaskImage: `url(${logo})`, maskImage: `url(${logo})` }}
        />
      </Link>
      <nav className="app-topbar-tabs">
        {toolbarItems.map((item) => (
          <Link
            key={item.to}
            to={item.to}
            className={`app-topbar-tab ${pathname.startsWith(item.to) ? "active" : ""}`}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <Link to="/" className="app-topbar-tab app-topbar-home">
        처음으로
      </Link>
    </header>
  );
}
