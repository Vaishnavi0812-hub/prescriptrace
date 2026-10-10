import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { searchDrugs, type SearchHit } from "../lib/api";

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

/**
 * "Add medicine" box: accessible combobox with typo-tolerant suggestions. Picking a suggestion
 * adds a confirmed medicine; pressing Enter on free text adds it for recognition (and the user
 * is asked to confirm if it is unclear).
 */
export function DrugSearch({
  onPick,
  onType,
}: {
  onPick: (hit: SearchHit) => void;
  onType: (text: string) => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const query = useDebounced(text.trim(), 200);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const hintId = useId();
  const labelId = useId();

  const { data, isFetching, isError } = useQuery({
    queryKey: ["search", query],
    queryFn: ({ signal }) => searchDrugs(query, signal),
    enabled: query.length >= 2,
    staleTime: 5 * 60_000,
    placeholderData: (previous) => previous,
  });
  const hits = query.length >= 2 ? (data?.hits ?? []) : [];
  const showList = open && query.length >= 2 && (hits.length > 0 || !isFetching);

  const reset = () => {
    setText("");
    setActive(-1);
    setOpen(false);
    inputRef.current?.focus();
  };

  const pick = (hit: SearchHit) => {
    onPick(hit);
    reset();
  };

  const submitTyped = () => {
    const value = text.trim();
    if (value.length >= 2) {
      onType(value);
      reset();
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, hits.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const hit = active >= 0 ? hits[active] : undefined;
      if (hit) pick(hit);
      else submitTyped();
    } else if (e.key === "Escape") {
      setOpen(false);
      setActive(-1);
    }
  };

  return (
    <div className="relative">
      <label id={labelId} htmlFor={`${listId}-input`} className="mb-2 block text-lg font-semibold">
        {t("check.addMedicine")}
      </label>
      <div className="flex gap-2">
        <input
          ref={inputRef}
          id={`${listId}-input`}
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${listId}-opt-${active}` : undefined}
          aria-describedby={hintId}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          enterKeyHint="done"
          value={text}
          placeholder={t("check.placeholder")}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
            setActive(-1);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={onKeyDown}
          className="min-h-14 w-full rounded-xl border-2 border-border-strong bg-surface px-4 text-lg placeholder:text-muted"
        />
        <button
          type="button"
          onClick={submitTyped}
          disabled={text.trim().length < 2}
          className="min-h-14 shrink-0 rounded-xl bg-primary px-4 font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
        >
          {t("check.add")}
        </button>
      </div>
      <p id={hintId} className="mt-1 text-sm text-muted">
        {t("check.addMedicineHint")}
      </p>

      {showList && (
        <div
          id={listId}
          role="listbox"
          aria-labelledby={labelId}
          className="absolute z-10 mt-1 max-h-80 w-full overflow-auto rounded-xl border border-sand bg-surface shadow-lg"
        >
          {hits.map((hit, i) => (
            <div
              key={hit.ref}
              id={`${listId}-opt-${i}`}
              role="option"
              tabIndex={-1}
              aria-selected={i === active}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick(hit)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  pick(hit);
                }
              }}
              className={`flex min-h-12 cursor-pointer flex-col justify-center px-4 py-2 ${
                i === active ? "bg-primary/10" : "hover:bg-cream"
              }`}
            >
              <span className="font-medium">
                {hit.label}
                <span className="ml-2 text-xs font-normal text-muted">{t(`kind.${hit.kind}`, hit.kind)}</span>
              </span>
              <span className="text-sm text-muted">
                {t("check.contains", { names: hit.ingredient_names.join(", ") })}
              </span>
            </div>
          ))}
          {!hits.length && !isError && (
            <p className="px-4 py-3 text-sm text-muted">{t("check.noMatches")}</p>
          )}
          {isError && <p className="px-4 py-3 text-sm text-muted">{t("check.searchOffline")}</p>}
        </div>
      )}
    </div>
  );
}
