import { useTranslation } from "react-i18next";
import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { MedicationsProvider } from "./lib/medications";
import AboutPage from "./routes/AboutPage";
import CheckPage from "./routes/CheckPage";
import ResultsPage from "./routes/ResultsPage";
import ScanPage from "./routes/ScanPage";

function NotFound() {
  const { t } = useTranslation();
  return <p className="py-8 text-center">{t("notFound")}</p>;
}

export default function App() {
  return (
    <MedicationsProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<CheckPage />} />
          <Route path="results" element={<ResultsPage />} />
          <Route path="scan" element={<ScanPage />} />
          <Route path="about" element={<AboutPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </MedicationsProvider>
  );
}
