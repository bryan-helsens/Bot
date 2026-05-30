import { useCallback, useEffect, useState } from "react";

// Poll an async fetcher on an interval, with manual refresh and error capture.
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs = 5000,
  deps: unknown[] = [],
): { data: T | null; error: string | null; refresh: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const memoFetcher = useCallback(fetcher, deps);

  const refresh = useCallback(() => {
    memoFetcher()
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  }, [memoFetcher]);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, intervalMs);
    return () => window.clearInterval(id);
  }, [refresh, intervalMs]);

  return { data, error, refresh };
}
