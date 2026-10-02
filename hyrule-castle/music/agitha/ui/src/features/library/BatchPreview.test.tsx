import { afterEach, describe, expect, it, vi } from "vitest";

import type { JobState, LibraryJob, LibraryPreview } from "@/shared/api/types";
import {
	ECLIPTICA,
	JOB,
	posted,
	refusal,
	requested,
	SONATA,
	type Writes,
} from "@/test/library";
import {
	albumGets,
	dropSymphonicMetal,
	LAND,
	marked,
	REPLICA,
	reviewButton,
	tag,
	throughPolls,
} from "@/test/libraryAlbum";
import {
	type AlbumTitle,
	albumBox,
	albumsAround,
	allBox,
	closeArtist,
	findTag,
	genreChange,
	jobOver,
	openArtist,
	openBatchReview,
	previewAlbum,
	previewOver,
	REVENGE,
	type ServedArtist,
	SILENCE,
	sentencesOf,
	sonata,
	statesOf,
	trackOf,
	unselected,
	usableOnArtist,
	written,
} from "@/test/libraryArtist";
import { screen, within } from "@/test/render";

afterEach(closeArtist);

const NOTHING = /nothing (changes|to change)/i;
const NO_GENRE = `a track has no genre: ${REPLICA}`;
const NOT_READ_BACK = `${LAND} did not read back as written.`;
const BUSY = "another save is running on this artist";

// Every reason the server gives for leaving an album out of a batch.
const REASONS = [
	"nothing to change",
	"open in review",
	"changed since this page loaded",
	NO_GENRE,
];

// Two albums change and one is skipped. Both albums that change hold a track
// at `02. My Land.flac`, each with its own genres.
const twoChange = () =>
	previewOver(
		previewAlbum(ECLIPTICA, {
			tracks: [
				genreChange(
					LAND,
					["power metal", "symphonic metal"],
					["power metal", "symphonic metal", "heavy metal"],
				),
				genreChange(REPLICA, null, ["heavy metal"]),
			],
		}),
		previewAlbum(SILENCE, { skip: "open in review" }),
		previewAlbum(REVENGE, {
			tracks: [genreChange(LAND, ["rock"], ["rock", "heavy metal"])],
		}),
	);

// No album changes, and no reason served reads as the page's own sentence for that.
const allSkipped = () =>
	previewOver(
		previewAlbum(ECLIPTICA, { skip: NO_GENRE }),
		previewAlbum(SILENCE, { skip: "open in review" }),
		previewAlbum(REVENGE, { skip: "changed since this page loaded" }),
	);

