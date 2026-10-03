import type {
	DraftEdit,
	Family,
	LibraryTrack,
	TagNames,
	TrackRef,
} from "@/shared/api/types";

export type PanelTrack = LibraryTrack & { album: string };

export const GENRE = "Genre";

export interface SharedTag {
	/** The readable name where the track's own family has one, else the raw key. */
	key: string;
	/** By count, highest first, then in the order the tracks first showed them. */
	values: { value: string; count: number }[];
	/** How many tracks were given. */
	of: number;
	/** Some given track lists the key among those the files refuse. */
	readonly: boolean;
}

/** The key as the track's own format names it for a person. */
export function displayKey(track: PanelTrack, raw: string, names: TagNames) {
	return names[track.family]?.[raw] ?? raw;
}

export const isTrack = (track: PanelTrack, ref: TrackRef) =>
	track.album === ref.album && track.path === ref.path;

// A Vorbis field name has no case and the server reads it folded; an ID3 frame, an MP4 atom and an ASF name keep theirs.
const foldFor = (family: Family, key: string) =>
	family === "vorbis" ? key.toLowerCase() : key;

const inTableOf = (family: Family, key: string, names: TagNames) => {
	const table = names[family] ?? {};
	return (
		Object.hasOwn(table, foldFor(family, key)) ||
		Object.values(table).includes(key)
	);
};

/** Whether no format's table knows the key, by raw key or readable name: only the format that holds it can say what it means, and the server refuses an edit of it over tracks of more than one format. */
export const isFormatsOwnKey = (key: string, names: TagNames) =>
	!(Object.keys(names) as Family[]).some((family) =>
		inTableOf(family, key, names),
	);

/**
 * The raw key of this track that an edit's `key` means, or `null` where the
 * key belongs to another format alone. A readable name lands on each track's
 * own key; a format's own key (`TCON`, `genre`) lands on that format's tracks,
 * a Vorbis one whatever its case.
 */
export function rawKeyOf(track: PanelTrack, key: string, names: TagNames) {
	const own = names[track.family] ?? {};
	const typed = foldFor(track.family, key);
	if (Object.hasOwn(own, typed)) return typed;
	const named = Object.keys(own).filter((raw) => own[raw] === key);
	if (named.length > 0)
		return named.find((raw) => Object.hasOwn(track.tags, raw)) ?? named[0];
	if (Object.hasOwn(track.tags, typed)) return typed;
	const elsewhere = (Object.keys(names) as Family[]).some(
		(family) => family !== track.family && inTableOf(family, key, names),
	);
	return elsewhere ? null : typed;
}

export const carries = (track: PanelTrack, key: string, names: TagNames) => {
	const raw = rawKeyOf(track, key, names);
	return raw !== null && Object.hasOwn(track.tags, raw);
};

/** Rows in the order of the first track's readable names, then the other keys alphabetically. */
export function sortRows(
	rows: SharedTag[],
	tracks: PanelTrack[],
	names: TagNames,
) {
	const first = tracks[0];
	const order = first ? Object.values(names[first.family] ?? {}) : [];
	const rank = (key: string) => {
		const at = order.indexOf(key);
		return at === -1 ? Number.POSITIVE_INFINITY : at;
	};
	return [...rows].sort(
		(a, b) =>
			rank(a.key) - rank(b.key) ||
			(rank(a.key) === Number.POSITIVE_INFINITY
				? a.key.localeCompare(b.key)
				: 0),
	);
}

export function sharedTags(tracks: PanelTrack[], names: TagNames): SharedTag[] {
	const rows = new Map<string, SharedTag>();
	for (const track of tracks) {
		for (const [raw, values] of Object.entries(track.tags)) {
			const key = displayKey(track, raw, names);
			let row = rows.get(key);
			if (!row) {
				row = { key, values: [], of: tracks.length, readonly: false };
				rows.set(key, row);
			}
			if (track.readonly.includes(raw)) row.readonly = true;
			for (const value of new Set(values ?? [])) {
				const seen = row.values.find((each) => each.value === value);
				if (seen) seen.count += 1;
				else row.values.push({ value, count: 1 });
			}
		}
	}
	for (const row of rows.values()) row.values.sort((a, b) => b.count - a.count);
	return sortRows([...rows.values()], tracks, names);
}

/** The tracks with the edits applied in order; the tracks given are not touched. */
export function applyEdits(
	tracks: PanelTrack[],
	edits: DraftEdit[],
	names: TagNames,
): PanelTrack[] {
	const after = tracks.map((track) => ({ ...track, tags: { ...track.tags } }));
	for (const edit of edits) {
		for (const track of after) {
			if (!edit.tracks.some((ref) => isTrack(track, ref))) continue;
			const tags = track.tags;
			for (const [key, values] of Object.entries(edit.set)) {
				const raw = rawKeyOf(track, key, names);
				if (raw === null) continue;
				if (values === null || values.length === 0) delete tags[raw];
				else tags[raw] = [...values];
			}
			for (const [key, values] of Object.entries(edit.add)) {
				const raw = rawKeyOf(track, key, names);
				if (raw === null) continue;
				const have = tags[raw] ?? [];
				const fresh = values.filter(
					(value, at) => !have.includes(value) && values.indexOf(value) === at,
				);
				if (fresh.length > 0) tags[raw] = [...have, ...fresh];
			}
			for (const [key, values] of Object.entries(edit.remove)) {
				const raw = rawKeyOf(track, key, names);
				if (raw === null || tags[raw] === undefined) continue;
				const left = (tags[raw] ?? []).filter(
					(value) => !values.includes(value),
				);
				if (left.length === 0) delete tags[raw];
				else tags[raw] = left;
			}
		}
	}
	return after;
}

/** The rows an edit names on the tracks given, as `sharedTags` keys them. */
export function changedTags(
	tracks: PanelTrack[],
	edits: DraftEdit[],
	names: TagNames,
): Set<string> {
	const changed = new Set<string>();
	for (const edit of edits) {
		const keys = [
			...Object.keys(edit.set),
			...Object.keys(edit.add),
			...Object.keys(edit.remove),
		];
		for (const track of tracks) {
			if (!edit.tracks.some((ref) => isTrack(track, ref))) continue;
			for (const key of keys) {
				const raw = rawKeyOf(track, key, names);
				if (raw !== null) changed.add(displayKey(track, raw, names));
			}
		}
	}
	return changed;
}

/**
 * The rows of the selected tracks with the edits applied, plus a row for each
 * changed tag the edits left on none of them, so a removal stays on screen.
 */
export function panelRows(
	chosen: PanelTrack[],
	now: PanelTrack[],
	changed: Set<string>,
	names: TagNames,
): SharedTag[] {
	const rows = sharedTags(now, names);
	const before = sharedTags(chosen, names);
	for (const key of changed) {
		if (rows.some((row) => row.key === key)) continue;
		rows.push({
			key,
			values: [],
			of: chosen.length,
			readonly: before.find((row) => row.key === key)?.readonly ?? false,
		});
	}
	return sortRows(rows, chosen, names);
}
