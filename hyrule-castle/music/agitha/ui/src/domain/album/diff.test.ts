import { describe, expect, it } from "vitest";

import type { AlbumView, Edits } from "@/shared/api/types";
import { albumView } from "@/test/albumView";

import { type DiffRow, diffOf, editKeyOf } from "./diff";

const ALL = ["1-1", "1-2", "1-3"];

// The same edit on every track, as an album-wide edit is sent.
const onAll = (key: string, values: string[] | null): Edits =>
	Object.fromEntries(ALL.map((position) => [position, { [key]: values }]));

const rowOf = (rows: DiffRow[], key: string) => {
	const row = rows.find((each) => each.key === key);
	if (!row) throw new Error(`no row for ${key}`);
	return row;
};

// The picture a file carries, as the engine lists a binary frame.
function withPicture(view: AlbumView): AlbumView {
	for (const file of view.preview?.files ?? [])
		file.before["APIC:"] = ["APIC: image/jpeg (25535 bytes)"];
	return view;
}

describe("diffOf", () => {
	it("has no rows for an album with no preview", () => {
		expect(diffOf(albumView({ preview: null }), {})).toEqual({
			album: [],
			tracks: {},
		});
	});

	it("puts a tag under the album when every track writes the same value, and under the tracks otherwise", () => {
		const diff = diffOf(albumView(), {});
		const album = diff.album.map((row) => row.key);

		expect(album).toEqual(expect.arrayContaining(["TALB", "TDRC", "TCON"]));
		expect(album).not.toContain("TIT2");
		expect(album).not.toContain("TRCK");
		expect(Object.keys(diff.tracks)).toEqual(ALL);
		expect(diff.tracks["1-1"]?.map((row) => row.key)).toEqual([
			"TIT2",
			"TRCK",
			"TXXX:MusicBrainz Release Track Id",
			"UFID:http://musicbrainz.org",
		]);
	});

	it.each<[string, Partial<DiffRow>]>([
		["TALB", { now: ["Clean Album"], next: ["Clean Album"], change: "same" }],
		["TDRC", { now: ["1989"], next: ["2010-05-24"], change: "changed" }],
		["TCON", { now: null, next: ["rock"], change: "added" }],
		[
			"TXXX:MusicBrainz Album Id",
			{ change: "same", locked: "id", edited: false },
		],
	])("reads the album's %s as it is and as it will be", (key, expected) => {
		expect(rowOf(diffOf(albumView(), {}).album, key)).toMatchObject(expected);
	});

	it("reads a track's own tag against that track alone", () => {
		const one = diffOf(albumView(), {}).tracks["1-1"] ?? [];

		expect(rowOf(one, "TIT2")).toMatchObject({
			now: ["one"],
			next: ["One"],
			change: "changed",
		});
		expect(rowOf(one, "UFID:http://musicbrainz.org")).toMatchObject({
			now: null,
			change: "added",
			locked: "id",
		});
	});

	it("says a side differs where the tracks disagree on it", () => {
		const view = albumView();
		const files = view.preview?.files ?? [];
		files.forEach((file, index) => {
			file.before.TDRC = [`198${index}`];
		});

		expect(rowOf(diffOf(view, {}).album, "TDRC")).toMatchObject({
			now: "differs",
			next: ["2010-05-24"],
			change: "changed",
		});
	});

	it("shows each track its own value where the tracks disagree now and the album's row cannot", () => {
		const view = albumView();
		const files = view.preview?.files ?? [];
		files.forEach((file, index) => {
			file.before["TXXX:MOOD"] = index === 0 ? ["calm"] : [];
		});
		const diff = diffOf(view, {});

		expect(rowOf(diff.album, "TXXX:MOOD")).toMatchObject({
			now: "differs",
			next: null,
			change: "removed",
		});
		expect(rowOf(diff.tracks["1-1"] ?? [], "TXXX:MOOD")).toMatchObject({
			now: ["calm"],
			next: null,
			change: "removed",
		});
		expect(diff.tracks["1-2"]?.map((row) => row.key)).not.toContain(
			"TXXX:MOOD",
		);
	});

	it("orders rows by the family's names, then the unknown keys, and the locked ones last", () => {
		const rows = diffOf(albumView(), {}).album;
		const keys = rows.map((row) => row.key);

		// The names list TIT2, TALB, TPE1, TPE2, TRCK, TPOS, TDRC, TCON.
		expect(keys.slice(0, 6)).toEqual([
			"TALB",
			"TPE1",
			"TPE2",
			"TPOS",
			"TDRC",
			"TCON",
		]);
		expect(keys.slice(6, 9)).toEqual(["TDOR", "TMED", "TPUB"]);
		const firstLocked = rows.findIndex((row) => row.locked !== null);
		expect(firstLocked).toBeGreaterThan(6);
		expect(rows.slice(firstLocked).map((row) => row.locked)).toEqual(
			Array(rows.length - firstLocked).fill("id"),
		);
	});

	it("leaves pictures out", () => {
		const diff = diffOf(withPicture(albumView()), {});
		const every = [...diff.album, ...Object.values(diff.tracks).flat()];

		expect(every.some((row) => row.key.startsWith("APIC"))).toBe(false);
	});

	it.each<[string, Edits, string, Partial<DiffRow>]>([
		[
			"a value set on every track",
			onAll("TALB", ["Other Album"]),
			"TALB",
			{ next: ["Other Album"], change: "changed", edited: true },
		],
		[
			"a removal on every track",
			onAll("TDRC", null),
			"TDRC",
			{ now: ["1989"], next: null, change: "removed", edited: true },
		],
		[
			"a genre edited under its neutral name",
			onAll("genre", ["jazz", "blues"]),
			"TCON",
			{ next: ["jazz", "blues"], change: "added", edited: true },
		],
		[
			"a tag the owner adds",
			onAll("TXXX:MOOD", ["calm"]),
			"TXXX:MOOD",
			{ now: null, next: ["calm"], change: "added", edited: true },
		],
	])("shows %s as the new value", (_, edits, key, expected) => {
		expect(rowOf(diffOf(albumView(), edits).album, key)).toMatchObject(
			expected,
		);
	});

	it("keeps a row the owner removes where the files never had it, so it can be undone", () => {
		const diff = diffOf(albumView(), onAll("genre", null));

		expect(rowOf(diff.album, "TCON")).toMatchObject({
			now: null,
			next: null,
			edited: true,
		});
	});

	it("moves a tag to the tracks once an edit makes one track differ", () => {
		const diff = diffOf(albumView(), { "1-2": { TALB: ["Bonus"] } });

		expect(diff.album.some((row) => row.key === "TALB")).toBe(false);
		expect(rowOf(diff.tracks["1-2"] ?? [], "TALB")).toMatchObject({
			next: ["Bonus"],
			change: "changed",
			edited: true,
		});
		expect(rowOf(diff.tracks["1-1"] ?? [], "TALB")).toMatchObject({
			change: "same",
			edited: false,
		});
	});

	it("adds no row for a neutral key the plan already writes under its own name", () => {
		const diff = diffOf(albumView(), onAll("comment", ["from the owner"]));

		expect(diff.album.some((row) => row.key === "comment")).toBe(false);
	});

	it("names the engine rules that remove a tag, once each", () => {
		const view = albumView();
		for (const file of view.preview?.files ?? [])
			file.before["TXXX:JUNK"] = ["x"];
		view.preview!.residue = view.preview!.files.map((file) => ({
			file: file.source,
			key: "TXXX:JUNK",
			value: null,
			rule: "unknown frame",
		}));

		expect(rowOf(diffOf(view, {}).album, "TXXX:JUNK")).toMatchObject({
			next: null,
			change: "removed",
			removedBy: ["unknown frame"],
		});
	});
});

describe("editKeyOf", () => {
	it.each([
		["TCON", "genre"],
		["TALB", "TALB"],
		["TXXX:MOOD", "TXXX:MOOD"],
	])("edits %s as %s on an ID3 album", (key, expected) => {
		expect(editKeyOf(albumView(), key)).toBe(expected);
	});

	it("keeps the key of an album with no preview", () => {
		expect(editKeyOf(albumView({ preview: null }), "TCON")).toBe("TCON");
	});
});