// The review of a draft as the page shows it for a given answer of the preview.
// What the draft holds does not matter here: the review shows the answer.
async function reviewOf(preview: LibraryPreview) {
	const { user } = openArtist({ writes: { preview } });
	await unselected(user);
	await user.click(allBox());
	await dropSymphonicMetal(user);
	const review = await openBatchReview(user);
	return {
		review,
		apply: within(review).getByRole("button", { name: "Apply" }),
		// A track's group under the album it is listed with.
		track(album: AlbumTitle, path: string) {
			const [group, ...rest] = within(review)
				.queryAllByRole("group", { name: path })
				.filter((each) => albumsAround(each, review).join(" | ") === album);
			if (!group || rest.length > 0)
				throw new Error(`${album} has not one group named ${path}`);
			return group;
		},
		// Every track the review lists, whichever album it is under.
		groups: () =>
			within(review).queryAllByRole("group", { name: /\.(flac|mp3)$/ }),
		reasons: (album: AlbumTitle) => sentencesOf(album, REASONS, review),
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

// Sonata Arctica once the draft is written: Ecliptica's My Land has lost
// `symphonic metal`, so no track carries it.
function afterwards() {
	const artist = sonata();
	trackOf(artist, ECLIPTICA, LAND).tags.genre = ["power metal"];
	return artist;
}

interface Library {
	/** What the job route answers now. A case moves it on. With none, 404: agitha restarted and knows no job. */
	job: LibraryJob | undefined;
	/** What the artist's route answers now. */
	artist: ServedArtist;
	save?: Writes["save"];
}

const library = (over: Partial<Library> = {}): Library => ({
	job: jobOver(written(ECLIPTICA, "waiting"), written(REVENGE, "waiting")),
	artist: sonata(),
	...over,
});

// The page over a library a case can change while the page is open. Polls are
// answered from `library` as it is when each arrives.
function open(now: Library) {
	return openArtist({
		clock: true,
		artist: () => Response.json(now.artist),
		writes: {
			preview: twoChange(),
			save: now.save,
			job: () =>
				now.job ? Response.json(now.job) : new Response(null, { status: 404 }),
		},
	});
}

// One edit over every track, its review, and Apply.
async function apply(page: ReturnType<typeof open>) {
	await unselected(page.user);
	await page.user.click(allBox());
	await dropSymphonicMetal(page.user);
	const review = await openBatchReview(page.user);
	await page.user.click(within(review).getByRole("button", { name: "Apply" }));
}

const shows = (states: Partial<Record<AlbumTitle, JobState>>) => () => {
	for (const [title, state] of Object.entries(states))
		expect({ [title]: statesOf(title as AlbumTitle) }).toEqual({
			[title]: [state],
		});
};

const jobGets = (page: ReturnType<typeof open>) =>
	requested(page.calls).filter((path) => path.includes("/jobs/"));

describe("BatchPreview", () => {
	describe("what the batch would do", () => {
		it("lists under each album that changes its changed tracks, each tag before and after", async () => {
			const { track, groups } = await reviewOf(twoChange());

			// Three values after and two before: read the other way round it would not fit.
			expect(change(track("Ecliptica", LAND), "Genre")).toHaveTextContent(
				/Genre.*power metal.*symphonic metal.*power metal.*symphonic metal.*heavy metal/,
			);
			expect(change(track("Ecliptica", REPLICA), "Genre")).toHaveTextContent(
				/Genre.*—.*heavy metal/,
			);
			// The same file name in another album, with that album's own change.
			const other = change(track("For the Sake of Revenge", LAND), "Genre");
			expect(other).toHaveTextContent(/Genre.*rock.*rock.*heavy metal/);
			expect(other).not.toHaveTextContent("symphonic metal");
			// The tracks the preview says change, and no other.
			expect(groups()).toHaveLength(3);
		});

		it("names each skipped album with its own reason as served", async () => {
			const { reasons, groups } = await reviewOf(allSkipped());

			expect(reasons("Ecliptica")).toEqual([NO_GENRE]);
			expect(reasons("Songs of Silence")).toEqual(["open in review"]);
			expect(reasons("For the Sake of Revenge")).toEqual([
				"changed since this page loaded",
			]);
			expect(groups()).toEqual([]);
		});

		// A batch leaves an album out whole when it refuses one of the draft's
		// tags there. The skip says that it was left out, and the refused tags why.
		it("shows under a skipped album each tag it refused, with the reason", async () => {
			const ONE_FORMAT = "is one format's own key; edit one format at a time";
			const RATING = "ratings come from listening";
			const { review, reasons } = await reviewOf(
				previewOver(
					previewAlbum(ECLIPTICA, {
						tracks: [genreChange(REPLICA, null, ["heavy metal"])],
					}),
					previewAlbum(SILENCE, {
						skip: "nothing to change",
						refused: [
							{ key: "TXXX:RIPPER", reason: ONE_FORMAT },
							{ key: "rating", reason: RATING },
						],
					}),
					previewAlbum(REVENGE, { skip: "open in review" }),
				),
			);

			// How the key and the reason are joined is the page's to word. Each
			// is found by its reason, in a line that holds its key, under its album's name.
			const refusedUnder = (key: string, reason: string) =>
				within(review)
					.queryAllByText(reason, { exact: false })
					.filter((shown) =>
						(shown.closest("li, p") ?? shown).textContent?.includes(key),
					)
					.map((shown) => albumsAround(shown, review).join(" | "));
			expect(refusedUnder("TXXX:RIPPER", ONE_FORMAT)).toEqual([
				"Songs of Silence",
			]);
			expect(refusedUnder("rating", RATING)).toEqual(["Songs of Silence"]);
			// The skip's own reason stays beside them.
			expect(reasons("Songs of Silence")).toEqual(["nothing to change"]);
		});

		it("names an album skipped beside the albums that change, and offers Apply for those", async () => {
			const { reasons, apply: button } = await reviewOf(twoChange());

			expect(reasons("Songs of Silence")).toEqual(["open in review"]);
			expect(reasons("Ecliptica")).toEqual([]);
			expect(button).toBeEnabled();
		});

		it("says nothing changes and disables Apply where every album is skipped", async () => {
			const { review, apply: button } = await reviewOf(allSkipped());

			expect(review).toHaveTextContent(NOTHING);
			expect(button).toBeDisabled();
		});

		it("disables Apply where no album has anything to change, each named with that reason", async () => {
			const { reasons, apply: button } = await reviewOf(
				previewOver(
					previewAlbum(ECLIPTICA, { skip: "nothing to change" }),
					previewAlbum(SILENCE, { skip: "nothing to change" }),
					previewAlbum(REVENGE, { skip: "nothing to change" }),
				),
			);

			for (const title of [
				"Ecliptica",
				"Songs of Silence",
				"For the Sake of Revenge",
			] as const)
				expect(reasons(title)).toEqual(["nothing to change"]);
			expect(button).toBeDisabled();
		});

		// The artist page is a batch whatever it selects. Over tracks of one
		// album the server answers as for several: the album is skipped with its
		// reason, where the album's own page would get an empty list of tracks.
		it("sends a selection inside one album as a batch, and says nothing changes where that album is skipped", async () => {
			const { calls, user } = openArtist({
				writes: {
					preview: previewOver(
						previewAlbum(ECLIPTICA, { skip: "nothing to change" }),
					),
				},
			});
			await unselected(user);
			await user.click(albumBox("Ecliptica"));
			await dropSymphonicMetal(user);

			const review = await openBatchReview(user);

			expect(review).toHaveTextContent(NOTHING);
			expect(sentencesOf("Ecliptica", REASONS, review)).toEqual([
				"nothing to change",
			]);
			expect(
				within(review).getByRole("button", { name: "Apply" }),
			).toBeDisabled();
			expect(within(review).queryByRole("button", { name: "Save" })).toBeNull();
			const [draft] = posted(calls, "/api/library/preview");
			expect([...new Set(draft!.tracks.map((track) => track.album))]).toEqual([
				ECLIPTICA,
			]);
			expect(draft!.batch).toBe(true);
		});

		it("does not say nothing changes where an album does", async () => {
			const { review } = await reviewOf(twoChange());

			expect(review).not.toHaveTextContent(NOTHING);
		});
	});

	describe("Apply", () => {
		it("posts to save the draft the preview showed, and nothing before Apply is pressed", async () => {
			const page = open(library());
			await unselected(page.user);
			await page.user.click(allBox());
			await dropSymphonicMetal(page.user);
			const review = await openBatchReview(page.user);
			expect(posted(page.calls, "/api/library/save")).toEqual([]);

			await page.user.click(
				within(review).getByRole("button", { name: "Apply" }),
			);

			await throughPolls(() =>
				expect(posted(page.calls, "/api/library/save")).toHaveLength(1),
			);
			expect(posted(page.calls, "/api/library/save")).toEqual(
				posted(page.calls, "/api/library/preview"),
			);
			const [draft] = posted(page.calls, "/api/library/save");
			expect(draft!.edits).toHaveLength(1);
			expect(draft!.tracks).toHaveLength(10);
			expect(draft!.batch).toBe(true);
		});

		it("shows each album's own state as the job reports it, and the page is read-only meanwhile", async () => {
			const now = library();
			const page = open(now);
			await unselected(page.user);
			await page.user.click(allBox());
			await dropSymphonicMetal(page.user);
			const review = await openBatchReview(page.user);
			// What is locked below was there to use before.
			expect(usableOnArtist()).toEqual(
				expect.arrayContaining([
					"Select all tracks",
					"Select Ecliptica",
					"Remove Genre",
					"Review changes",
					"Apply",
				]),
			);
			await page.user.click(
				within(review).getByRole("button", { name: "Apply" }),
			);

			const steps: [JobState, JobState][] = [
				["waiting", "waiting"],
				["writing", "waiting"],
				["verifying", "waiting"],
				// The first album is done and the batch is not.
				["done", "writing"],
			];
			for (const [first, second] of steps) {
				now.job = jobOver(written(ECLIPTICA, first), written(REVENGE, second));
				await throughPolls(
					shows({ Ecliptica: first, "For the Sake of Revenge": second }),
				);
				expect(usableOnArtist()).toEqual([]);
				// Read-only is not empty: the tags of the selection stay on the page.
				expect(tag("Genre")).toHaveTextContent("power metal 8/10");
			}
			// The job asked for is the one save answered with.
			expect(jobGets(page)).toContain(`GET /api/library/jobs/${JOB}`);
			// An album the job does not write has no state.
			expect(statesOf("Songs of Silence")).toEqual([]);
		});

		it("shows why an album failed beside that album, and goes on showing the next album's states", async () => {
			const now = library();
			const page = open(now);
			await apply(page);
			await throughPolls(shows({ Ecliptica: "waiting" }));

			now.job = jobOver(
				written(ECLIPTICA, "failed", NOT_READ_BACK),
				written(REVENGE, "writing"),
			);

			await throughPolls(() =>
				expect(sentencesOf("Ecliptica", [NOT_READ_BACK])).toEqual([
					NOT_READ_BACK,
				]),
			);
			await throughPolls(shows({ "For the Sake of Revenge": "writing" }));
			expect(sentencesOf("For the Sake of Revenge", [NOT_READ_BACK])).toEqual(
				[],
			);
			// The batch is still running.
			expect(usableOnArtist()).toEqual([]);

			now.job = jobOver(
				written(ECLIPTICA, "failed", NOT_READ_BACK),
				written(REVENGE, "verifying"),
			);
			await throughPolls(shows({ "For the Sake of Revenge": "verifying" }));
		});

		it("keeps a failed album's reason on the page after the batch has ended, and the page can be used again", async () => {
			const now = library();
			const page = open(now);
			await apply(page);
			await throughPolls(shows({ Ecliptica: "waiting" }));
			const before = albumGets(page.calls, SONATA);

			now.job = jobOver(
				written(ECLIPTICA, "failed", NOT_READ_BACK),
				written(REVENGE, "done"),
			);

			await throughPolls(() =>
				expect(albumGets(page.calls, SONATA)).toBeGreaterThan(before),
			);
			await throughPolls(() =>
				expect(usableOnArtist()).toContain("Select all tracks"),
			);
			// A reason that left with the progress would be gone by now.
			expect(sentencesOf("Ecliptica", [NOT_READ_BACK])).toEqual([
				NOT_READ_BACK,
			]);
		});

		it("shows the artist as the files hold it once every album is done, with the draft gone", async () => {
			const now = library();
			const page = open(now);
			await apply(page);
			await throughPolls(shows({ Ecliptica: "waiting" }));
			const before = albumGets(page.calls, SONATA);

			now.artist = afterwards();
			// The first album is done a poll before the second.
			now.job = jobOver(
				written(ECLIPTICA, "done"),
				written(REVENGE, "writing"),
			);
			await throughPolls(shows({ "For the Sake of Revenge": "writing" }));
			now.job = jobOver(written(ECLIPTICA, "done"), written(REVENGE, "done"));

			await throughPolls(() =>
				expect(albumGets(page.calls, SONATA)).toBeGreaterThan(before),
			);
			await throughPolls(() =>
				expect(usableOnArtist()).toContain("Select all tracks"),
			);
			expect(reviewButton()).toBeDisabled();
			expect(page.place()).toBe(`/library/${SONATA}`);

			// Over every track again, whatever the selection was left as.
			await unselected(page.user);
			await page.user.click(allBox());
			await throughPolls(() =>
				expect(tag("Genre")).toHaveTextContent("power metal 8/10"),
			);
			expect(tag("Genre")).not.toHaveTextContent("symphonic metal");
			expect(marked("Genre")).toBeNull();
			expect(reviewButton()).toBeDisabled();
		});

		// Jobs live in the server's memory: after a restart the job route knows none.
		it("says the batch was interrupted where the server no longer knows its job, stops asking for it, and keeps the draft", async () => {
			const now = library();
			const page = open(now);
			await apply(page);
			await throughPolls(shows({ Ecliptica: "waiting" }));
			expect(usableOnArtist()).toEqual([]);
			const before = albumGets(page.calls, SONATA);

			now.job = undefined;

			await throughPolls(() =>
				expect(screen.getByText(/interrupted/i)).toBeInTheDocument(),
			);
			await throughPolls(() =>
				expect(usableOnArtist()).toEqual(
					expect.arrayContaining(["Select all tracks", "Review changes"]),
				),
			);
			expect(marked("Genre")).toBeVisible();
			// The artist is read again: the files are what the restart left.
			await throughPolls(() =>
				expect(albumGets(page.calls, SONATA)).toBeGreaterThan(before),
			);

			const asked = jobGets(page).length;
			await vi.advanceTimersByTimeAsync(4_200);
			expect(jobGets(page)).toHaveLength(asked);
			expect(usableOnArtist()).toContain("Review changes");
		});

		it("shows a refusal of the save as served, and keeps the draft", async () => {
			const page = open(library({ save: refusal(409, BUSY) }));
			await apply(page);

			await throughPolls(() =>
				expect(screen.getByText(BUSY)).toBeInTheDocument(),
			);
			await throughPolls(() =>
				expect(usableOnArtist()).toContain("Review changes"),
			);
			expect(marked("Genre")).toBeVisible();
			expect(await findTag("Genre")).not.toHaveTextContent("symphonic metal");
			// A refused save started no job.
			expect(jobGets(page)).toEqual([]);
		});
	});
});
