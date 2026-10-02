import { describe, expect, it } from "vitest";

import type { DraftEdit } from "@/shared/api/types";
import {
	albumTracks,
	fixtures,
	refsOf,
	type TrackOfAlbum,
} from "@/test/library";

import type { SharedTag } from "./shared";

// Loaded inside each case: a module that is missing then fails the case that
// asked for it, on its own line, and not the whole file with one import error.
const MODULE = "./shared";
const load = (): Promise<typeof import("./shared")> =>
	import(/* @vite-ignore */ MODULE);

const names = fixtures.album.names;

// Ecliptica as the fixture holds it: two FLACs, then two MP3s. Blank File has
// one genre and a rating, My Land two genres, 8th Commandment one genre, a
// picture, a rating and a ripper frame, and Replica no genre at all.
const BLANK = "01. Blank File.flac";
const LAND = "02. My Land.flac";
const EIGHTH = "03. 8th Commandment.mp3";
const REPLICA = "04. Replica.mp3";

const only = (tracks: TrackOfAlbum[], ...paths: string[]) =>
	paths.map((path) => {
		const track = tracks.find((each) => each.path === path);
		if (!track) throw new Error(`no track ${path}`);
		return track;
	});

const rowOf = (rows: SharedTag[], key: string) => {
	const found = rows.filter((row) => row.key === key);
	if (found.length !== 1)
		throw new Error(`${found.length} rows for ${key}, not one`);
	return found[0] as SharedTag;
};

// Value -> count, whatever order the values come in. A value listed twice is an error.
const counts = (row: SharedTag) => {
	const seen: Record<string, number> = {};
	for (const { value, count } of row.values) {
		if (value in seen) throw new Error(`${row.key} lists ${value} twice`);
		seen[value] = count;
	}
	return seen;
};

const edit = (
	tracks: TrackOfAlbum[],
	change: Partial<Pick<DraftEdit, "set" | "add" | "remove">>,
): DraftEdit => ({
	tracks: refsOf(tracks),
	set: {},
	add: {},
	remove: {},
	...change,
});

const tagsOf = (tracks: TrackOfAlbum[], path: string, album?: string) => {
	const track = tracks.find(
		(each) =>
			each.path === path && (album === undefined || each.album === album),
	);
	if (!track) throw new Error(`no track ${path}`);
	return track.tags;
};

// `names` is how a readable name finds each track's own key, so every call passes it.
async function applying() {
	const { applyEdits } = await load();
	return (tracks: TrackOfAlbum[], edits: DraftEdit[]) =>
		applyEdits(tracks, edits, names);
}

function frozen<T>(value: T): T {
	if (typeof value === "object" && value !== null) {
		for (const part of Object.values(value)) frozen(part);
		Object.freeze(value);
	}
	return value;
}

