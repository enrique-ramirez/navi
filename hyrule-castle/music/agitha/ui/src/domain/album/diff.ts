import type { AlbumView, Edits, PlanFile } from "@/shared/api/types";
import type { Change, Side, TagRow } from "@/shared/ui/tagRow";
import { familyOf } from "./albumTags";
import { GENRE, type Neutral, neutralFor } from "./neutral";
import { lockedKind, PICTURE } from "./tagModel";

export type { Change, Side };
export type DiffRow = TagRow;

export const present = (values: string[] | undefined) =>
	values && values.length > 0 ? values : null;

const joined = (side: Side) =>
	side === null
		? "\u0001"
		: side === "differs"
			? "\u0002"
			: side.join("\u0000");

export function common(sides: (string[] | null)[]): Side {
	const first = sides[0] ?? null;
	return sides.every((side) => joined(side) === joined(first))
		? first
		: "differs";
}

function editOf(
	edits: Edits,
	file: PlanFile,
	key: string,
	neutral: (file: PlanFile) => Neutral,
): string[] | null | undefined {
	const own = edits[file.position] ?? {};
	if (key in own) return own[key] ?? null;
	const name = neutral(file)[key];
	if (name !== undefined && name in own) return own[name] ?? null;
	return undefined;
}

function nextOf(
	edits: Edits,
	file: PlanFile,
	key: string,
	neutral: (file: PlanFile) => Neutral,
): string[] | null {
	const edit = editOf(edits, file, key, neutral);
	return edit === undefined ? present(file.after[key]) : present(edit ?? []);
}

export function changeOf(now: Side, next: Side): Change {
	if (joined(now) === joined(next)) return "same";
	if (now === null) return "added";
	if (next === null) return "removed";
	return "changed";
}

export interface Diff {
	album: DiffRow[];
	tracks: Record<string, DiffRow[]>;
}

// Rows follow the order of `names`, which is Picard's.
export function diffOf(view: AlbumView, edits: Edits): Diff {
	const files = view.preview?.files ?? [];
	const first = files[0];
	if (!first) return { album: [], tracks: {} };
	const family = familyOf(view, first);
	// By each file's own family: a plan may hold a FLAC before MP3s.
	const neutralKeys = (file: PlanFile) => neutralFor(familyOf(view, file));
	const residue = view.preview?.residue ?? [];

	const keys: string[] = [];
	const add = (key: string) => {
		if (!keys.includes(key) && !PICTURE.test(key)) keys.push(key);
	};
	for (const file of files) {
		for (const key of Object.keys(file.before)) add(key);
		for (const key of Object.keys(file.after)) add(key);
		// A lower-case key on a family whose keys are not is a neutral field, already in `after`.
		const lowerIsNeutral = familyOf(view, file) !== "vorbis";
		for (const key of Object.keys(edits[file.position] ?? {}))
			if (key !== GENRE && !(lowerIsNeutral && /^[a-z_]+$/.test(key))) add(key);
	}

	const names = Object.keys(view.names[family] ?? {});
	const rank = (key: string) => {
		const at = names.indexOf(key);
		return at === -1 ? names.length : at;
	};

	const rowFor = (key: string, of: PlanFile[]): DiffRow | null => {
		const now = common(of.map((file) => present(file.before[key])));
		const next = common(
			of.map((file) => nextOf(edits, file, key, neutralKeys)),
		);
		const edited = of.some(
			(file) => editOf(edits, file, key, neutralKeys) !== undefined,
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

	// The neutral name is no tag of a file whose own key is another: its edit shows on that row.
	const hidden = (file: PlanFile, key: string) =>
		familyOf(view, file) !== "vorbis" &&
		Object.values(neutralFor(familyOf(view, file))).includes(key);

	const shared = (key: string) =>
		!files.some((file) => hidden(file, key)) &&
		common(files.map((file) => nextOf(edits, file, key, neutralKeys))) !==
			"differs";

	// The album's row can only say the files differ now, so each track shows its own value as well.
	const differsNow = (key: string) =>
		common(files.map((file) => present(file.before[key]))) === "differs";

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
				.filter(
					(key) => (!shared(key) || differsNow(key)) && !hidden(file, key),
				)
				.map((key) => rowFor(key, [file]))
				.filter((row) => row !== null),
		);
	return { album, tracks };
}

export function editKeyOf(view: AlbumView, key: string): string {
	for (const file of view.preview?.files ?? []) {
		const name = neutralFor(familyOf(view, file))[key];
		if (name !== undefined) return name;
	}
	return key;
}
