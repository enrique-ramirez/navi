import { useCallback, useSyncExternalStore } from "react";

const lists = new Map<string, MediaQueryList | null>();

// jsdom has no matchMedia: a page without it never matches, which is the dark theme.
function listFor(query: string): MediaQueryList | null {
	if (!lists.has(query)) {
		lists.set(
			query,
			typeof window.matchMedia === "function" ? window.matchMedia(query) : null,
		);
	}
	return lists.get(query) ?? null;
}

export function useMediaQuery(query: string): boolean {
	const list = listFor(query);
	const subscribe = useCallback(
		(onChange: () => void) => {
			list?.addEventListener("change", onChange);
			return () => list?.removeEventListener("change", onChange);
		},
		[list],
	);
	return useSyncExternalStore(subscribe, () => list?.matches ?? false);
}
