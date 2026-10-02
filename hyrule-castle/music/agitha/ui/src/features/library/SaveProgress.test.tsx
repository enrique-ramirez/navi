import { act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
	JobState,
	LibraryAlbum,
	LibraryArtist,
	LibraryJob,
} from "@/shared/api/types";
import {
	ECLIPTICA,
	fixtures,
	JOB,
	jobOf,
	posted,
	previewOf,
	refusal,
	requested,
	SONATA,
	type Writes,
} from "@/test/library";
import {
	albumGets,
	albumOf,
	box,
	closeAlbum,
	marked,
	newValue,
	openAlbum,
	openReview,
	reviewButton,
	setPowerMetal,
	shown,
	shownWithTags,
	tag,
	throughPolls,
	usable,
} from "@/test/libraryAlbum";
import { screen, waitFor, within } from "@/test/render";

afterEach(closeAlbum);

const MOVED = `${SONATA}/(2008) Ecliptica`;
const STALE = "the album changed since this page loaded";
const NOT_READ_BACK = "02. My Land.flac did not read back as written.";

// Ecliptica as the files hold it once the draft is written: every track's
// genre is `power metal` alone, so My Land has lost `symphonic metal` and
// Replica has gained a genre.
function written(over: Partial<LibraryAlbum> = {}) {
	const album = albumOf(over);
	album.tracks[1]!.tags.genre = ["power metal"];
	album.tracks[3]!.tags.TCON = ["power metal"];
	return album;
}

interface Library {
	/** What the job route answers now. A case moves it on. With none, 404: agitha restarted and knows no job. */
	job: LibraryJob | undefined;
	/** What Ecliptica's route answers now. */
	album: LibraryAlbum | undefined;
	artist: LibraryArtist;
	/** The album at the folder a save moves it to. */
	moved?: LibraryAlbum;
	save?: Writes["save"];
}

// The page over a library a case can change while the page is open. Polls are
// answered from `library` as it is when each arrives.
function open(library: Library) {
	return openAlbum({
		clock: true,
		shelves: {
			artists: { [SONATA]: () => Response.json(library.artist) },
			albums: {
				[ECLIPTICA]: () =>
					library.album
						? Response.json(library.album)
						: new Response(null, { status: 404 }),
				[MOVED]: () =>
					library.moved
						? Response.json(library.moved)
						: new Response(null, { status: 404 }),
			},
		},
		writes: {
			preview: previewOf({
				new_path: ECLIPTICA,
				problems: [],
				refused: [],
				cover: null,
			}),
			save: library.save,
			job: () =>
				library.job
					? Response.json(library.job)
					: new Response(null, { status: 404 }),
		},
	});
}

const library = (over: Partial<Library> = {}): Library => ({
	job: jobOf("waiting"),
	album: albumOf(),
	artist: structuredClone(fixtures.artist),
	...over,
});

// One edit, its review, and Save.
async function save(page: ReturnType<typeof open>) {
	await shown();
	await setPowerMetal(page.user);
	const review = await openReview(page.user);
	await page.user.click(within(review).getByRole("button", { name: "Save" }));
}

const says = (text: string) => () =>
	expect(screen.getByText(text)).toBeInTheDocument();

const jobGets = (page: ReturnType<typeof open>) =>
	requested(page.calls).filter((path) => path.includes("/jobs/")).length;

// Every request for a folder's own route, however the address is escaped.
const gets = (page: ReturnType<typeof open>, folder: string) =>
	requested(page.calls)
		.map(decodeURIComponent)
		.filter((path) => path === `GET /api/library/${folder}`).length;

const editable = () => {
	expect(box("My Land")).toBeEnabled();
	expect(newValue("Genre")).toBeEnabled();
};

