import type { AlbumView, Family, PlanFile } from "@/shared/api/types";
import { familyOf, genreKeyOf } from "./albumTags";

const BYTES = /\((\d+) bytes\)\s*$/;

/** The byte count a binary frame's value carries, or `undefined`. */
export const bytesOf = (value: string) => BYTES.exec(value)?.[1];

export type Locked = "id" | "rating" | "binary";

// The tags the owner cannot change: the six MusicBrainz IDs (they come from the release),
// ratings (the library's rule) and binary frames.
export function lockedKind(key: string, values: string[]): Locked | null {
	const compact = key.toLowerCase().replace(/[^a-z0-9]/g, "");
	if (
		compact.includes("musicbrainz") &&
		(compact.endsWith("id") || key.startsWith("UFID:"))
	)
		return "id";
	if (key.startsWith("POPM") || compact.includes("rating")) return "rating";
	if (
		/^(APIC|covr|METADATA_BLOCK_PICTURE|WM\/Picture|GEOB|PRIV)/.test(key) ||
		values.some((value) => BYTES.test(value))
	)
		return "binary";
	return null;
}

interface Row {
	key: string;
	values: string[];
}

export interface Model {
	rows: Row[];
	locked: { key: string; kind: Locked; value: string }[];
	differing: string[];
	/** `null` where the tracks disagree on the genres. */
	genres: string[] | null;
	mixed: boolean;
	family: Family;
}

const joined = (values: string[] | undefined) => (values ?? []).join("\u0000");

// What the editor starts from: the written tags of the track, or of every track where they agree,
// with the unsent edits laid over them.
export function modelOf(
	view: AlbumView,
	position: string | "all",
	edits: Record<string, string[] | null>,
): Model {
	const every = view.preview?.files ?? [];
	const all = position === "all";
	const files: PlanFile[] = all
		? every
		: every.filter((file) => file.position === position);
	const first = files[0];
	const family = first ? familyOf(view, first) : "id3";
	const mixed = all && files.some((file) => familyOf(view, file) !== family);
	const model: Model = {
		rows: [],
		locked: [],
		differing: [],
		genres: [],
		mixed,
		family,
	};
	if (!first || mixed) return model;

	const genreKey = genreKeyOf(family);
	const agree = (key: string) =>
		files.every(
			(file) =>
				key in file.after === key in first.after &&
				joined(file.after[key]) === joined(first.after[key]),
		);

	for (const key of Object.keys(first.after)) {
		const values = first.after[key] ?? [];
		if (key === genreKey) continue;
		const kind = lockedKind(key, values);
		if (kind) {
			model.locked.push({ key, kind, value: values.join(" / ") });
		} else if (!agree(key)) {
			model.differing.push(key);
		} else if (edits[key] !== null) {
			model.rows.push({ key, values: edits[key] ?? values });
		}
	}
	for (const [key, values] of Object.entries(first.before)) {
		const kind = lockedKind(key, values);
		if (kind && !(key in first.after))
			model.locked.push({ key, kind, value: values.join(" / ") });
	}
	// Tags the owner added by key and has not sent yet. On a format whose keys are not
	// lower case, a lower-case key is a neutral field of an earlier decision, already in `after`.
	for (const [key, values] of Object.entries(edits)) {
		const neutral = family !== "vorbis" && /^[a-z_]+$/.test(key);
		if (values && !(key in first.after) && !neutral && key !== "genre")
			model.rows.push({ key, values });
	}

	model.genres = agree(genreKey)
		? (edits.genre ?? first.after[genreKey] ?? [])
		: null;
	return model;
}
