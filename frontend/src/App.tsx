import { useTranslation } from "react-i18next";
import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import AboutPage from "./routes/AboutPage";
import CheckPage from "./routes/CheckPage";

function NotFound() {
  const { t } = useTranslation();
  return <p className="py-8 text-center">{t("notFound")}</p>;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<CheckPage />} />
        <Route path="about" element={<AboutPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