describe("SaveProgress", () => {
	it("posts to save the draft the review showed, and nothing before Save is pressed", async () => {
		const page = open(library());
		await shown();
		await setPowerMetal(page.user);
		const review = await openReview(page.user);
		expect(posted(page.calls, "/api/library/save")).toEqual([]);

		await page.user.click(within(review).getByRole("button", { name: "Save" }));

		await throughPolls(() =>
			expect(posted(page.calls, "/api/library/save")).toHaveLength(1),
		);
		expect(posted(page.calls, "/api/library/save")).toEqual(
			posted(page.calls, "/api/library/preview"),
		);
		expect(posted(page.calls, "/api/library/save")[0]!.edits).toHaveLength(1);
	});

	it("shows each state the job reports as the save goes, and the album is read-only meanwhile", async () => {
		const now = library();
		const page = open(now);
		await save(page);

		for (const state of ["waiting", "writing", "verifying"] as const) {
			now.job = jobOf(state);
			await throughPolls(says(state));
			expect(usable()).toEqual([]);
			// Read-only is not empty: the tags of the selection stay on the page.
			expect(tag("Genre")).toHaveTextContent("power metal 3/4");
			expect(tag("Album")).toHaveTextContent("Ecliptica");
		}
		// The job asked for is the one save answered with.
		expect(requested(page.calls)).toContain(`GET /api/library/jobs/${JOB}`);
	});

	// A listing is kept for 30 s and a page drawn afresh shows what is kept.
	// The album as it was read before Save has no job and the old tags, and
	// would open editable under a save that is still writing.
	it("is read-only and shows the save's state again when the owner leaves the album during a save and comes straight back", async () => {
		const now = library({ job: jobOf("writing") });
		// From the moment the save is accepted the album's route serves its job.
		now.save = () => {
			now.album = albumOf({ job: { id: JOB, state: "writing" } });
			return Response.json({ job: JOB }, { status: 202 });
		};
		const page = open(now);
		await shown();
		const savedAt = Date.now();
		const before = albumGets(page.calls);
		await save(page);
		await throughPolls(says("writing"), 2);

		// Whether leaving asks first while the save runs is not this case's to say.
		await page.user.click(
			screen.getByRole("treeitem", { name: "Sabaton, folder" }),
		);
		await waitFor(() =>
			expect(screen.queryByRole("alertdialog") ?? page.place()).not.toBe(
				`/library/${ECLIPTICA}`,
			),
		);
		const asking = screen.queryByRole("alertdialog");
		if (asking) {
			const [leave] = within(asking)
				.getAllByRole("button")
				.filter((button) => button.textContent !== "Cancel");
			await page.user.click(leave!);
		}
		await waitFor(() => expect(page.place()).toBe("/library/S/Sabaton"));
		await waitFor(() =>
			expect(screen.queryByRole("heading", { name: /Ecliptica/ })).toBeNull(),
		);

		await act(async () => {
			page.router.history.back();
		});
		await waitFor(() => expect(page.place()).toBe(`/library/${ECLIPTICA}`));
		await shownWithTags();

		await throughPolls(says("writing"), 2);
		expect(usable()).toEqual([]);
		expect(tag("Genre")).toHaveTextContent("power metal 3/4");
		// The album was read again after the save was accepted: what the page
		// held from before it says nothing of the job.
		expect(albumGets(page.calls)).toBeGreaterThan(before);
		// All of it inside the time a listing is kept, so the page did not
		// ask again only because that time had passed.
		expect(Date.now() - savedAt).toBeLessThan(30_000);
	});

	it("shows the album as the files hold it once the save is done, with the draft gone", async () => {
		const now = library();
		const page = open(now);
		await save(page);
		await throughPolls(says("waiting"));
		const before = albumGets(page.calls);

		now.album = written();
		now.job = jobOf("done");

		await throughPolls(() =>
			expect(albumGets(page.calls)).toBeGreaterThan(before),
		);
		await throughPolls(() =>
			expect(tag("Genre")).not.toHaveTextContent("symphonic metal"),
		);
		await throughPolls(editable);
		expect(marked("Genre")).toBeNull();
		expect(reviewButton()).toBeDisabled();
		expect(page.place()).toBe(`/library/${ECLIPTICA}`);
	});

	it("moves to the album's new address where the save moved its folder, without asking", async () => {
		const now = library();
		const page = open(now);
		await save(page);
		await throughPolls(says("waiting"));

		// The folder is gone from where it was, and the artist lists it under its new name.
		now.album = undefined;
		now.moved = written({ path: MOVED });
		now.artist.albums[0] = {
			...now.artist.albums[0]!,
			path: MOVED,
			name: "(2008) Ecliptica",
		};
		const before = { old: gets(page, ECLIPTICA), letter: gets(page, "S") };
		now.job = jobOf("done", { new_path: MOVED });

		await throughPolls(() => expect(page.place()).toBe(`/library/${MOVED}`));
		// The draft is written, so there is nothing to ask about on the way.
		expect(screen.queryByRole("alertdialog")).toBeNull();
		await throughPolls(editable);
		expect(screen.getByRole("heading", { name: /Ecliptica/ })).toBeVisible();
		expect(tag("Genre")).not.toHaveTextContent("symphonic metal");
		expect(reviewButton()).toBeDisabled();
		expect(
			await screen.findByRole("treeitem", {
				name: "(2008) Ecliptica, folder",
				current: "page",
			}),
		).toBeVisible();
		expect(
			screen.queryByRole("treeitem", { name: "(1999) Ecliptica, folder" }),
		).toBeNull();
		// A save can rename the artist's folder too, so the letter is listed afresh.
		await throughPolls(() =>
			expect(gets(page, "S")).toBeGreaterThan(before.letter),
		);
		// The folder is gone from its old address: asking for it there is a
		// failure the owner sees flash by. Two polls on, nothing has asked.
		await vi.advanceTimersByTimeAsync(4_200);
		expect(gets(page, MOVED)).toBeGreaterThan(0);
		expect(gets(page, ECLIPTICA)).toBe(before.old);
		expect(screen.queryByText("could not load the library")).toBeNull();
	});

	it("shows why a save failed, and the album is editable again with the draft still there", async () => {
		const now = library();
		const page = open(now);
		await save(page);
		await throughPolls(says("waiting"));
		expect(usable()).toEqual([]);

		now.job = jobOf("failed", { error: NOT_READ_BACK });

		await throughPolls(() =>
			expect(
				screen.getByText(NOT_READ_BACK, { exact: false }),
			).toBeInTheDocument(),
		);
		await throughPolls(editable);
		expect(marked("Genre")).toBeVisible();
		expect(reviewButton()).toBeEnabled();
	});

	// Jobs live in the server's memory. After a restart the job route knows
	// none: the save did not finish, so the album is as it was.
	describe("a save whose job the server no longer knows", () => {
		it("says the save was interrupted, stops asking for the job, and the album is editable again with the draft still there", async () => {
			const now = library();
			const page = open(now);
			await save(page);
			await throughPolls(says("waiting"));
			expect(usable()).toEqual([]);
			const before = albumGets(page.calls);

			now.job = undefined;

			await throughPolls(() =>
				expect(screen.getByText(/interrupted/i)).toBeInTheDocument(),
			);
			await throughPolls(editable);
			expect(marked("Genre")).toBeVisible();
			expect(newValue("Genre")).toHaveValue("power metal");
			expect(reviewButton()).toBeEnabled();
			// The cover's warning is a status too; the save's is the one that must be gone.
			expect(screen.queryByText("Saving")).toBeNull();
			// The album is read again: the files are what the restart left.
			await throughPolls(() =>
				expect(albumGets(page.calls)).toBeGreaterThan(before),
			);

			const asked = jobGets(page);
			await vi.advanceTimersByTimeAsync(4_200);
			expect(jobGets(page)).toBe(asked);
			// Nothing brought the save back meanwhile.
			// The cover's warning is a status too; the save's is the one that must be gone.
			expect(screen.queryByText("Saving")).toBeNull();
			expect(reviewButton()).toBeEnabled();
		});

		it("drops that sentence once the draft is saved again", async () => {
			const now = library();
			const page = open(now);
			await save(page);
			await throughPolls(says("waiting"));
			now.job = undefined;
			await throughPolls(() =>
				expect(screen.getByText(/interrupted/i)).toBeInTheDocument(),
			);
			await throughPolls(editable);

			now.job = jobOf("writing");
			const review = await openReview(page.user);
			await page.user.click(
				within(review).getByRole("button", { name: "Save" }),
			);

			await throughPolls(says("writing"));
			expect(screen.queryByText(/interrupted/i)).toBeNull();
			expect(posted(page.calls, "/api/library/save")).toHaveLength(2);
		});
	});

	describe("an album with a save from before the page opened", () => {
		it.each<JobState>(["waiting", "writing", "verifying"])(
			"opens read-only and shows the save %s",
			async (state) => {
				open(
					library({
						album: albumOf({ job: { id: JOB, state } }),
						job: jobOf(state),
					}),
				);
				await screen.findByRole("heading", { name: /Ecliptica/ });

				await throughPolls(says(state));
				expect(usable()).toEqual([]);
			},
		);

		it("follows that save through the job route until it is done, then is editable", async () => {
			const now = library({
				album: albumOf({ job: { id: JOB, state: "waiting" } }),
				job: jobOf("verifying"),
			});
			const page = open(now);
			await screen.findByRole("heading", { name: /Ecliptica/ });

			// The album route said waiting; the job route knows better.
			await throughPolls(says("verifying"));
			const before = albumGets(page.calls);

			now.album = written({ job: { id: JOB, state: "done" } });
			now.job = jobOf("done");

			await throughPolls(() =>
				expect(albumGets(page.calls)).toBeGreaterThan(before),
			);
			await throughPolls(editable);
			expect(tag("Genre")).not.toHaveTextContent("symphonic metal");
		});

		it.each<[JobState, string | null]>([
			["done", null],
			["failed", NOT_READ_BACK],
		])("opens editable where that save is %s", async (state, error) => {
			open(
				library({
					album: albumOf({ job: { id: JOB, state } }),
					job: jobOf(state, { error }),
				}),
			);
			await shown();

			await throughPolls(editable);
			expect(reviewButton()).toBeDisabled();
		});
	});

	describe("a save the server refuses", () => {
		it("says the album changed since the page loaded and offers Reload, which shows the files as they are with no draft", async () => {
			const now = library({ save: refusal(409, STALE) });
			const page = open(now);
			await save(page);

			await throughPolls(says(STALE));
			const reload = screen.getByRole("button", { name: "Reload" });
			const before = albumGets(page.calls);
			now.album = written();
			await page.user.click(reload);

			await throughPolls(() =>
				expect(albumGets(page.calls)).toBeGreaterThan(before),
			);
			await throughPolls(() =>
				expect(tag("Genre")).not.toHaveTextContent("symphonic metal"),
			);
			await throughPolls(editable);
			expect(marked("Genre")).toBeNull();
			expect(reviewButton()).toBeDisabled();
			expect(screen.queryByText(STALE)).toBeNull();
			expect(screen.queryByRole("button", { name: "Reload" })).toBeNull();
			// A refused save started no job.
			expect(
				requested(page.calls).filter((path) => path.includes("/jobs/")),
			).toEqual([]);
		});

		it.each([
			`already in the library: ${MOVED}`,
			"a track has no genre: 04. Replica.mp3",
		])(
			"shows the refusal %s as served, and keeps the draft",
			async (sentence) => {
				const page = open(library({ save: refusal(409, sentence) }));
				await save(page);

				await throughPolls(says(sentence));
				await throughPolls(editable);
				expect(marked("Genre")).toBeVisible();
				expect(reviewButton()).toBeEnabled();
				expect(
					requested(page.calls).filter((path) => path.includes("/jobs/")),
				).toEqual([]);
			},
		);
	});
});
