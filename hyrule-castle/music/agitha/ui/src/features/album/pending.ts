import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useMemo, useSyncExternalStore } from "react";

import type {
	AcceptDecision,
	AlbumView,
	Decision,
	Edits,
	GameChoice,
	RepointDecision,
} from "@/shared/api/types";

interface Store {
	draft: Decision | null;
	version: number;
	listeners: Set<() => void>;
}

const stores = new WeakMap<QueryClient, Map<string, Store>>();

function storeFor(client: QueryClient, view: AlbumView): Store {
	let byAlbum = stores.get(client);
	if (!byAlbum) {
		byAlbum = new Map();
		stores.set(client, byAlbum);
	}
	const key = `${view.drop}/${view.n}`;
	let store = byAlbum.get(key);
	if (!store) {
		store = { draft: null, version: 0, listeners: new Set() };
		byAlbum.set(key, store);
	}
	return store;
}

function notify(store: Store) {
	store.version += 1;
	for (const listener of store.listeners) listener();
}

function accept(view: AlbumView, over: Partial<AcceptDecision> = {}) {
	return {
		action: "accept",
		release_id: view.preview?.release_id ?? "",
		edits: {},
		game: null,
		cover: null,
		...over,
	} satisfies AcceptDecision;
}

function normalize(decision: Decision): Decision {
	if (decision.action === "repoint") return decision;
	const edits: Edits = {};
	for (const position of Object.keys(decision.edits).sort()) {
		const own = decision.edits[position] ?? {};
		if (Object.keys(own).length === 0) continue;
		edits[position] = Object.fromEntries(
			Object.keys(own)
				.sort()
				.map((key) => [key, own[key] ?? null]),
		);
	}
	return {
		action: "accept",
		release_id: decision.release_id,
		edits,
		game: decision.game ?? null,
		cover: decision.cover ?? null,
	};
}

const startOf = (view: AlbumView): Decision =>
	view.decision?.action === "accept" ? normalize(view.decision) : accept(view);

const same = (a: Decision, b: Decision) =>
	JSON.stringify(normalize(a)) === JSON.stringify(normalize(b));

// A repoint carries none of an accept's keys; naming them lets a reader take `draft.edits` without narrowing first.
export type Draft =
	| AcceptDecision
	| (RepointDecision & {
			release_id?: undefined;
			edits?: undefined;
			game?: undefined;
			cover?: undefined;
	  });

export interface Pending {
	draft: Draft;
	dirty: boolean;
	setEdit: (
		position: string | "all",
		key: string,
		values: string[] | null,
	) => void;
	removeEdit: (position: string | "all", key: string) => void;
	setGame: (game: GameChoice | null) => void;
	setCandidate: (releaseId: string) => void;
	setRepoint: (release: string | null) => void;
	setCover: (path: string | null) => void;
	reset: () => void;
}

export function usePending(view: AlbumView): Pending {
	const client = useQueryClient();
	const store = storeFor(client, view);
	useSyncExternalStore(
		(listener) => {
			store.listeners.add(listener);
			return () => {
				store.listeners.delete(listener);
			};
		},
		() => store.version,
	);

	const start = useMemo(() => startOf(view), [view]);
	const draft = store.draft ?? start;
	const baseline = view.decision ? normalize(view.decision) : start;

	const positions = view.preview?.files.map((file) => file.position) ?? [];

	function change(next: (current: Decision) => Decision) {
		store.draft = next(store.draft ?? start);
		notify(store);
	}

	function onAccept(edit: (current: AcceptDecision) => AcceptDecision) {
		change((current) =>
			current.action === "accept" ? edit(current) : current,
		);
	}

	const targets = (position: string | "all") =>
		position === "all" ? positions : [position];

	return {
		draft,
		dirty: !same(draft, baseline),
		setEdit: (position, key, values) =>
			onAccept((current) => {
				const edits: Edits = { ...current.edits };
				for (const each of targets(position))
					edits[each] = { ...edits[each], [key]: values };
				return { ...current, edits };
			}),
		removeEdit: (position, key) =>
			onAccept((current) => {
				const edits: Edits = { ...current.edits };
				for (const each of targets(position)) {
					const { [key]: _gone, ...rest } = edits[each] ?? {};
					if (Object.keys(rest).length > 0) edits[each] = rest;
					else delete edits[each];
				}
				return { ...current, edits };
			}),
		setGame: (game) => onAccept((current) => ({ ...current, game })),
		setCandidate: (releaseId) =>
			change((current) =>
				current.action === "accept"
					? { ...current, release_id: releaseId }
					: accept(view, { release_id: releaseId }),
			),
		setRepoint: (release) =>
			change((current) =>
				release !== null
					? { action: "repoint", release }
					: current.action === "accept"
						? current
						: startOf(view),
			),
		setCover: (path) => onAccept((current) => ({ ...current, cover: path })),
		reset: () => {
			store.draft = null;
			notify(store);
		},
	};
}
