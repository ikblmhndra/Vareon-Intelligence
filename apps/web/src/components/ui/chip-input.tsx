"use client";

import { XIcon } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent } from "react";

import { cn } from "@/lib/utils";

interface ChipInputProps {
  values: string[];
  /** Kembalikan `false` bila pemilik menolak nilai baru (mis. negara tak terpetakan): teks yang diketik tetap di
   * kolom supaya bisa dibetulkan, bukan hilang bersama chip yang ditolak. */
  onChange: (v: string[]) => void | boolean;
  "aria-label": string;
  placeholder?: string;
  /** Sumber saran async (mis. nama entitas); ditampilkan lewat `<datalist>` native. */
  suggest?: (q: string) => Promise<string[]>;
  id?: string;
}

/** Input tag: chip dengan "×" + kolom teks inline. Enter/koma/blur menambah nilai ber-trim (blur supaya teks yang
 * belum di-Enter tidak hilang diam-diam saat form disimpan); Backspace pada kolom kosong menghapus chip terakhir.
 * Nilai kosong/spasi dan duplikat tanpa memandang huruf besar-kecil diabaikan: backend PIR tidak membuang keyword kosong, jadi komponen inilah penjaganya. */
export function ChipInput({
  values,
  onChange,
  "aria-label": ariaLabel,
  placeholder,
  suggest,
  id,
}: ChipInputProps) {
  const [text, setText] = useState("");
  const [options, setOptions] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const reqRef = useRef(0);
  const listId = useId();

  /** `false` = pemilik menolak nilai baru (lihat `onChange`). */
  function add(raw: string[]): boolean {
    const next = [...values];
    for (const r of raw) {
      const v = r.trim();
      if (!v || next.some((x) => x.toLowerCase() === v.toLowerCase())) continue;
      next.push(v);
    }
    if (next.length === values.length) return true;
    return onChange(next) !== false;
  }

  /** Jadikan teks di kolom chip; teks yang ditolak pemilik dibiarkan agar bisa dibetulkan. */
  function commit() {
    if (!add([text])) return;
    setText("");
    setOptions([]);
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    // Enter/koma saat IME masih menyusun (Jepang, Tionghoa, ...) milik IME, bukan perintah tambah chip
    if (e.nativeEvent.isComposing) return;
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault(); // Enter tidak boleh men-submit form pemilik; koma tidak ikut terketik
      commit();
    } else if (e.key === "Backspace" && text === "" && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  }

  function onInput(v: string) {
    if (v.includes(",")) {
      // tempel "a, b, c": semua bagian jadi chip, sisa setelah koma terakhir tetap di kolom
      const parts = v.split(",");
      const rest = parts.pop() ?? "";
      add(parts);
      setText(rest);
      return;
    }
    setText(v);
    if (!suggest) return;
    const q = v.trim();
    const req = ++reqRef.current;
    if (!q) {
      setOptions([]);
      return;
    }
    suggest(q)
      .then((r) => {
        if (req === reqRef.current) setOptions(r);
      })
      .catch(() => {
        if (req === reqRef.current) setOptions([]);
      });
  }

  return (
    <div
      onClick={() => inputRef.current?.focus()}
      className={cn(
        "flex min-h-10 w-full flex-wrap items-center gap-1.5 rounded-[10px] border border-input bg-background px-2 py-1.5",
        "focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 focus-within:ring-offset-background",
      )}
    >
      <ul aria-live="polite" aria-label={`${ariaLabel}, selected`} className="contents">
        {values.map((v) => (
          <li
            key={v.toLowerCase()}
            className="inline-flex items-center gap-1 rounded-md bg-panel py-0.5 pr-0.5 pl-2 text-xs text-foreground"
          >
            {v}
            <button
              type="button"
              aria-label={`Remove ${v}`}
              onClick={() => onChange(values.filter((x) => x !== v))}
              className="inline-flex size-5 items-center justify-center rounded-sm outline-none hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring"
            >
              <XIcon aria-hidden className="size-3" />
            </button>
          </li>
        ))}
      </ul>
      <input
        ref={inputRef}
        id={id}
        value={text}
        onChange={(e) => onInput(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={commit}
        aria-label={ariaLabel}
        placeholder={values.length === 0 ? placeholder : undefined}
        list={suggest ? listId : undefined}
        className="min-w-24 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted-foreground"
      />
      {suggest && (
        <datalist id={listId}>
          {options.map((o) => (
            <option key={o} value={o} />
          ))}
        </datalist>
      )}
    </div>
  );
}
