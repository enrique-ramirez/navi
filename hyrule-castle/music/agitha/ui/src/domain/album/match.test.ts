import { describe, expect, it } from "vitest";

import type { Candidate } from "@/shared/api/types";
import { candidate } from "@/test/albumView";

import { byLevel, type Level, levelOf, releaseUrl, trackTotal } from "./match";

describe("levelOf", () => {
	it.each<[string, Partial<Candidate>, Level]>([
		["fits in every check", {}, "strong"],
		["is 15 s off, the most that still fits", { duration_diff: -15 }, "strong"],
		["has no failing-track count", { failing_tracks: null }, "strong"],
		["is 16 s off", { duration_diff: 16 }, "possible"],
		["has a track that doesn't line up", { failing_tracks: 1 }, "possible"],
		["credits another artist", { artist_agrees: false }, "possible"],
		[
			"has no known length difference",
			{ duration_diff: null as unknown as number },
			"possible",
		],
		["has another track count", { matches_counts: false }, "weak"],
		[
			"was listed but not fetched",
			{ checked: false, matches_counts: false },
			"unchecked",
		],
		[
			"has no title, from a plan older than `checked`",
			{ title: null as unknown as string },
			"unchecked",
		],
	])("calls a release that %s %s", (_, over, level) => {
		expect(levelOf(candidate(over))).toBe(level);
	});
});

describe("byLevel", () => {
	it("puts the best fit first and keeps musiclib's order between equals", () => {
		const list = [
			candidate({ release_id: "weak", matches_counts: false }),
			candidate({ release_id: "unchecked", checked: false }),
			candidate({ release_id: "possible-a", duration_diff: 40 }),
			candidate({ release_id: "strong" }),
			candidate({ release_id: "possible-b", failing_tracks: 2 }),
		];

		expect(byLevel(list).map((each) => each.release_id)).toEqual([
			"strong",
			"possible-a",
			"possible-b",
			"weak",
			"unchecked",
		]);
		// The list it was given is left as it came.
		expect(list[0]?.release_id).toBe("weak");
	});
});

describe("trackTotal", () => {
	it.each<[(number | null)[], number | null]>([
		[[3], 3],
		[[10, 12], 22],
		[[10, null], null],
		[[], 0],
	])("adds up %j to %j", (counts, total) => {
		expect(trackTotal(candidate({ track_counts: counts }))).toBe(total);
	});
});

describe("releaseUrl", () => {
	it("links the release on MusicBrainz", () => {
		expect(releaseUrl("6f1a2b3c-0000-4000-8000-000100000001")).toBe(
			"https://musicbrainz.org/release/6f1a2b3c-0000-4000-8000-000100000001",
		);
	});
});
