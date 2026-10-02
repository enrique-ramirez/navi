import { afterEach, describe, expect, it } from "vitest";

import type { LibraryPreview, PreviewAlbum } from "@/shared/api/types";
import {
	ECLIPTICA,
	fixtures,
	held,
	posted,
	previewOf,
	refusal,
	SONATA,
} from "@/test/library";
import {
	albumGets,
	albumOf,
	BLANK,
	closeAlbum,
	dropSymphonicMetal,
	EIGHTH,
	LAND,
	marked,
	openAlbum,
	openReview,
	REPLICA,
	reviewButton,
	shown,
	tag,
} from "@/test/libraryAlbum";
import { screen, waitFor, within } from "@/test/render";

afterEach(closeAlbum);

const MOVED = `${SONATA}/(2008) Ecliptica`;

// The preview fixture's album with nothing in the way of a save: it stays in
// its folder, and no problem, refused tag or cover comes with it.
const clean = (over: Partial<PreviewAlbum> = {}) =>
	previewOf({
		new_path: ECLIPTICA,
		problems: [],
		refused: [],
		cover: null,
		...over,
	});

// The review of a draft as the page shows it for a given answer of the preview.
// What the draft holds does not matter here: the review shows the answer.
async function reviewOf(preview: LibraryPreview) {
	const { user } = openAlbum({ writes: { preview } });
	await shown();
	await dropSymphonicMetal(user);
	const review = await openReview(user);
	return {
		review,
		save: within(review).getByRole("button", { name: "Save" }),
		track: (path: string) => within(review).getByRole("group", { name: path }),
		queryTrack: (path: string) =>
			within(review).queryByRole("group", { name: path }),
	};
}

// The row or list item of one tag's change in a track's group.
function change(track: HTMLElement, key: string) {
	const lines = [
		...within(track).queryAllByRole("row"),
		...within(track).queryAllByRole("listitem"),
	];
	const line = lines.find((each) => each.textContent?.includes(key));
	if (!line) throw new Error(`no row or list item for ${key}`);
	return line;
}

const PREVIEW = "/api/library/preview";
const SAVE = "/api/library/save";
const STALE = "the album changed since this page loaded";
const NO_UPLOAD = "No such cover upload.";
// What the page says where it has no better sentence.
const GENERIC = "could not load the library";

const queryReview = () =>
	screen.queryByRole("region", { name: "Review changes" });

// The Save of the review on the page, where there is one that can be pressed.
const saveOffered = () => {
	const review = queryReview();
	const save = review && within(review).queryByRole("button", { name: "Save" });
	return save && !(save as HTMLButtonElement).disabled ? save : null;
};

const times = (text: string | null, part: string) =>
	(text ?? "").split(part).length - 1;

