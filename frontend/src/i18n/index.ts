import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./en.json";

// English is the source of truth. Hindi and Kannada are added in Stage 9 and
// flagged "needs review" wherever strings were machine-translated.
void i18n.use(initReactI18next).init({
  resources: { en: { translation: en } },
  lng: "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export default i18n;
