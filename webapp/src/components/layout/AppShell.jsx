import { useLocation } from "react-router-dom";

import Topbar from "@/components/Topbar";

export default function AppShell({ children }) {
  const isIntroduction = useLocation().pathname === "/";

  return (
    <div className="app-shell">
      {isIntroduction ? null : <Topbar />}
      <main className={isIntroduction ? "introduction-main" : "app-main"}>
        {children}
      </main>
    </div>
  );
}
