import { Button } from "@/components/ui/button";

interface LoadMoreFooterProps {
  shown: number;
  total: number;
  onLoadMore: () => void;
  loading: boolean;
  hasMore: boolean;
}

/** Kaki daftar "Showing 1-{shown} of {total}" + tombol outline "Load more" (disembunyikan bila habis). */
export function LoadMoreFooter({ shown, total, onLoadMore, loading, hasMore }: LoadMoreFooterProps) {
  return (
    <div className="flex items-center justify-between gap-3 pt-3">
      <p className="text-xs text-muted-foreground">
        Showing {shown === 0 ? 0 : `1-${shown}`} of {total}
      </p>
      {hasMore && (
        <Button variant="outline" size="sm" onClick={onLoadMore} loading={loading}>
          Load more
        </Button>
      )}
    </div>
  );
}
