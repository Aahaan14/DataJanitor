import { Route, Routes } from "react-router-dom";
import { AppLayout } from "./layouts/AppLayout";
import { ToastProvider } from "./components/Toast";
import { LinkButton, EmptyState } from "./components/ui";
import DashboardPage from "./pages/DashboardPage";
import UploadPage from "./pages/UploadPage";
import DatasetsPage from "./pages/DatasetsPage";
import DatasetDetailPage from "./pages/DatasetDetailPage";
import ScanDetailPage from "./pages/ScanDetailPage";
import PlanReviewPage from "./pages/PlanReviewPage";
import CleanedDetailPage from "./pages/CleanedDetailPage";
import HistoryPage from "./pages/HistoryPage";
import SettingsPage from "./pages/SettingsPage";

function NotFoundPage() {
  return (
    <EmptyState title="Page not found" action={<LinkButton to="/" variant="primary">Go to the dashboard</LinkButton>}>
      The page you are looking for does not exist.
    </EmptyState>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="datasets" element={<DatasetsPage />} />
          <Route path="datasets/:datasetId" element={<DatasetDetailPage />} />
          <Route path="scans/:scanId" element={<ScanDetailPage />} />
          <Route path="plans/:planId" element={<PlanReviewPage />} />
          <Route path="cleaned/:cleanedId" element={<CleanedDetailPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </ToastProvider>
  );
}