describe("sharedTags", () => {
	it("has no rows for no tracks", async () => {
		const { sharedTags } = await load();

		expect(sharedTags([], names)).toEqual([]);
	});

	it("puts TCON of an MP3 and genre of a FLAC in one row, under the readable name", async () => {
		const { sharedTags } = await load();
		const rows = sharedTags(only(albumTracks(), BLANK, EIGHTH), names);

		expect(counts(rowOf(rows, "Genre"))).toEqual({ "power metal": 2 });
		expect(rowOf(rows, "Genre").of).toBe(2);
		expect(rows.map((row) => row.key)).not.toContain("genre");
		expect(rows.map((row) => row.key)).not.toContain("TCON");
	});

	it("keeps a tag's own key where its format has no readable name for it", async () => {
		const { sharedTags } = await load();
		const rows = sharedTags(albumTracks(), names);

		expect(counts(rowOf(rows, "TXXX:RIPPER"))).toEqual({ "EAC 0.99": 1 });
		expect(counts(rowOf(rows, "rating"))).toEqual({ "5": 1 });
	});

	it("reads a key by the names of the track's own format alone", async () => {
		const { sharedTags } = await load();
		// `tmpo` is BPM in an MP4. In a FLAC it is a field of that name and nothing more.
		const [flac] = albumTracks();
		flac!.tags.tmpo = ["120"];

		const rows = sharedTags([flac!], names);

		expect(counts(rowOf(rows, "tmpo"))).toEqual({ "120": 1 });
		expect(rows.map((row) => row.key)).not.toContain("BPM");
	});

	it("lists every tag any track carries, once each", async () => {
		const { sharedTags } = await load();
		const keys = sharedTags(albumTracks(), names).map((row) => row.key);

		expect([...keys].sort()).toEqual(
			[
				"APIC:",
				"Album",
				"Album artist",
				"Artist",
				"Date",
				"Disc number",
				"Genre",
				"MusicBrainz album artist id",
				"MusicBrainz artist id",
				"MusicBrainz recording id",
				"MusicBrainz release group id",
				"MusicBrainz release id",
				"MusicBrainz track id",
				"POPM:Windows Media Player 9 Series",
				"TXXX:RIPPER",
				"Title",
				"Track number",
				"rating",
			].sort(),
		);
	});

	it("counts the tracks that carry each value, of the tracks it was given", async () => {
		const { sharedTags } = await load();
		const rows = sharedTags(albumTracks(), names);

		// Replica has no genre and still counts in `of`. My Land's two genres each count once.
		expect(counts(rowOf(rows, "Genre"))).toEqual({
			"power metal": 3,
			"symphonic metal": 1,
		});
		expect(counts(rowOf(rows, "Album"))).toEqual({ Ecliptica: 4 });
		expect(counts(rowOf(rows, "Title"))).toEqual({
			"Blank File": 1,
			"My Land": 1,
			"8th Commandment": 1,
			Replica: 1,
		});
		expect(rows.map((row) => row.of)).toEqual(rows.map(() => 4));
	});

	it("marks as read-only the tags the tracks refuse, and no other", async () => {
		const { sharedTags } = await load();
		const rows = sharedTags(albumTracks(), names);
		const readonly = rows.filter((row) => row.readonly).map((row) => row.key);

		expect(readonly.sort()).toEqual(
			[
				"APIC:",
				"MusicBrainz album artist id",
				"MusicBrainz artist id",
				"MusicBrainz recording id",
				"MusicBrainz release group id",
				"MusicBrainz release id",
				"MusicBrainz track id",
				"POPM:Windows Media Player 9 Series",
				"rating",
			].sort(),
		);
	});

	it.each([
		["the first", [BLANK, LAND]],
		["a later one", [LAND, BLANK]],
	])(
		"marks a tag read-only when %s of the tracks that carry it refuses it",
		async (_which, order) => {
			const { sharedTags } = await load();
			// Both carry a rating, and only Blank File's list refuses it.
			const tracks = only(albumTracks(), ...order);
			tagsOf(tracks, LAND).rating = ["3"];

			expect(rowOf(sharedTags(tracks, names), "rating").readonly).toBe(true);
		},
	);
});

