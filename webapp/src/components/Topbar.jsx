import { Link, useLocation } from "react-router-dom";
import logo from "../assets/asap_black.png";

export default function Topbar() {
  const { pathname } = useLocation();
  const isClassification = pathname === "/" || pathname.startsWith("/classification");
  return (
    <header id="app-topbar" className="app-topbar">
      <Link to="/classification" className="app-topbar-logo-link">
        <span
          className="app-topbar-logo"
          role="img"
          aria-label="ASAP"
          style={{ WebkitMaskImage: `url(${logo})`, maskImage: `url(${logo})` }}
        />
      </Link>
      <nav className="app-topbar-tabs">
        <Link
          to="/classification"
          className={`app-topbar-tab ${isClassification ? "active" : ""}`}
        >
          프로젝트
        </Link>
      </nav>
    </header>
  );
}
