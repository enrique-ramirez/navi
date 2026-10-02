import { afterEach, describe, expect, it } from "vitest";

import type { LibraryTrack, OrderFlag } from "@/shared/api/types";
import {
	albumTracks,
	ECLIPTICA,
	held,
	posted,
	previewOf,
	refsOf,
} from "@/test/library";
import {
	albumOf,
	BLANK,
	box,
	closeAlbum,
	EIGHTH,
	inPathOrder,
	LAND,
	marked,
	openReview,
	REPLICA,
	reviewButton,
	setPowerMetal,
	shown,
	TITLES,
} from "@/test/libraryAlbum";
import { screen, waitFor, within } from "@/test/render";
import {
	checked,
	FLAGGED,
	NO_ANSWER,
	NO_FIT,
	NO_RELEASE,
	openOrdered,
	orderAt,
	orderGets,
	saidOf,
	selectOnly,
	swapOffered,
	UNCHECKED,
	unchecked,
} from "@/test/trackOrder";

// The track order of an album page: Swap over two selected tracks, and the
// flag the order route raises on two tracks that run each other's length.
// `openOrdered` is `openAlbum` with that route answering; with no `order` it
// answers that the order was checked and nothing is flagged.
afterEach(closeAlbum);

const PREVIEW = "/api/library/preview";

// A track as a draft sends it. A swap names no tag, so it has seen none.
const sent = (
	track: LibraryTrack,
	seen: Record<string, string[] | null> = {},
) => ({
	album: ECLIPTICA,
	path: track.path,
	loaded: track.loaded,
	seen,
});

// A preview with nothing in the way of a save, for a draft that swaps My Land and Replica.
const swapPreview = () =>
	previewOf({
		new_path: ECLIPTICA,
		problems: [],
		refused: [],
		cover: null,
		tracks: [
			{
				path: LAND,
				new_path: "02. Replica.flac",
				changes: [{ key: "Title", before: ["My Land"], after: ["Replica"] }],
			},
			{
				path: REPLICA,
				new_path: "04. My Land.mp3",
				changes: [{ key: "Title", before: ["Replica"], after: ["My Land"] }],
			},
		],
	});

// The mark on a track the draft swaps: the other track's number, as the table shows it.
const swappedWith = (number: string) => `swapped with ${number}`;
const anySwapMark = () => screen.queryAllByText(/swapped with/);

// The first two tracks flagged as well as the fixture's two.
const FIRST_TWO: OrderFlag = {
	a: BLANK,
	b: LAND,
	a_runs: 276,
	a_wants: 245,
	b_runs: 245,
	b_wants: 276,
};

const orderLine = () => screen.queryByText(/Track order not checked/);
const checkAgain = () => screen.queryByRole("button", { name: "Check again" });

