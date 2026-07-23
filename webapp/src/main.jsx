import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppShell from "@/components/layout/AppShell";
import { TooltipProvider } from "@/components/ui/tooltip";
import AdminPage from "./pages/AdminPage";
import ConsumerPage from "./pages/ConsumerPage";
import DocumentPage from "./pages/DocumentPage";
import EnterprisePage from "./pages/EnterprisePage";
import IntroductionPage from "./pages/IntroductionPage";
import WorkbenchPage from "./pages/WorkbenchPage";
import "./styles/base.css";
import "./styles/introduction.css";
import "./styles/workbench.css";
import "./styles/admin.css";
import "./styles/document.css";
import "./styles/consumer.css";
import "./styles/enterprise.css";

function ApplicationLayout() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<IntroductionPage />} />
        <Route path="/classification" element={<WorkbenchPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/admin/companies" element={<Navigate to="/enterprise" replace />} />
        <Route path="/consumer" element={<ConsumerPage />} />
        <Route path="/enterprise" element={<EnterprisePage />} />
        <Route path="/document/:jobId/:taric10" element={<DocumentPage />} />
        <Route path="*" element={<Navigate to="/classification" replace />} />
      </Routes>
    </AppShell>
  );
}

function App() {
  return (
    <TooltipProvider>
      <BrowserRouter>
        <ApplicationLayout />
      </BrowserRouter>
    </TooltipProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
