import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Topbar from "./components/Topbar";
import AdminPage from "./pages/AdminPage";
import ConsumerPage from "./pages/ConsumerPage";
import DocumentPage from "./pages/DocumentPage";
import EnterpriseAdminPage from "./pages/EnterpriseAdminPage";
import EnterprisePage from "./pages/EnterprisePage";
import WorkbenchPage from "./pages/WorkbenchPage";
import "./styles/base.css";
import "./styles/workbench.css";
import "./styles/admin.css";
import "./styles/document.css";
import "./styles/consumer.css";
import "./styles/enterprise.css";

function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <Topbar />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<WorkbenchPage />} />
            <Route path="/classification" element={<WorkbenchPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/admin/companies" element={<EnterpriseAdminPage />} />
            <Route path="/consumer" element={<ConsumerPage />} />
            <Route path="/enterprise" element={<EnterprisePage />} />
            <Route path="/document/:jobId/:taric10" element={<DocumentPage />} />
            <Route path="*" element={<Navigate to="/classification" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
