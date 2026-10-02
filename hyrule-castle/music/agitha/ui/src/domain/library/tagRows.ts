import {
	changeOf,
	common,
	type DiffRow,
	present,
	type Side,
} from "@/domain/album/diff";
import { lockedKind, PICTURE } from "@/domain/album/tagModel";
import type { DraftEdit, TagNames, TrackRef } from "@/shared/api/types";
import {
	applyEdits,
	changedTags,
	displayKey,
	isFormatsOwnKey,
	type PanelTrack,
	rawKeyOf,
} from "./shared";

/**
 * The tags that say what the album is, not what one track of it is. They are
 * read and set over the whole album even where its tracks disagree on them.
 */
export const ALBUM_TAGS = [
	"Album",
	"Album artist",
	"Album artist sort order",
	"Date",
	"Original release date",
	"Original year",
	"Genre",
	"Label",
	"Catalogue number",
	"Barcode",
	"ASIN",
	"Release country",
	"Release type",
	"Release status",
	"Media",
	"Script",
	"Compilation",
];

const valuesOf = (track: PanelTrack, key: string, names: TagNames) => {
	const raw = rawKeyOf(track, key, names);
	return present(raw === null ? undefined : track.tags[raw]);
};

/**
 * One row per tag of the tracks given, as the tag table takes them: what the
 * files hold, and what they hold once the edits are laid. A key of `extra` gets
 * a row though no track carries it, so a tag can be typed in.
 */
export function tagRows(
	tracks: PanelTrack[],
	edits: DraftEdit[],
	names: TagNames,
	extra: string[] = [],
): DiffRow[] {
	const after = applyEdits(tracks, edits, names);
	const changed = changedTags(tracks, edits, names);
	const keys = new Set<string>(extra);
	for (const track of [...tracks, ...after])
		for (const raw of Object.keys(track.tags))
			keys.add(displayKey(track, raw, names));

	const first = tracks[0];
	const order = first ? Object.values(names[first.family] ?? {}) : [];
	const rank = (key: string) => {
		const at = order.indexOf(key);
		return at === -1 ? order.length : at;
	};

	const rows: DiffRow[] = [];
	for (const key of keys) {
		if (PICTURE.test(key)) continue;
		const now: Side = common(
			tracks.map((track) => valuesOf(track, key, names)),
		);
		const next: Side = common(
			after.map((track) => valuesOf(track, key, names)),
		);
		const edited = changed.has(key);
		if (now === null && next === null && !edited && !extra.includes(key))
			continue;
		// The server names the keys it will not change; the page only says which kind each is.
		const fixed = tracks.find((track) => {
			const raw = rawKeyOf(track, key, names);
			return raw !== null && track.readonly.includes(raw);
		});
		const fixedRaw = fixed ? (rawKeyOf(fixed, key, names) ?? key) : key;
		rows.push({
			key,
			now,
			next,
			change: changeOf(now, next),
			locked: fixed
				? (lockedKind(fixedRaw, fixed.tags[fixedRaw] ?? []) ?? "fixed")
				: null,
			edited,
			removedBy: [],
		});
	}
	return rows.sort(
		(a, b) =>
			Number(a.locked !== null) - Number(b.locked !== null) ||
			rank(a.key) - rank(b.key) ||
			a.key.localeCompare(b.key),
	);
}

const carries = (track: PanelTrack, key: string, names: TagNames) => {
	const raw = rawKeyOf(track, key, names);
	return raw !== null && Object.hasOwn(track.tags, raw);
};

/**
 * The tracks of `chosen` an edit of `key` names. A key no format's table knows
 * is one format's own, and the server refuses it over tracks of several: its
 * edit names only the tracks that carry it.
 */
export function reachOf(
	chosen: PanelTrack[],
	key: string,
	names: TagNames,
): TrackRef[] {
	const reached = isFormatsOwnKey(key, names)
		? chosen.filter((track) => carries(track, key, names))
		: chosen;
	return (reached.length > 0 ? reached : chosen).map(({ album, path }) => ({
		album,
		path,
	}));
}

/** The edits with every change of `key` on the tracks named taken out; an edit left changing nothing is dropped. */
export function withoutKey(
	edits: DraftEdit[],
	refs: TrackRef[],
	key: string,
): DraftEdit[] {
	const named = (ref: TrackRef) =>
		refs.some((each) => each.album === ref.album && each.path === ref.path);
	const drop = <T>(map: Record<string, T>) =>
		Object.fromEntries(Object.entries(map).filter(([each]) => each !== key));
	const only = <T>(map: Record<string, T>) =>
		Object.fromEntries(Object.entries(map).filter(([each]) => each === key));
	const changes = (edit: DraftEdit) =>
		Object.keys(edit.set).length +
			Object.keys(edit.add).length +
			Object.keys(edit.remove).length >
		0;

	return edits.flatMap((edit) => {
		const touches = key in edit.set || key in edit.add || key in edit.remove;
		if (!touches || !edit.tracks.some(named)) return [edit];
		const rest: DraftEdit = {
			tracks: edit.tracks,
			set: drop(edit.set),
			add: drop(edit.add),
			remove: drop(edit.remove),
		};
		// The tracks not named keep the change.
		const others: DraftEdit = {
			tracks: edit.tracks.filter((ref) => !named(ref)),
			set: only(edit.set),
			add: only(edit.add),
			remove: only(edit.remove),
		};
		return [rest, others].filter(
			(each) => each.tracks.length > 0 && changes(each),
		);
	});
}
