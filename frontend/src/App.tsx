import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { EnvironmentFormPage } from "./pages/EnvironmentFormPage";
import { EnvironmentsPage } from "./pages/EnvironmentsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { ImportPage } from "./pages/ImportPage";
import { SuiteDetailPage } from "./pages/SuiteDetailPage";
import { SuiteListPage } from "./pages/SuiteListPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<SuiteListPage />} />
          <Route path="/suites/:id" element={<SuiteDetailPage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/environments" element={<EnvironmentsPage />} />
          <Route path="/environments/new" element={<EnvironmentFormPage />} />
          <Route
            path="/environments/:id/edit"
            element={<EnvironmentFormPage />}
          />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
