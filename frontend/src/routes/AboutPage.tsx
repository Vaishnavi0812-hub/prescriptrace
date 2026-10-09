import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

/** Stage 1 shell. The dataset table (versions, dates, licences) arrives with the API in Stage 6. */
export default function AboutPage() {
  const { t } = useTranslation();
  return (
    <section className="space-y-4 py-4">
      <h1 className="text-2xl font-bold">{t("about.title")}</h1>
      <p>{t("about.what")}</p>
      <p>{t("about.notWhat")}</p>
      <Link to="/" className="inline-flex min-h-11 items-center font-medium text-primary underline">
        {t("about.back")}
      </Link>
    </section>
  );
}
