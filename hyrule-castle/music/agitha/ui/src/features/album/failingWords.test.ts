import { describe, expect, it } from "vitest";

import type { FailingTrack } from "@/shared/api/types";
import { en, type Phrase } from "@/shared/i18n/en";
import { albumView, candidate } from "@/test/albumView";

import { failingOf, failingWords } from "./failingWords";

// The English phrase with its `{name}` places filled, as the page's own translator does it.
const t = ((phrase: Phrase, values: Record<string, string | number> = {}) =>
	en[phrase].replace(/\{(\w+)\}/g, (_, name: string) =>
		String(values[name]),
	)) as Parameters<typeof failingWords>[1];

const track = (over: Partial<FailingTrack>): FailingTrack => ({
	position: "1-9",
	title: "La samba de Od\u00edn",
	file_title: "La Samba de Od\u00edn",
	title_agrees: true,
	length: 288.7,
	wants: 260,
	...over,
});

describe("failingWords", () => {
	it("gives both lengths where the title agrees and the length does not", () => {
		expect(failingWords(track({}), t)).toBe("4:48 here, 4:20 on MusicBrainz");
	});

	it("gives both titles where only the title differs, and both things where both do", () => {
		const other = { title_agrees: false, file_title: "Otra" };
		expect(failingWords(track({ ...other, length: 260 }), t)).toBe(
			"titled Otra here, La samba de Od\u00edn on MusicBrainz",
		);
		expect(failingWords(track(other), t)).toBe(
			"titled Otra here, La samba de Od\u00edn on MusicBrainz; 4:48 here, 4:20 on MusicBrainz",
		);
	});

	it("still says the file does not fit where MusicBrainz has no length to show", () => {
		expect(failingWords(track({ wants: null }), t)).toBe(
			"does not fit the release's track",
		);
	});
});

describe("failingOf", () => {
	it("reads the tracks that do not fit the release the preview was planned for, by position", () => {
		const view = albumView();
		const planned = "planned";
		view.preview!.release_id = planned;
		view.preview!.candidates = [
			candidate({
				release_id: "another",
				failing: [track({ position: "1-1" })],
			}),
			candidate({ release_id: planned, failing: [track({})] }),
		];

		expect([...failingOf(view).keys()]).toEqual(["1-9"]);
	});

	it("reads none from a preview made before the engine listed them", () => {
		expect(failingOf(albumView()).size).toBe(0);
	});
});
