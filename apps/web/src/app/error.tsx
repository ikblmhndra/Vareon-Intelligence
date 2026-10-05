"use client";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-4 text-center">
      <p className="text-sm text-muted-foreground">Terjadi kesalahan saat memuat halaman ini.</p>
      <button
        type="button"
        onClick={reset}
        className="rounded-full border border-border px-4 py-2 text-sm hover:bg-muted"
      >
        Coba lagi
      </button>
    </div>
  );
}
