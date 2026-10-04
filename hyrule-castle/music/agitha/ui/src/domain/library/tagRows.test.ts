import { describe, expect, it } from "vitest";

import type { TagNames } from "@/shared/api/types";

import type { PanelTrack } from "./shared";
import { standingRows, tagRows } from "./tagRows";

const NAMES = {
	id3: {},
	vorbis: {
		title: "Title",
		genre: "Genre",
		artists: "Artists",
		albumartists: "Album artists",
	},
	mp4: {},
	asf: {},
} as TagNames;

const track = (path: string, tags: Record<string, string[]>): PanelTrack =>
	({
		album: "F/Future/(2017) Mask Off",
		path,
		family: "vorbis",
		tags,
		readonly: [],
	}) as unknown as PanelTrack;

describe("standingRows", () => {
	it("names the genre and the artist lists the tracks' format has a key for, and nothing with no track", () => {
		expect(standingRows([track("01.flac", {})], NAMES)).toEqual([
			"Genre",
			"Artists",
			"Album artists",
		]);
		expect(
			standingRows([track("01.flac", {})], {
				...NAMES,
				vorbis: { genre: "Genre" },
			} as TagNames),
		).toEqual(["Genre"]);
		expect(standingRows([], NAMES)).toEqual([]);
	});

	it("gives a row to type into though no track holds the tag", () => {
		const tracks = [track("01.flac", { title: ["Mask Off"] })];
		const rows = tagRows(tracks, [], NAMES, standingRows(tracks, NAMES));

		expect(rows.map((row) => row.key)).toEqual([
			"Title",
			"Genre",
			"Artists",
			"Album artists",
		]);
		expect(rows.find((row) => row.key === "Artists")).toMatchObject({
			now: null,
			next: null,
			change: "same",
			locked: null,
		});
	});
});
