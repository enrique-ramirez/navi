import { useCallback, useSyncExternalStore } from "react";

const listeners = new Set<() => void>();
const held = new Map<string, unknown>();

function read<T>(key: string, fallback: T): T {
	try {
		const stored = localStorage.getItem(key);
		return stored === null ? fallback : (JSON.parse(stored) as T);
	} catch {
		return fallback;
	}
}

export function readStoredState<T>(key: string, fallback: T): T {
	if (!held.has(key)) held.set(key, read(key, fallback));
	return held.get(key) as T;
}

export function writeStoredState<T>(key: string, value: T): void {
	held.set(key, value);
	try {
		localStorage.setItem(key, JSON.stringify(value));
	} catch {
		// Private mode or a full quota: the pick lasts until the tab closes.
	}
	for (const listener of listeners) listener();
}

const subscribe = (listener: () => void) => {
	listeners.add(listener);
	return () => {
		listeners.delete(listener);
	};
};

export function useStoredState<T>(
	key: string,
	fallback: T,
): [T, (next: T) => void] {
	const value = useSyncExternalStore(subscribe, () =>
		readStoredState(key, fallback),
	);
	const update = useCallback((next: T) => writeStoredState(key, next), [key]);
	return [value, update];
}