describe("ReviewChanges", () => {
	it("lists every track that changes with each of its tags before and after", async () => {
		const { track } = await reviewOf(clean());

		for (const path of [BLANK, LAND, EIGHTH, REPLICA])
			expect(change(track(path), "Date")).toHaveTextContent(/Date.*1999.*2008/);
		// Two values before and one after: read the other way round it would not fit.
		expect(change(track(LAND), "Genre")).toHaveTextContent(
			/Genre.*power metal.*symphonic metal.*power metal/,
		);
		expect(change(track(BLANK), "Date")).not.toHaveTextContent("Genre");
	});

	it("shows a tag that is removed and one that is new with a dash for the side that has none", async () => {
		const { track } = await reviewOf(clean());

		expect(change(track(EIGHTH), "TXXX:RIPPER")).toHaveTextContent(
			/TXXX:RIPPER.*EAC 0\.99.*—/,
		);
		expect(change(track(REPLICA), "Genre")).toHaveTextContent(
			/Genre.*—.*power metal/,
		);
	});

	it("lists only the tracks the preview says change", async () => {
		const [first] = fixtures.preview.albums[0]!.tracks;
		const { track, queryTrack } = await reviewOf(clean({ tracks: [first!] }));

		expect(track(BLANK)).toBeVisible();
		for (const path of [LAND, EIGHTH, REPLICA])
			expect(queryTrack(path)).toBeNull();
	});

	it("shows a track's path before and after where the file is renamed, and once where it is not", async () => {
		const [first, second] = structuredClone(fixtures.preview.albums[0]!.tracks);
		first!.new_path = "01. Blank Page.flac";
		const { track } = await reviewOf(clean({ tracks: [first!, second!] }));

		expect(track(BLANK)).toHaveTextContent("01. Blank Page.flac");
		expect(times(track(LAND).textContent, LAND)).toBeLessThan(2);
	});

	it("shows the album's own path before and after where the folder moves", async () => {
		const { review, save } = await reviewOf(clean({ new_path: MOVED }));

		expect(review.textContent).toMatch(
			/S\/Sonata Arctica\/\(1999\) Ecliptica.*S\/Sonata Arctica\/\(2008\) Ecliptica/s,
		);
		expect(save).toBeEnabled();
	});

	it("shows no move of the album where it stays in its folder", async () => {
		const { review } = await reviewOf(clean());

		// A move reads as the folder twice, before and after.
		expect(times(review.textContent, ECLIPTICA)).toBeLessThan(2);
	});

	it("names each problem as its rule and detail, and Save is disabled while one shows", async () => {
		const { review, save } = await reviewOf(
			clean({
				problems: [
					{ rule: "already in the library", detail: MOVED },
					{ rule: "a track has no genre", detail: REPLICA },
				],
			}),
		);

		expect(review).toHaveTextContent(`already in the library: ${MOVED}`);
		expect(review).toHaveTextContent(`a track has no genre: ${REPLICA}`);
		expect(save).toBeDisabled();
	});

	it("names each refused tag with its reason, and Save stays enabled", async () => {
		const { review, save } = await reviewOf(
			clean({
				refused: [
					{ key: "MusicBrainz release id", reason: "is a MusicBrainz ID" },
					{ key: "rating", reason: "ratings come from listening" },
				],
			}),
		);

		// How the key and the reason are joined is the page's to word.
		expect(review).toHaveTextContent(
			/MusicBrainz release id\W{0,3}is a MusicBrainz ID/,
		);
		expect(review).toHaveTextContent(
			/rating\W{0,3}ratings come from listening/,
		);
		expect(save).toBeEnabled();
	});

	it("says nothing changes and disables Save where the preview changes nothing", async () => {
		const { review, save } = await reviewOf(clean({ tracks: [] }));

		expect(review).toHaveTextContent(/nothing (changes|to change)/i);
		expect(save).toBeDisabled();
	});

	it("does not say nothing changes where a track does", async () => {
		const { review } = await reviewOf(clean());

		expect(review).not.toHaveTextContent(/nothing (changes|to change)/i);
	});

	describe("an answer that arrives after the draft has changed", () => {
		// The preview is asked for, a second edit is made, and only then does the
		// answer come: it describes a draft the page no longer holds. Shown with
		// Save, it would let the owner save changes no review ever listed.
		it("offers no Save against it, and Save posts only the draft a review was shown for", async () => {
			const answer = held(clean());
			const { calls, user } = openAlbum({ writes: { preview: answer.answer } });
			await shown();
			await dropSymphonicMetal(user);
			await user.click(reviewButton());
			await waitFor(() => expect(posted(calls, PREVIEW)).toHaveLength(1));

			await user.click(screen.getByRole("button", { name: "Remove Date" }));
			await within(tag("Date")).findByText("changed");
			answer.release();

			// Review changes can be pressed again only once the first answer is in.
			await waitFor(() => expect(reviewButton()).toBeEnabled());
			expect(saveOffered()).toBeNull();
			expect(posted(calls, SAVE)).toEqual([]);

			const review = await openReview(user);
			await user.click(within(review).getByRole("button", { name: "Save" }));

			await waitFor(() => expect(posted(calls, SAVE)).toHaveLength(1));
			const previews = posted(calls, PREVIEW);
			expect(previews).toHaveLength(2);
			expect(previews[1]!.edits).toHaveLength(2);
			expect(posted(calls, SAVE)).toEqual([previews[1]]);
		});
	});

	describe("a preview the server refuses", () => {
		it("says the album changed since the page loaded and offers Reload, which shows the files as they are with no draft", async () => {
			const now = { album: albumOf() };
			const { calls, user } = openAlbum({
				shelves: {
					albums: { [ECLIPTICA]: () => Response.json(now.album) },
				},
				writes: { preview: refusal(409, STALE) },
			});
			await shown();
			await dropSymphonicMetal(user);
			await user.click(reviewButton());

			expect(await screen.findByText(STALE)).toBeVisible();
			const reload = screen.getByRole("button", { name: "Reload" });
			expect(screen.queryByText(GENERIC)).toBeNull();
			expect(queryReview()).toBeNull();

			const before = albumGets(calls);
			now.album = albumOf();
			now.album.tracks[1]!.tags.genre = ["power metal", "heavy metal"];
			await user.click(reload);

			await waitFor(() => expect(albumGets(calls)).toBeGreaterThan(before));
			await waitFor(() =>
				expect(tag("Genre")).toHaveTextContent("heavy metal"),
			);
			expect(marked("Genre")).toBeNull();
			expect(reviewButton()).toBeDisabled();
			expect(screen.queryByText(STALE)).toBeNull();
			expect(screen.queryByRole("button", { name: "Reload" })).toBeNull();
		});

		it("shows any other refusal as served, with no Reload, and keeps the draft", async () => {
			const { user } = openAlbum({
				writes: { preview: refusal(400, NO_UPLOAD) },
			});
			await shown();
			await dropSymphonicMetal(user);
			await user.click(reviewButton());

			expect(await screen.findByText(NO_UPLOAD)).toBeVisible();
			expect(screen.queryByText(GENERIC)).toBeNull();
			expect(screen.queryByRole("button", { name: "Reload" })).toBeNull();
			expect(queryReview()).toBeNull();
			expect(marked("Genre")).toBeVisible();
			expect(reviewButton()).toBeEnabled();
		});

		// A refusal with no sentence, or no answer at all, has only the page's own words.
		it("says the page's own sentence where the preview fails with none served", async () => {
			const { user } = openAlbum({
				writes: { preview: () => new Response(null, { status: 500 }) },
			});
			await shown();
			await dropSymphonicMetal(user);
			await user.click(reviewButton());

			expect(await screen.findByText(GENERIC)).toBeVisible();
			expect(marked("Genre")).toBeVisible();
		});

		it("drops the refusal's sentence once a later preview is answered", async () => {
			const preview = { refused: true };
			const { user } = openAlbum({
				writes: {
					preview: () =>
						preview.refused
							? refusal(400, NO_UPLOAD)()
							: Response.json(clean()),
				},
			});
			await shown();
			await dropSymphonicMetal(user);
			await user.click(reviewButton());
			await screen.findByText(NO_UPLOAD);

			preview.refused = false;
			await openReview(user);

			expect(screen.queryByText(NO_UPLOAD)).toBeNull();
		});
	});
});