describe("applyEdits", () => {
	it("answers the tracks as they are for no edits", async () => {
		const applyEdits = await applying();

		expect(applyEdits(albumTracks(), [])).toEqual(albumTracks());
	});

	it("changes the tags alone and leaves the tracks it was given untouched", async () => {
		const applyEdits = await applying();
		const given = frozen(albumTracks());

		const after = applyEdits(given, [
			edit(given, { set: { Genre: ["rock"] } }),
		]);

		expect(given).toEqual(albumTracks());
		expect(after.map(({ tags: _, ...rest }) => rest)).toEqual(
			albumTracks().map(({ tags: _, ...rest }) => rest),
		);
	});

	it("sets a readable name on each track's own key, replacing what was there", async () => {
		const applyEdits = await applying();
		const tracks = albumTracks();

		const after = applyEdits(tracks, [
			edit(tracks, { set: { Genre: ["rock"] } }),
		]);

		expect(tagsOf(after, BLANK).genre).toEqual(["rock"]);
		expect(tagsOf(after, LAND).genre).toEqual(["rock"]);
		expect(tagsOf(after, EIGHTH).TCON).toEqual(["rock"]);
		// Replica had no genre: a set gives it one.
		expect(tagsOf(after, REPLICA).TCON).toEqual(["rock"]);
		for (const track of after) {
			expect(track.tags.Genre).toBeUndefined();
			expect(
				track.tags[track.family === "id3" ? "genre" : "TCON"],
			).toBeUndefined();
		}
	});

	it("removes a tag set to null, and a track without it stays without", async () => {
		const applyEdits = await applying();
		const tracks = albumTracks();

		const after = applyEdits(tracks, [edit(tracks, { set: { Genre: null } })]);

		expect(tagsOf(after, BLANK).genre).toBeUndefined();
		expect(tagsOf(after, EIGHTH).TCON).toBeUndefined();
		expect(tagsOf(after, REPLICA).TCON).toBeUndefined();
		expect(tagsOf(after, BLANK).album).toEqual(["Ecliptica"]);
	});

	it("adds each value to the tracks that lack it, after the values they have", async () => {
		const applyEdits = await applying();
		const tracks = albumTracks();

		// My Land has the first value already: adding the list whole would double it there.
		const after = applyEdits(tracks, [
			edit(tracks, { add: { Genre: ["symphonic metal", "heavy metal"] } }),
		]);

		const all = ["power metal", "symphonic metal", "heavy metal"];
		expect(tagsOf(after, BLANK).genre).toEqual(all);
		expect(tagsOf(after, LAND).genre).toEqual(all);
		expect(tagsOf(after, EIGHTH).TCON).toEqual(all);
		expect(tagsOf(after, REPLICA).TCON).toEqual([
			"symphonic metal",
			"heavy metal",
		]);
	});

	it("removes a value from the tracks that carry it and leaves the rest", async () => {
		const applyEdits = await applying();
		const tracks = albumTracks();

		const after = applyEdits(tracks, [
			edit(tracks, { remove: { Genre: ["symphonic metal"] } }),
		]);

		expect(tagsOf(after, LAND).genre).toEqual(["power metal"]);
		expect(tagsOf(after, BLANK).genre).toEqual(["power metal"]);
		expect(tagsOf(after, EIGHTH).TCON).toEqual(["power metal"]);
		expect(tagsOf(after, REPLICA).TCON).toBeUndefined();
	});

	it("leaves no value behind when a track's only one is removed", async () => {
		const applyEdits = await applying();
		const tracks = albumTracks();

		const after = applyEdits(tracks, [
			edit(tracks, { remove: { Genre: ["power metal"] } }),
		]);

		// Whether the emptied tag stays as an empty list or goes is not decided.
		expect(tagsOf(after, BLANK).genre ?? []).toEqual([]);
		expect(tagsOf(after, LAND).genre).toEqual(["symphonic metal"]);
	});

	it("applies the edits in the order they come", async () => {
		const applyEdits = await applying();
		const tracks = albumTracks();
		const set = edit(tracks, { set: { Genre: ["rock"] } });
		const add = edit(tracks, { add: { Genre: ["jazz"] } });

		expect(tagsOf(applyEdits(tracks, [set, add]), BLANK).genre).toEqual([
			"rock",
			"jazz",
		]);
		expect(tagsOf(applyEdits(tracks, [add, set]), BLANK).genre).toEqual([
			"rock",
		]);
	});

	it("applies each edit to the tracks it names and no other", async () => {
		const applyEdits = await applying();
		const tracks = albumTracks();

		const after = applyEdits(tracks, [
			edit(only(tracks, BLANK), { set: { Genre: ["rock"] } }),
			edit(only(tracks, EIGHTH), { add: { Genre: ["jazz"] } }),
		]);

		expect(tagsOf(after, BLANK).genre).toEqual(["rock"]);
		expect(tagsOf(after, LAND).genre).toEqual([
			"power metal",
			"symphonic metal",
		]);
		expect(tagsOf(after, EIGHTH).TCON).toEqual(["power metal", "jazz"]);
		expect(tagsOf(after, REPLICA).TCON).toBeUndefined();
	});

	it("tells two tracks of one path apart by their album", async () => {
		const applyEdits = await applying();
		const OTHER = "S/Sonata Arctica/(2000) Other";
		const [here] = only(albumTracks(), BLANK);
		const there = { ...only(albumTracks(), BLANK)[0]!, album: OTHER };

		const after = applyEdits(
			[here!, there],
			[edit([there], { set: { Genre: ["rock"] } })],
		);

		expect(tagsOf(after, BLANK, OTHER).genre).toEqual(["rock"]);
		expect(tagsOf(after, BLANK, here!.album).genre).toEqual(["power metal"]);
	});

	it.each([
		["TCON", [EIGHTH, REPLICA], [BLANK, LAND]],
		["genre", [BLANK, LAND], [EIGHTH, REPLICA]],
	])(
		"lands a format's own key %s on the tracks of that format alone",
		async (key, reached, spared) => {
			const applyEdits = await applying();
			const tracks = albumTracks();

			const after = applyEdits(tracks, [
				edit(tracks, { set: { [key]: ["rock"] } }),
			]);

			for (const path of reached)
				expect(tagsOf(after, path)[key]).toEqual(["rock"]);
			for (const path of spared)
				expect(tagsOf(after, path)).toEqual(tagsOf(tracks, path));
		},
	);

	it("sets and removes a tag with no readable name by its own key", async () => {
		const applyEdits = await applying();
		const tracks = albumTracks();
		const mp3s = only(tracks, EIGHTH, REPLICA);

		const after = applyEdits(tracks, [
			edit(mp3s, { set: { "TXXX:RIPPER": null } }),
			edit(mp3s, { add: { "TXXX:MOOD": ["calm"] } }),
		]);

		expect(tagsOf(after, EIGHTH)["TXXX:RIPPER"]).toBeUndefined();
		expect(tagsOf(after, EIGHTH)["TXXX:MOOD"]).toEqual(["calm"]);
		expect(tagsOf(after, REPLICA)["TXXX:MOOD"]).toEqual(["calm"]);
	});

	// A Vorbis field name has no case, and the server reads `GENRE` as the
	// `genre` the file holds. A page that takes it for a second tag shows the
	// edit beside the tag it changes and tells the server it saw none.
	describe("a Vorbis key typed in another case", () => {
		// `Genre` is the readable name and reaches every format; `GENRE` is not.
		it("sets GENRE on the FLACs' own genre, and on no MP3", async () => {
			const applyEdits = await applying();
			const tracks = albumTracks();

			const after = applyEdits(tracks, [
				edit(tracks, { set: { GENRE: ["rock"] } }),
			]);

			for (const path of [BLANK, LAND]) {
				expect(tagsOf(after, path).genre).toEqual(["rock"]);
				expect(Object.keys(tagsOf(after, path)).sort()).toEqual(
					Object.keys(tagsOf(tracks, path)).sort(),
				);
			}
			for (const path of [EIGHTH, REPLICA])
				expect(tagsOf(after, path)).toEqual(tagsOf(tracks, path));
		});

		it("adds to and removes from the values the FLAC holds under the lower-case key", async () => {
			const applyEdits = await applying();
			const tracks = albumTracks();
			const flacs = only(tracks, BLANK, LAND);

			const after = applyEdits(tracks, [
				edit(flacs, { add: { GENRE: ["heavy metal"] } }),
				edit(flacs, { remove: { Genre: ["symphonic metal"] } }),
				edit(flacs, { remove: { GENRE: ["power metal"] } }),
			]);

			expect(tagsOf(after, BLANK).genre).toEqual(["heavy metal"]);
			expect(tagsOf(after, LAND).genre).toEqual(["heavy metal"]);
			expect(tagsOf(after, BLANK).GENRE).toBeUndefined();
		});

		it("reads a key with no readable name the same way: MOOD is the mood a FLAC holds", async () => {
			const applyEdits = await applying();
			const tracks = albumTracks();
			const [blank, land] = only(tracks, BLANK, LAND);
			blank!.tags.mood = ["dark"];

			const after = applyEdits(tracks, [
				edit([blank!, land!], { add: { MOOD: ["calm"] } }),
			]);

			expect(tagsOf(after, BLANK).mood).toEqual(["dark", "calm"]);
			// New to this track, and still under the name a FLAC is read by.
			expect(tagsOf(after, LAND).mood).toEqual(["calm"]);
			expect(tagsOf(after, BLANK).MOOD).toBeUndefined();
			expect(tagsOf(after, LAND).MOOD).toBeUndefined();
		});

		// An ID3 frame's name has a case: `tcon` is no frame, and not TCON.
		it("keeps an ID3 key apart from the same letters in another case", async () => {
			const applyEdits = await applying();
			const tracks = albumTracks();
			const mp3s = only(tracks, EIGHTH, REPLICA);

			const after = applyEdits(tracks, [
				edit(mp3s, { set: { tcon: ["rock"] } }),
			]);

			expect(tagsOf(after, EIGHTH).TCON).toEqual(["power metal"]);
			expect(tagsOf(after, REPLICA).TCON).toBeUndefined();
		});
	});
});
