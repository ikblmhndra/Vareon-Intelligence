"use client";

import { useId, useState } from "react";

import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";

interface PresetControlProps {
  label: string;
  presets: readonly { value: number; label: string }[];
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  "aria-label": string;
}

const CUSTOM = "custom";

/** Kontrol angka berpreset: segmen preset + "Custom" yang membuka input angka. Input hanya diteruskan ke
 * `onChange` bila di dalam [min, max] (batas API); di luar itu tampil galat dan nilai lama dipertahankan,
 * jadi query tidak pernah dikirim dengan angka yang akan ditolak backend. */
export function PresetControl({
  label,
  presets,
  value,
  onChange,
  min,
  max,
  step,
  "aria-label": ariaLabel,
}: PresetControlProps) {
  const id = useId();
  const inputId = `${id}-custom`;
  const [custom, setCustom] = useState(false);
  const [draft, setDraft] = useState(String(value));
  const [error, setError] = useState<string>();

  // Nilai di luar preset (mis. 45) otomatis dianggap Custom, termasuk saat state awal dari luar.
  const isCustom = custom || !presets.some((p) => p.value === value);
  const options = [
    ...presets.map((p) => ({ value: String(p.value), label: p.label })),
    { value: CUSTOM, label: "Custom" },
  ];

  function pick(v: string) {
    setError(undefined);
    if (v === CUSTOM) {
      setDraft(String(value));
      setCustom(true);
      return;
    }
    setCustom(false);
    onChange(Number(v));
  }

  function commit() {
    const n = draft.trim() === "" ? Number.NaN : Number(draft);
    if (!Number.isFinite(n) || n < min || n > max) {
      setError(`Enter a value from ${min} to ${max}.`);
      return;
    }
    setError(undefined);
    onChange(n);
  }

  return (
    <div className="flex flex-col gap-1">
      <span className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">{label}</span>
      <div className="flex flex-wrap items-start gap-2">
        <SegmentedControl
          aria-label={ariaLabel}
          options={options}
          value={isCustom ? CUSTOM : String(value)}
          onChange={pick}
        />
        {isCustom && (
          <Field label={`${label} (custom)`} htmlFor={inputId} error={error} className="w-28 gap-1 [&>label]:sr-only">
            <Input
              id={inputId}
              type="number"
              inputMode="decimal"
              min={min}
              max={max}
              step={step}
              value={draft}
              aria-invalid={!!error}
              aria-describedby={fieldDescribedBy(inputId, { error })}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commit();
                }
              }}
              className="h-8 text-xs"
            />
          </Field>
        )}
      </div>
    </div>
  );
}