describe("TrackOrder", () => {
	describe("Swap over the selection", () => {
		it("offers Swap with exactly two tracks selected, and with no other number", async () => {
			const { user } = openOrdered();
			await shown();

			// All four are selected when the page opens.
			expect(swapOffered()).toBeNull();

			await selectOnly(user, "My Land", "8th Commandment", "Replica");
			expect(swapOffered()).toBeNull();

			await selectOnly(user, "My Land", "Replica");
			expect(swapOffered()).toBeEnabled();

			await selectOnly(user, "Replica");
			expect(swapOffered()).toBeNull();

			await selectOnly(user);
			expect(swapOffered()).toBeNull();

			// Two again, a different pair: the count decides, not which tracks.
			await selectOnly(user, "Blank File", "8th Commandment");
			expect(swapOffered()).toBeEnabled();
		});

		it("puts the selected pair in the draft as one swap in album order, and the review shows both tracks", async () => {
			const [, land, , replica] = albumTracks();
			const { calls, user } = openOrdered({
				writes: { preview: swapPreview() },
			});
			await shown();
			expect(reviewButton()).toBeDisabled();

			// Selected last track first: the pair goes out in the album's order all the same.
			await selectOnly(user);
			await user.click(box("Replica"));
			await user.click(box("My Land"));
			await user.click(swapOffered()!);

			await waitFor(() => expect(reviewButton()).toBeEnabled());
			// The swap is on the page alone until the review is asked for.
			expect(calls.filter((call) => call.method !== "GET")).toEqual([]);

			const review = await openReview(user);
			expect(posted(calls, PREVIEW).map(inPathOrder)).toEqual([
				{
					tracks: [sent(land!), sent(replica!)],
					edits: [],
					swaps: [[LAND, REPLICA]],
					cover: null,
					batch: false,
				},
			]);
			expect(
				within(review).getByRole("group", { name: LAND }),
			).toHaveTextContent("02. Replica.flac");
			expect(
				within(review).getByRole("group", { name: REPLICA }),
			).toHaveTextContent("04. My Land.mp3");
		});

		it("marks each of the two tracks as swapped with the other, and no other track", async () => {
			// Numbers no file name carries: the mark names the number the table shows.
			const album = albumOf();
			album.tracks[1]!.number = 12;
			album.tracks[3]!.number = 14;
			const { user } = openOrdered({
				shelves: { albums: { [ECLIPTICA]: album } },
			});
			await shown();
			expect(anySwapMark()).toEqual([]);

			await selectOnly(user, "My Land", "Replica");
			await user.click(swapOffered()!);

			await waitFor(() =>
				expect(saidOf("My Land")).toContain(swappedWith("14")),
			);
			expect(saidOf("Replica")).toContain(swappedWith("12"));
			expect(saidOf("Blank File")).not.toContain("swapped with");
			expect(saidOf("8th Commandment")).not.toContain("swapped with");
		});

		it("takes the swap away on Discard changes, and the next draft carries none", async () => {
			const { calls, user } = openOrdered({
				writes: { preview: swapPreview() },
			});
			await shown();
			await selectOnly(user, "My Land", "Replica");
			await user.click(swapOffered()!);
			await waitFor(() => expect(anySwapMark()).not.toEqual([]));

			await user.click(screen.getByRole("button", { name: "Discard changes" }));

			await waitFor(() => expect(anySwapMark()).toEqual([]));
			expect(reviewButton()).toBeDisabled();

			// A swap that was only hidden would go out with the next draft.
			await selectOnly(user, ...TITLES);
			await setPowerMetal(user);
			await openReview(user);
			expect(posted(calls, PREVIEW).map((draft) => draft.swaps)).toEqual([[]]);
		});

		it("holds a swap and a tag edit in one draft", async () => {
			const tracks = albumTracks();
			const [blank, land, eighth, replica] = tracks;
			const { calls, user } = openOrdered({
				writes: { preview: swapPreview() },
			});
			await shown();

			await selectOnly(user, "8th Commandment", "Replica");
			await user.click(swapOffered()!);
			await selectOnly(user, ...TITLES);
			await setPowerMetal(user);
			await openReview(user);

			expect(posted(calls, PREVIEW).map(inPathOrder)).toEqual([
				{
					tracks: [
						sent(blank!, { Genre: ["power metal"] }),
						sent(land!, { Genre: ["power metal", "symphonic metal"] }),
						sent(eighth!, { Genre: ["power metal"] }),
						sent(replica!, { Genre: null }),
					],
					edits: [
						{
							tracks: refsOf(tracks),
							set: { Genre: ["power metal"] },
							add: {},
							remove: {},
						},
					],
					swaps: [[EIGHTH, REPLICA]],
					cover: null,
					batch: false,
				},
			]);
			// The edit did not take the swap's mark off its tracks.
			expect(saidOf("Replica")).toContain(swappedWith("03"));
			expect(marked("Genre")).toBeVisible();
		});

		it("never holds one pair twice, however often Swap is pressed on it", async () => {
			// Whether a second press takes the pair out again is not decided. A
			// draft with the pair twice would swap the two and swap them back.
			const { calls, user } = openOrdered({
				writes: { preview: swapPreview() },
			});
			await shown();

			await selectOnly(user, "My Land", "Replica");
			await user.click(swapOffered()!);
			await waitFor(() => expect(reviewButton()).toBeEnabled());
			await selectOnly(user, "My Land", "Replica");
			const again = swapOffered();
			if (again) await user.click(again);

			if (reviewButton().hasAttribute("disabled")) {
				expect(anySwapMark()).toEqual([]);
				return;
			}
			await openReview(user);
			expect(posted(calls, PREVIEW).map((draft) => draft.swaps)).toEqual([
				[[LAND, REPLICA]],
			]);
		});
	});

	describe("the order check", () => {
		it("asks for the order of the album it shows, and only once the album has answered", async () => {
			const album = held(albumOf());
			const { calls } = openOrdered({
				shelves: { albums: { [ECLIPTICA]: album.answer } },
				order: FLAGGED,
			});

			// The folders are on the page and the album is still on its way.
			await screen.findByRole("treeitem", { name: "Sabaton, folder" });
			expect(orderGets(calls)).toEqual([]);

			album.release();
			await shown();

			await waitFor(() => expect(orderGets(calls)).toEqual([ECLIPTICA]));
			const albumAt = calls.findIndex(
				(call) =>
					decodeURIComponent(new URL(call.url).pathname) ===
					`/api/library/${ECLIPTICA}`,
			);
			expect(albumAt).toBeGreaterThan(-1);
			expect(orderAt(calls)).toBeGreaterThan(albumAt);
		});

		it("shows the album and takes an edit while the order is still being checked, and keeps the draft when it answers", async () => {
			const order = held(FLAGGED);
			const { calls, user } = openOrdered({ order: order.answer });

			await shown();
			await waitFor(() => expect(orderGets(calls)).toHaveLength(1));
			for (const title of TITLES) expect(box(title)).toBeChecked();

			await user.click(box("Replica"));
			expect(box("Replica")).not.toBeChecked();
			await setPowerMetal(user);
			expect(marked("Genre")).toBeVisible();
			expect(reviewButton()).toBeEnabled();
			// Nothing of the answer can be on the page: it has not been given.
			expect(screen.queryByText(/look swapped/)).toBeNull();

			order.release();

			await waitFor(() => expect(saidOf("Replica")).toContain("look swapped"));
			expect(marked("Genre")).toBeVisible();
			expect(reviewButton()).toBeEnabled();
			expect(box("Replica")).not.toBeChecked();
		});
	});

	describe("a flag", () => {
		it("says on both tracks which two look swapped, with what each runs and what MusicBrainz has, and on no other track", async () => {
			// Numbers no file name carries, and four lengths that each floor to a
			// different minute and second, none of them a length the table shows.
			const album = albumOf();
			album.tracks[2]!.number = 5;
			album.tracks[3]!.number = 6;
			openOrdered({
				shelves: { albums: { [ECLIPTICA]: album } },
				order: checked({
					a: EIGHTH,
					b: REPLICA,
					a_runs: 302.9,
					a_wants: 219.5,
					b_runs: 222.99,
					b_wants: 304,
				}),
			});
			await shown();

			const sentence =
				"05 and 06 look swapped: 05 runs 5:02 where MusicBrainz has 3:39; 06 runs 3:42 where MusicBrainz has 5:04";
			await waitFor(() =>
				expect(saidOf("8th Commandment")).toContain(sentence),
			);
			expect(saidOf("Replica")).toContain(sentence);
			expect(saidOf("Blank File")).not.toContain("look swapped");
			expect(saidOf("My Land")).not.toContain("look swapped");
		});

		it("swaps nothing by itself: a flag leaves the draft empty until its Swap is pressed", async () => {
			openOrdered({ order: FLAGGED });
			await shown();

			await waitFor(() => expect(saidOf("Replica")).toContain("look swapped"));
			await screen.findAllByRole("button", { name: "Swap 03 and 04" });

			expect(reviewButton()).toBeDisabled();
			expect(
				screen.getByRole("button", { name: "Discard changes" }),
			).toBeDisabled();
			expect(anySwapMark()).toEqual([]);
		});

		it("puts the flagged pair in the draft from the flag's own Swap, whatever is selected", async () => {
			const [, , eighth, replica] = albumTracks();
			const { calls, user } = openOrdered({
				order: FLAGGED,
				writes: { preview: swapPreview() },
			});
			await shown();

			// Every track is selected, so the selection's Swap is not on offer.
			const [swap] = await screen.findAllByRole("button", {
				name: "Swap 03 and 04",
			});
			expect(swap).toBeEnabled();
			expect(swapOffered()).toBeNull();
			await user.click(swap!);

			await waitFor(() =>
				expect(saidOf("8th Commandment")).toContain(swappedWith("04")),
			);
			expect(saidOf("Replica")).toContain(swappedWith("03"));
			await openReview(user);
			expect(posted(calls, PREVIEW).map(inPathOrder)).toEqual([
				{
					tracks: [sent(eighth!), sent(replica!)],
					edits: [],
					swaps: [[EIGHTH, REPLICA]],
					cover: null,
					batch: false,
				},
			]);
		});

		it("gives each of two flags its own sentence on its own two tracks, and its own Swap", async () => {
			const [blank, land] = albumTracks();
			const { calls, user } = openOrdered({
				order: checked(FIRST_TWO, ...FLAGGED.flags),
				writes: { preview: swapPreview() },
			});
			await shown();

			const first =
				"01 and 02 look swapped: 01 runs 4:36 where MusicBrainz has 4:05; 02 runs 4:05 where MusicBrainz has 4:36";
			const second =
				"03 and 04 look swapped: 03 runs 4:55 where MusicBrainz has 3:41; 04 runs 3:41 where MusicBrainz has 4:55";
			await waitFor(() => expect(saidOf("Blank File")).toContain(first));
			expect(saidOf("My Land")).toContain(first);
			expect(saidOf("8th Commandment")).toContain(second);
			expect(saidOf("Replica")).toContain(second);
			expect(saidOf("Blank File")).not.toContain("03 and 04");
			expect(saidOf("Replica")).not.toContain("01 and 02");
			expect(
				screen.getAllByRole("button", { name: "Swap 03 and 04" }).length,
			).toBeGreaterThan(0);

			// The first flag's Swap takes the first flag's pair and leaves the second be.
			const [swap] = screen.getAllByRole("button", { name: "Swap 01 and 02" });
			await user.click(swap!);
			await openReview(user);

			expect(posted(calls, PREVIEW).map(inPathOrder)).toEqual([
				{
					tracks: [sent(blank!), sent(land!)],
					edits: [],
					swaps: [[BLANK, LAND]],
					cover: null,
					batch: false,
				},
			]);
		});

		it("says nothing about the order where it was checked and no pair is flagged", async () => {
			const page = openOrdered({ order: checked() });
			await shown();
			await page.orderSettled();

			expect(orderGets(page.calls)).toEqual([ECLIPTICA]);
			expect(screen.queryByText(/look swapped/)).toBeNull();
			expect(orderLine()).toBeNull();
			expect(checkAgain()).toBeNull();
			expect(screen.queryAllByRole("button", { name: /^Swap \S/ })).toEqual([]);
		});
	});

	describe("an order that was not checked", () => {
		it.each([
			{ reason: NO_RELEASE, again: false },
			{ reason: NO_FIT, again: false },
			{ reason: NO_ANSWER, again: true },
		])("says why in one line: $reason", async ({ reason, again }) => {
			openOrdered({ order: { ...UNCHECKED, reason, retry: again } });
			await shown();

			// The whole sentence is one element's text, as the route served it.
			expect(await screen.findByText(reason)).toBeVisible();
			expect(screen.queryByText(/look swapped/)).toBeNull();
			// Check again comes with the one reason that asking again can change.
			if (again) expect(checkAgain()).toBeEnabled();
			else expect(checkAgain()).toBeNull();
		});

		it("asks the route again on Check again, and the new answer takes the line's place", async () => {
			const { calls, user } = openOrdered({
				order: [unchecked(NO_ANSWER), FLAGGED],
			});
			await shown();
			await screen.findByText(NO_ANSWER);
			expect(orderGets(calls)).toHaveLength(1);

			await user.click(
				await screen.findByRole("button", { name: "Check again" }),
			);

			await waitFor(() => expect(saidOf("Replica")).toContain("look swapped"));
			expect(orderGets(calls)).toEqual([ECLIPTICA, ECLIPTICA]);
			expect(orderLine()).toBeNull();
			expect(checkAgain()).toBeNull();
		});

		it("keeps the line and Check again where MusicBrainz still does not answer, then drops both for a reason that will not change", async () => {
			const { calls, user } = openOrdered({
				order: [unchecked(NO_ANSWER), unchecked(NO_ANSWER), unchecked(NO_FIT)],
			});
			await shown();

			await user.click(
				await screen.findByRole("button", { name: "Check again" }),
			);
			await waitFor(() => expect(orderGets(calls)).toHaveLength(2));
			await user.click(
				await screen.findByRole("button", { name: "Check again" }),
			);

			expect(await screen.findByText(NO_FIT)).toBeVisible();
			expect(orderGets(calls)).toHaveLength(3);
			expect(screen.queryByText(NO_ANSWER)).toBeNull();
			expect(checkAgain()).toBeNull();
		});
	});

	describe("an order request that fails", () => {
		const failures = [
			{ how: "a 500", answer: () => new Response(null, { status: 500 }) },
			{
				how: "no answer at all",
				answer: () => Promise.reject(new TypeError("Failed to fetch")),
			},
		];

		it.each(failures)(
			"leaves the album usable and says the order was not checked, after $how",
			async ({ answer }) => {
				const { user } = openOrdered({ order: answer });
				await shown();

				// Which reason follows the colon for a request that failed is not decided.
				expect(
					await screen.findByText(/^Track order not checked: \S/),
				).toBeVisible();
				expect(
					screen.getByRole("heading", { name: /Ecliptica/ }),
				).toBeVisible();
				for (const title of TITLES) expect(box(title)).toBeChecked();
				await setPowerMetal(user);
				expect(reviewButton()).toBeEnabled();
			},
		);

		// A request that failed is asked again, as `MusicBrainz did not answer` is.
		it.each(failures)(
			"offers Check again after $how, and the new answer takes the line's place",
			async ({ answer }) => {
				const { calls, user } = openOrdered({ order: [answer, FLAGGED] });
				await shown();
				await screen.findByText(/^Track order not checked: \S/);

				await user.click(
					await screen.findByRole("button", { name: "Check again" }),
				);

				await waitFor(() =>
					expect(saidOf("Replica")).toContain("look swapped"),
				);
				expect(orderGets(calls)).toHaveLength(2);
				expect(orderLine()).toBeNull();
				expect(checkAgain()).toBeNull();
			},
		);
	});
});
