import { describe, expect, it } from "vitest";

import { albumView, facts } from "@/test/albumView";

import { type Summary, summaryOf } from "./summary";

describe("summaryOf", () => {
	it("has nothing to say of an album with no files", () => {
		expect(summaryOf(albumView({ files: [] }))).toBeNull();
	});

	it.each<[string, Parameters<typeof facts>[1][], Partial<Summary>]>([
		[
			"adds up the tracks, their length and their size",
			[
				{ length: 100, size: 1_000 },
				{ length: 200, size: 2_000 },
				{ size: 3_000 },
			],
			{ tracks: 3, discs: 1, length: 500, size: 6_000 },
		],
		[
			"names the one format and what every file shares",
			[{}, {}],
			{
				format: "MP3",
				lossless: false,
				bitrate: { min: 320000, max: 320000 },
				sampleRate: 44100,
				bitDepth: null,
				channels: 2,
			},
		],
		[
			"joins the formats and calls the album lossy when one file is",
			[
				{ format: "FLAC", lossless: true, bit_depth: 16 },
				{ format: "MP3" },
				{ format: "FLAC", lossless: true, bit_depth: 16 },
			],
			{ format: "FLAC + MP3", lossless: false, bitDepth: null },
		],
		[
			"spans the bitrates and leaves out what the files disagree on",
			[
				{ bitrate: 128000, sample_rate: 48000, channels: 1 },
				{ bitrate: 320000 },
				{ bitrate: 256000 },
			],
			{
				bitrate: { min: 128000, max: 320000 },
				sampleRate: null,
				channels: null,
			},
		],
		[
			"keeps a bit depth every lossless file agrees on",
			[
				{ format: "FLAC", lossless: true, bit_depth: 24 },
				{ format: "FLAC", lossless: true, bit_depth: 24 },
			],
			{ format: "FLAC", lossless: true, bitDepth: 24 },
		],
	])("%s", (_, overs, expected) => {
		const files = overs.map((over, index) => facts(`1-${index + 1}`, over));

		expect(summaryOf(albumView({ files }))).toMatchObject(expected);
	});

	it("counts the discs the positions name", () => {
		const files = ["1-1", "1-2", "2-1", "3-1"].map((position) =>
			facts(position),
		);

		expect(summaryOf(albumView({ files }))?.discs).toBe(3);
	});
});
