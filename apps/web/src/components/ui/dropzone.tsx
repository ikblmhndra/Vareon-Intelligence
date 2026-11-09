"use client";

import { useRef, useState, type DragEvent } from "react";
import { UploadIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface DropzoneProps {
  /** Nilai atribut `accept` input file (mis. ".json,.lock"). */
  accept: string;
  file: File | null;
  onFile: (file: File | null) => void;
  error?: string;
  hint?: string;
  "aria-label": string;
}

/** Area unggah: klik/Enter/Spasi membuka pemilih berkas, atau seret-lepas. Menampilkan nama berkas +
 * tautan "Replace file"; `error` = border `primary`. Input native disembunyikan, area = `role=button`. */
export function Dropzone({
  accept,
  file,
  onFile,
  error,
  hint,
  "aria-label": ariaLabel,
}: DropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const open = () => inputRef.current?.click();

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setOver(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onFile(dropped);
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="button"
        tabIndex={0}
        aria-label={ariaLabel}
        onClick={open}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            open();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed bg-surface px-4 py-8 text-center transition-colors outline-none hover:bg-panel focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          error ? "border-primary" : over ? "border-foreground bg-panel" : "border-border",
        )}
      >
        <UploadIcon aria-hidden className="size-5 text-muted-foreground" />
        {file ? (
          <>
            <span className="font-code text-xs font-medium break-all">{file.name}</span>
            <span className="text-xs font-semibold text-primary-text underline-offset-4 hover:underline">
              Replace file
            </span>
          </>
        ) : (
          <span className="text-sm font-semibold">Drop a file here or click to browse</span>
        )}
        {hint && !file && <span className="text-xs text-muted-foreground">{hint}</span>}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        tabIndex={-1}
        aria-hidden
        className="hidden"
        onChange={(e) => {
          onFile(e.target.files?.[0] ?? null);
          e.target.value = "";
        }}
      />
      {error && (
        <p role="alert" className="text-xs text-primary-text">
          {error}
        </p>
      )}
    </div>
  );
}
