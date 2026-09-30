import type { AlbumView, Edits, PlanFile } from "@/shared/api/types";
import { familyOf, genreKeyOf } from "./albumTags";
import { type Locked, lockedKind } from "./tagModel";

/** A side of a row: the values, `null` where the tag is absent, `"differs"` where the tracks disagree. */
export type Side = string[] | null | "differs";

export type Change = "same" | "changed" | "added" | "removed";

export interface DiffRow {
	/** The raw key of the file's family (`TALB`, `album`, `©alb`). */
	key: string;
	now: Side;
	next: Side;
	change: Change;
	locked: Locked | null;
	/** Whether an unsent edit of the owner's sets this row. */
	edited: boolean;
	/** The engine rules that removed the tag, where it goes. */
	removedBy: string[];
}

// Pictures show in the cover card, not as rows.
const PICTURE = /^(APIC|covr|METADATA_BLOCK_PICTURE|WM\/Picture)/;

const present = (values: string[] | undefined) =>
	values && values.length > 0 ? values : null;

const joined = (side: Side) =>
	side === null
		? "\u0001"
		: side === "differs"
			? "\u0002"
			: side.join("\u0000");

function common(sides: (string[] | null)[]): Side {
	const first = sides[0] ?? null;
	return sides.every((side) => joined(side) === joined(first))
		? first
		: "differs";
}

/**
 * The edit the owner has made to `key` on `file`, `null` for a removal, `undefined` for none.
 * Genres are edited under the neutral name `genre`, whatever the family calls them.
 */
function editOf(
	edits: Edits,
	file: PlanFile,
	key: string,
	genreKey: string,
): string[] | null | undefined {
	const own = edits[file.position] ?? {};
	if (key in own) return own[key] ?? null;
	if (key === genreKey && "genre" in own) return own.genre ?? null;
	return undefined;
}

function nextOf(
	edits: Edits,
	file: PlanFile,
	key: string,
	genreKey: string,
): string[] | null {
	const edit = editOf(edits, file, key, genreKey);
	return edit === undefined ? present(file.after[key]) : present(edit ?? []);
}

function changeOf(now: Side, next: Side): Change {
	if (joined(now) === joined(next)) return "same";
	if (now === null) return "added";
	if (next === null) return "removed";
	return "changed";
}

export interface Diff {
	/** Tags every track shares once written. */
	album: DiffRow[];
	/** Per position, the tags that differ between the tracks. */
	tracks: Record<string, DiffRow[]>;
}

// Every key the tracks have now, will have, or the owner has added, split into the ones every
// track shares once written and the ones that differ between tracks. Rows follow the order of
// `names`, which is Picard's; unknown keys come after, and the locked ones last.
export function diffOf(view: AlbumView, edits: Edits): Diff {
	const files = view.preview?.files ?? [];
	const first = files[0];
	if (!first) return { album: [], tracks: {} };
	const family = familyOf(view, first);
	const genreKey = genreKeyOf(family);
	const neutral = family !== "vorbis";
	const residue = view.preview?.residue ?? [];

	const keys: string[] = [];
	const add = (key: string) => {
		if (!keys.includes(key) && !PICTURE.test(key)) keys.push(key);
	};
	for (const file of files) {
		for (const key of Object.keys(file.before)) add(key);
		for (const key of Object.keys(file.after)) add(key);
		// A lower-case key on a family whose keys are not is a neutral field, already in `after`.
		for (const key of Object.keys(edits[file.position] ?? {}))
			if (key !== "genre" && !(neutral && /^[a-z_]+$/.test(key))) add(key);
	}

	const names = Object.keys(view.names[family] ?? {});
	const rank = (key: string) => {
		const at = names.indexOf(key);
		return at === -1 ? names.length : at;
	};

	const rowFor = (key: string, of: PlanFile[]): DiffRow | null => {
		const now = common(of.map((file) => present(file.before[key])));
		const next = common(of.map((file) => nextOf(edits, file, key, genreKey)));
		const edited = of.some(
			(file) => editOf(edits, file, key, genreKey) !== undefined,
		);
		// A removed tag the files never had keeps its row while the edit stands, so it can be undone.
		if (now === null && next === null && !edited) return null;
		const sample = of.map((file) => file.after[key] ?? file.before[key]);
		const removedBy =
			next === null
				? residue
						.filter(
							(entry) =>
								entry.key === key &&
								of.some((file) => file.source === entry.file),
						)
						.map((entry) => entry.rule)
				: [];
		return {
			key,
			now,
			next,
			change: changeOf(now, next),
			locked: lockedKind(key, sample.find((values) => values) ?? []),
			edited,
			removedBy: [...new Set(removedBy)],
		};
	};

	const order = (rows: DiffRow[]) =>
		rows.sort(
			(a, b) =>
				Number(a.locked !== null) - Number(b.locked !== null) ||
				rank(a.key) - rank(b.key) ||
				a.key.localeCompare(b.key),
		);

	const shared = (key: string) =>
		common(files.map((file) => nextOf(edits, file, key, genreKey))) !==
		"differs";

	const album = order(
		keys
			.filter(shared)
			.map((key) => rowFor(key, files))
			.filter((row) => row !== null),
	);
	const tracks: Record<string, DiffRow[]> = {};
	for (const file of files)
		tracks[file.position] = order(
			keys
				.filter((key) => !shared(key))
				.map((key) => rowFor(key, [file]))
				.filter((row) => row !== null),
		);
	return { album, tracks };
}

/** The genre key of the album's family, which edits name `genre`. */
export function editKeyOf(view: AlbumView, key: string): string {
	const first = view.preview?.files[0];
	if (!first) return key;
	return key === genreKeyOf(familyOf(view, first)) ? "genre" : key;
}
