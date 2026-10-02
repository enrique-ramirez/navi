import { isTrack, type PanelTrack, rawKeyOf } from "@/domain/library/shared";
import type {
	CoverUpload,
	Draft,
	DraftEdit,
	TagNames,
} from "@/shared/api/types";

/** What the page has changed and not yet saved. */
export interface PageDraft {
	edits: DraftEdit[];
	swaps: [string, string][];
	cover: CoverUpload | null;
}

export const emptyDraft: PageDraft = { edits: [], swaps: [], cover: null };

export const isEmpty = (draft: PageDraft) =>
	draft.edits.length === 0 && draft.swaps.length === 0 && draft.cover === null;

/**
 * The draft as the server takes it. Each track a change touches is listed
 * once, with what the album route served for it, and `seen` holds the values
 * it served under each tag an edit names, never what the edits leave.
 */
export function toWire(
	draft: PageDraft,
	tracks: PanelTrack[],
	names: TagNames,
	batch: boolean,
): Draft {
	const swapped = draft.swaps.flat();
	const touched = tracks.filter(
		(track) =>
			draft.cover !== null ||
			swapped.includes(track.path) ||
			draft.edits.some((edit) =>
				edit.tracks.some((ref) => isTrack(track, ref)),
			),
	);
	return {
		tracks: touched.map((track) => {
			const seen: Draft["tracks"][number]["seen"] = {};
			for (const edit of draft.edits) {
				if (!edit.tracks.some((ref) => isTrack(track, ref))) continue;
				for (const key of [
					...Object.keys(edit.set),
					...Object.keys(edit.add),
					...Object.keys(edit.remove),
				]) {
					const raw = rawKeyOf(track, key, names);
					seen[key] = (raw === null ? undefined : track.tags[raw]) ?? null;
				}
			}
			return {
				album: track.album,
				path: track.path,
				loaded: track.loaded,
				seen,
			};
		}),
		edits: draft.edits,
		swaps: draft.swaps,
		cover: draft.cover?.cover ?? null,
		batch,
	};
}

/**
 * The draft with a pair of tracks swapped, or with that pair taken out again
 * where it is already there. The server refuses two pairs that share a track,
 * so a pair sharing one with the new pair gives way to it.
 */
export function withSwap(draft: PageDraft, pair: [string, string]): PageDraft {
	const [a, b] = pair;
	const same = (swap: [string, string]) => swap[0] === a && swap[1] === b;
	if (draft.swaps.some(same))
		return { ...draft, swaps: draft.swaps.filter((swap) => !same(swap)) };
	const kept = draft.swaps.filter(
		(swap) => !swap.some((path) => path === a || path === b),
	);
	return { ...draft, swaps: [...kept, pair] };
}
