import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../services/api";

export interface AsyncState<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
  setData: (updater: (prev: T | undefined) => T | undefined) => void;
}

export function toApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, "unknown_error", "Something went wrong. Please try again.");
}

/**
 * Run an async function when `deps` change. Stale responses (from an older
 * request, or after unmount) are ignored, so fast filter changes cannot
 * show out-of-order data.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<{ data: T | undefined; error: ApiError | null; loading: boolean }>({
    data: undefined, error: null, loading: true,
  });
  const ticket = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(() => {
    const mine = ++ticket.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    fnRef.current().then(
      (data) => { if (mine === ticket.current) setState({ data, error: null, loading: false }); },
      (e) => { if (mine === ticket.current) setState({ data: undefined, error: toApiError(e), loading: false }); },
    );
  }, []);

  useEffect(() => {
    run();
    return () => { ticket.current++; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const setData = useCallback((updater: (prev: T | undefined) => T | undefined) => {
    setState((s) => ({ ...s, data: updater(s.data) }));
  }, []);

  return { ...state, reload: run, setData };
}
