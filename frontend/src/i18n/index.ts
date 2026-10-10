import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./en.json";
import hi from "./hi.json";
import kn from "./kn.json";

// English is the source of truth. Hindi and Kannada are machine translations that have not yet
// been reviewed by native speakers; the UI says so whenever one of them is selected.
export const LANGUAGES = [
  { code: "en", name: "English", reviewed: true },
  { code: "hi", name: "हिन्दी", reviewed: false },
  { code: "kn", name: "ಕನ್ನಡ", reviewed: false },
] as const;
export type LanguageCode = (typeof LANGUAGES)[number]["code"];

const KEY = "prescriptrace.lang"; // a per-device display preference, not patient data

function saved(): LanguageCode {
  try {
    const value = localStorage.getItem(KEY);
    return LANGUAGES.some((l) => l.code === value) ? (value as LanguageCode) : "en";
  } catch {
    return "en";
  }
}

export function setLanguage(code: LanguageCode): void {
  try {
    localStorage.setItem(KEY, code);
  } catch {
    // not remembered; still switches for this visit
  }
  void i18n.changeLanguage(code);
}

i18n.on("languageChanged", (lng) => {
  if (typeof document !== "undefined") document.documentElement.lang = lng;
});

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, hi: { translation: hi }, kn: { translation: kn } },
  lng: saved(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export default i18n;
