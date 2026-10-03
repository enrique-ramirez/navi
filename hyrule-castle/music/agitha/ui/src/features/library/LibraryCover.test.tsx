import { fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
	CoverCheck,
	CoverUpload,
	LibraryAlbum,
	LibraryCover,
	LibraryJob,
} from "@/shared/api/types";
import uploadFixture from "@/test/fixtures/library/cover-upload.json";
import {
	albumTracks,
	ECLIPTICA,
	fixtures,
	JOB,
	jobOf,
	posted,
	previewOf,
	refsOf,
	refusal,
} from "@/test/library";
import {
	albumGets,
	albumOf,
	closeAlbum,
	inPathOrder,
	openAlbum,
	openReview,
	reviewButton,
	setPowerMetal,
	shown,
	throughPolls,
} from "@/test/libraryAlbum";
import { screen, userEvent, waitFor, within } from "@/test/render";

const COVERS = "/api/library/covers";
const PREVIEW = "/api/library/preview";
const SAVE = "/api/library/save";

const NOT_AN_IMAGE = "Those bytes are not an image.";
const WRONG_TYPE = "The cover must be a JPEG, PNG, WebP or GIF image.";

// The album fixture's cover: 480 × 480, failing the cover test.
const SMALL: LibraryCover = fixtures.album.cover!;
const SQUARE: LibraryCover = {
	url: SMALL.url,
	width: 600,
	height: 600,
	passes: true,
	problem: null,
};

// The upload fixture's answer: 1200 × 1200, passing.
const UPLOADED: CoverUpload = uploadFixture;
// A book cover: its sentence is not the album cover's.
const TALL: CoverCheck = {
	width: 1000,
	height: 1400,
	passes: false,
	problem: "The cover is its width over its height is 0.71.",
};

const png = () =>
	new File(["PNG bytes of the reissue"], "reissue.png", { type: "image/png" });
const webp = () =>
	new File(["WebP bytes of a scan"], "scan.webp", { type: "image/webp" });

interface Upload {
	/** The `Content-Type` a browser would send. */
	type: string | null;
	/** The body, read as text. */
	bytes: string;
}

type Respond = () => Response | Promise<Response>;

const answers =
	(body: CoverUpload): Respond =>
	() =>
		Response.json(body);

// The helper's fake hands every body to a `Request`, which reads a jsdom
// `File` as the text `[object File]`. The upload is answered here instead,
// from what the page gave `fetch`. A browser sends a Blob with the Blob's own
// type where no header names one, so that counts as the type sent.
function serveUploads(replies: Respond[]) {
	const uploads: Upload[] = [];
	const through = globalThis.fetch;
	vi.stubGlobal(
		"fetch",
		async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = new URL(
				String(input instanceof Request ? input.url : input),
				"http://localhost",
			);
			if (init?.method?.toUpperCase() !== "PUT" || url.pathname !== COVERS)
				return through(input, init);

			const body = init.body;
			const upload: Upload = {
				type:
					new Headers(init.headers).get("content-type") ??
					(body instanceof Blob && body.type !== "" ? body.type : null),
				bytes: "",
			};
			// Counted before the body is read, so a case can say none was sent.
			uploads.push(upload);
			upload.bytes = await textOf(body);
			const reply = replies[Math.min(uploads.length, replies.length) - 1];
			return reply ? reply() : new Response(null, { status: 404 });
		},
	);
	return uploads;
}

async function textOf(body: RequestInit["body"]) {
	if (body instanceof Blob) return body.text();
	if (body instanceof ArrayBuffer) return new TextDecoder().decode(body);
	if (ArrayBuffer.isView(body)) return new TextDecoder().decode(body);
	return String(body);
}

interface Opened {
	/** The cover the album route serves. With none named, the fixture's. */
	cover?: LibraryCover | null;
	/** The answer to each upload in turn; the last one answers any after it. */
	uploads?: Respond[];
	preview?: Parameters<typeof previewOf>[0];
	album?: Partial<LibraryAlbum>;
}

// A preview of a draft that only replaces the cover: no track changes.
const coverOnly = (cover: CoverCheck) => ({
	new_path: ECLIPTICA,
	tracks: [],
	problems: [],
	refused: [],
	cover,
});

function open({
	cover = SMALL,
	uploads = [answers(UPLOADED)],
	preview,
	album,
}: Opened = {}) {
	const page = openAlbum({
		shelves: { albums: { [ECLIPTICA]: albumOf({ cover, ...album }) } },
		writes: { preview: previewOf(preview) },
	});
	return { ...page, uploads: serveUploads(uploads) };
}

const current = () => screen.getByRole("img", { name: "Ecliptica cover" });
const queryCurrent = () =>
	screen.queryByRole("img", { name: "Ecliptica cover" });
const fresh = () => screen.findByRole("img", { name: "New cover" });
const queryFresh = () => screen.queryByRole("img", { name: "New cover" });
const picker = () => screen.getByLabelText<HTMLInputElement>("Replace cover");

// A warning is the server's sentence, whatever the card writes around it.
const warnings = (problem: string) =>
	screen.queryAllByText(problem, { exact: false });

// A file let go over part of the card, as a browser reports it. jsdom has no
// DataTransfer, so this one carries the file both ways a page may read it.
function drop(target: HTMLElement, file: File) {
	const dataTransfer = {
		files: [file],
		items: [{ kind: "file", type: file.type, getAsFile: () => file }],
		types: ["Files"],
	};
	fireEvent.dragOver(target, { dataTransfer });
	fireEvent.drop(target, { dataTransfer });
}

// Every track of the album as a draft with a cover sends it: no tag was edited, so none was seen.
const everyTrack = (seen: (path: string) => Record<string, string[] | null>) =>
	albumTracks().map((track) => ({
		album: ECLIPTICA,
		path: track.path,
		loaded: track.loaded,
		seen: seen(track.path),
	}));

describe("LibraryCover", () => {
	const createObjectURL = URL.createObjectURL;
	const revokeObjectURL = URL.revokeObjectURL;

	beforeEach(() => {
		// jsdom has no object URLs. Each image gets an address of its own.
		let made = 0;
		URL.createObjectURL = vi.fn(() => {
			made += 1;
			return `blob:http://localhost/picked-${made}`;
		});
		URL.revokeObjectURL = vi.fn();
	});

	afterEach(() => {
		closeAlbum();
		URL.createObjectURL = createObjectURL;
		URL.revokeObjectURL = revokeObjectURL;
	});

	describe("the cover the album has", () => {
		it("shows the cover with its pixel size, and its warning as served where it fails the cover test", async () => {
			open();
			await shown();

			expect(current()).toHaveAttribute("src", SMALL.url);
			expect(screen.getByText("480 × 480")).toBeVisible();
			expect(warnings(SMALL.problem!)).toHaveLength(1);
		});

		it("says No cover where the album has none, and still offers Replace cover", async () => {
			open({ cover: null });
			await shown();

			expect(screen.getByText("No cover")).toBeVisible();
			expect(queryCurrent()).toBeNull();
			expect(picker()).toBeEnabled();
		});
	});

	describe("Replace cover", () => {
		it("uploads a picked image as its own bytes and type, and shows it with its own size, the current cover one press away", async () => {
			const { calls, uploads, user } = open();
			await shown();
			expect(reviewButton()).toBeDisabled();

			await user.upload(picker(), png());

			const added = await fresh();
			expect(uploads).toEqual([
				{ type: "image/png", bytes: "PNG bytes of the reissue" },
			]);
			expect(added.getAttribute("src")).toBeTruthy();
			expect(added).not.toHaveAttribute("src", SMALL.url);
			expect(screen.getByText("1200 × 1200")).toBeVisible();
			expect(warnings(SMALL.problem!)).toEqual([]);
			expect(reviewButton()).toBeEnabled();
			await user.click(screen.getByRole("button", { name: "Current" }));
			expect(current()).toHaveAttribute("src", SMALL.url);
			expect(screen.getByText("480 × 480")).toBeVisible();
			expect(warnings(SMALL.problem!)).toHaveLength(1);
			// The image is uploaded when picked; the draft goes nowhere until the review.
			expect(posted(calls, PREVIEW)).toEqual([]);
		});

		it("takes an image dropped on the cover, sent with that file's type", async () => {
			const { uploads } = open();
			await shown();

			drop(current(), webp());

			await fresh();
			expect(uploads).toEqual([
				{ type: "image/webp", bytes: "WebP bytes of a scan" },
			]);
			expect(screen.getByText("1200 × 1200")).toBeVisible();
			expect(reviewButton()).toBeEnabled();
		});

		it("takes an image dropped where the album has no cover, and still says No cover for the current one", async () => {
			const { uploads } = open({ cover: null });
			await shown();

			drop(screen.getByText("No cover"), png());

			await fresh();
			expect(uploads).toHaveLength(1);
			expect(screen.getByText("1200 × 1200")).toBeVisible();
			fireEvent.click(screen.getByRole("button", { name: "Current" }));
			expect(screen.getByText("No cover")).toBeVisible();
		});

		it("accepts an image that fails the cover test, and shows that image's warning with its size", async () => {
			const { uploads, user } = open({
				cover: SQUARE,
				uploads: [answers({ cover: "b7e1", ...TALL })],
			});
			await shown();
			// The current cover passes, so nothing warns yet.
			expect(warnings(TALL.problem!)).toEqual([]);

			await user.upload(picker(), png());

			await fresh();
			expect(uploads).toHaveLength(1);
			expect(screen.getByText("1000 × 1400")).toBeVisible();
			expect(warnings(TALL.problem!)).toHaveLength(1);
			await user.click(screen.getByRole("button", { name: "Current" }));
			expect(screen.getByText("600 × 600")).toBeVisible();
			expect(warnings(TALL.problem!)).toEqual([]);
			await user.click(screen.getByRole("button", { name: "New" }));
			// Accepted: it is in the draft, failing or not.
			expect(reviewButton()).toBeEnabled();
		});
	});

	describe("the draft", () => {
		it("posts to preview the upload's token with every track of the album once and no edit", async () => {
			const { calls, user } = open({ preview: coverOnly(UPLOADED) });
			await shown();

			await user.upload(picker(), png());
			await fresh();
			await openReview(user);

			expect(posted(calls, PREVIEW).map(inPathOrder)).toEqual([
				{
					tracks: everyTrack(() => ({})),
					edits: [],
					swaps: [],
					cover: UPLOADED.cover,
					batch: false,
				},
			]);
		});

		// Whichever comes second must not push the first out of the draft.
		it.each<[string, boolean]>([
			["the edit made first", true],
			["the cover picked first", false],
		])(
			"sends a cover and a tag edit as one draft, with %s",
			async (_, editFirst) => {
				const tracks = albumTracks();
				const genres: Record<string, string[] | null> = Object.fromEntries(
					tracks.map((track) => [
						track.path,
						track.tags.genre ?? track.tags.TCON ?? null,
					]),
				);
				const { calls, user } = open();
				await shown();

				if (editFirst) await setPowerMetal(user);
				await user.upload(picker(), png());
				await fresh();
				if (!editFirst) await setPowerMetal(user);
				await openReview(user);

				// The edit has not taken the new image off the page either.
				expect(queryFresh()).not.toBeNull();
				expect(posted(calls, PREVIEW).map(inPathOrder)).toEqual([
					{
						tracks: everyTrack((path) => ({ Genre: genres[path]! })),
						edits: [
							{
								tracks: refsOf(tracks),
								set: { Genre: ["power metal"] },
								add: {},
								remove: {},
							},
						],
						swaps: [],
						cover: UPLOADED.cover,
						batch: false,
					},
				]);
			},
		);

		it("keeps the last image where two are picked: one new cover on the page, and its token in the draft", async () => {
			const { calls, uploads, user } = open({
				preview: coverOnly(TALL),
				uploads: [answers(UPLOADED), answers({ cover: "b7e1", ...TALL })],
			});
			await shown();

			await user.upload(picker(), png());
			await fresh();
			await user.upload(picker(), webp());
			await screen.findByText("1000 × 1400");

			expect(uploads.map((upload) => upload.type)).toEqual([
				"image/png",
				"image/webp",
			]);
			expect(screen.getAllByRole("img", { name: "New cover" })).toHaveLength(1);
			expect(screen.queryByText("1200 × 1200")).toBeNull();
			await openReview(user);
			expect(posted(calls, PREVIEW).map((draft) => draft.cover)).toEqual([
				"b7e1",
			]);
		});

		it("drops the new cover on Discard changes, and the next draft carries none", async () => {
			const { calls, user } = open();
			await shown();
			await user.upload(picker(), png());
			await fresh();

			await user.click(screen.getByRole("button", { name: "Discard changes" }));

			await waitFor(() => expect(queryFresh()).toBeNull());
			expect(screen.queryByText("1200 × 1200")).toBeNull();
			expect(current()).toHaveAttribute("src", SMALL.url);
			expect(reviewButton()).toBeDisabled();

			// A cover that was only hidden would still go with the next edit.
			await setPowerMetal(user);
			await openReview(user);
			expect(posted(calls, PREVIEW).map((draft) => draft.cover)).toEqual([
				null,
			]);
		});
	});

	describe("an upload the server refuses", () => {
		it.each<[number, string, () => File]>([
			[400, NOT_AN_IMAGE, png],
			[
				415,
				WRONG_TYPE,
				() => new File(["BM bytes"], "cover.bmp", { type: "image/bmp" }),
			],
		])(
			"shows the %i's sentence as the card's error, with nothing in the draft and the current cover still there",
			async (status, sentence, file) => {
				open({ uploads: [refusal(status, sentence)] });
				await shown();
				// A picker that lists the four types would keep a BMP from the page in this test, as no browser's drop does.
				const user = userEvent.setup({ applyAccept: false });

				await user.upload(picker(), file());

				expect(await screen.findByRole("alert")).toHaveTextContent(sentence);
				expect(queryFresh()).toBeNull();
				expect(reviewButton()).toBeDisabled();
				expect(current()).toHaveAttribute("src", SMALL.url);
				expect(screen.getByText("480 × 480")).toBeVisible();
			},
		);

		it("takes a good image after a refusal, and the refusal's sentence goes", async () => {
			const { user } = open({
				uploads: [refusal(400, NOT_AN_IMAGE), answers(UPLOADED)],
			});
			await shown();
			await user.upload(picker(), png());
			await screen.findByText(NOT_AN_IMAGE, { exact: false });

			await user.upload(picker(), png());

			await fresh();
			expect(screen.queryByText(NOT_AN_IMAGE, { exact: false })).toBeNull();
			expect(reviewButton()).toBeEnabled();
		});
	});

	describe("the review", () => {
		it("says the cover is replaced, with the new size, and offers Save for a draft that changes nothing else", async () => {
			const { calls, user } = open({ preview: coverOnly(UPLOADED) });
			await shown();
			await user.upload(picker(), png());
			await fresh();

			const review = await openReview(user);

			expect(within(review).getByText(/1200 × 1200/)).toBeVisible();
			expect(review).toHaveTextContent(/cover/i);
			// No track changes, and still a change.
			expect(within(review).queryByText("Nothing changes")).toBeNull();
			const save = within(review).getByRole("button", { name: "Save" });
			expect(save).toBeEnabled();

			await user.click(save);

			await waitFor(() => expect(posted(calls, SAVE)).toHaveLength(1));
			expect(posted(calls, SAVE)).toEqual(posted(calls, PREVIEW));
			expect(posted(calls, SAVE)[0]!.cover).toBe(UPLOADED.cover);
		});

		it("shows the cover the album has and the one it will get side by side, each named", async () => {
			const { user } = open({ preview: coverOnly(UPLOADED) });
			await shown();
			await user.upload(picker(), png());
			const added = await fresh();

			const review = await openReview(user);

			const pictureOf = (caption: string) =>
				within(review)
					.getByText(caption)
					.closest("figure")
					?.querySelector("img")
					?.getAttribute("src");
			expect(pictureOf("Current cover")).toBe(SMALL.url);
			expect(pictureOf("Cover once saved")).toBe(added.getAttribute("src"));
		});

		it("shows only the new cover in the review where the album has none", async () => {
			const { user } = open({ cover: null, preview: coverOnly(UPLOADED) });
			await shown();
			await user.upload(picker(), png());
			await fresh();

			const review = await openReview(user);

			expect(within(review).getByText("Cover once saved")).toBeVisible();
			expect(within(review).queryByText("Current cover")).toBeNull();
		});

		it("shows the warning of a new cover that fails the cover test before Save, and Save is still offered", async () => {
			const { user } = open({
				cover: SQUARE,
				uploads: [answers({ cover: "b7e1", ...TALL })],
				preview: coverOnly(TALL),
			});
			await shown();
			await user.upload(picker(), png());
			await fresh();

			const review = await openReview(user);

			expect(within(review).getByText(/1000 × 1400/)).toBeVisible();
			expect(
				within(review).getByText(TALL.problem!, { exact: false }),
			).toBeVisible();
			expect(
				within(review).getByRole("button", { name: "Save" }),
			).toBeEnabled();
		});

		it("says nothing of the cover where the draft has no new one", async () => {
			const { user } = open({
				preview: {
					new_path: ECLIPTICA,
					problems: [],
					refused: [],
					cover: null,
				},
			});
			await shown();
			await setPowerMetal(user);

			const review = await openReview(user);

			expect(review).not.toHaveTextContent(/cover/i);
		});
	});

	describe("a save", () => {
		const unusable = () => {
			const input = screen.queryByLabelText<HTMLInputElement>("Replace cover");
			expect(input === null || input.disabled).toBe(true);
		};

		// The page over a library a case can change while it is open.
		function openOver(library: { album: LibraryAlbum; job: LibraryJob }) {
			const page = openAlbum({
				clock: true,
				shelves: {
					albums: { [ECLIPTICA]: () => Response.json(library.album) },
				},
				writes: {
					preview: previewOf(coverOnly(UPLOADED)),
					job: () => Response.json(library.job),
				},
			});
			return { ...page, uploads: serveUploads([answers(UPLOADED)]) };
		}

		it("offers no Replace cover while a save runs, and uploads nothing dropped on the cover", async () => {
			const { uploads } = openOver({
				album: albumOf({ job: { id: JOB, state: "writing" } }),
				job: jobOf("writing"),
			});
			await screen.findByRole("heading", { name: /Ecliptica/ });
			await throughPolls(() =>
				expect(screen.getByText("writing")).toBeInTheDocument(),
			);

			unusable();
			drop(current(), png());
			// Long enough for a second poll, so an upload on its way has gone.
			await vi.advanceTimersByTimeAsync(2_100);

			expect(uploads).toEqual([]);
			expect(queryFresh()).toBeNull();
		});

		it("shows the album as served again once a save with a cover is done: the new cover as the current one, and no draft", async () => {
			const library = { album: albumOf(), job: jobOf("waiting") };
			const page = openOver(library);
			await shown();
			const before = current().getAttribute("src");
			await page.user.upload(picker(), png());
			await fresh();
			const review = await openReview(page.user);
			await page.user.click(
				within(review).getByRole("button", { name: "Save" }),
			);
			await throughPolls(() =>
				expect(screen.getByText("waiting")).toBeInTheDocument(),
			);
			unusable();
			const gets = albumGets(page.calls);

			// The server wrote cover.jpg: the same address, another picture.
			library.album = albumOf({
				cover: {
					...SMALL,
					width: 1200,
					height: 1200,
					passes: true,
					problem: null,
				},
			});
			library.job = jobOf("done");

			await throughPolls(() =>
				expect(albumGets(page.calls)).toBeGreaterThan(gets),
			);
			await throughPolls(() => expect(queryFresh()).toBeNull());
			await throughPolls(() =>
				expect(screen.queryByText("480 × 480")).toBeNull(),
			);
			expect(screen.getByText("1200 × 1200")).toBeVisible();
			expect(warnings(SMALL.problem!)).toEqual([]);
			await throughPolls(() => expect(picker()).toBeEnabled());
			expect(reviewButton()).toBeDisabled();

			// A browser shows the picture it already has for an address it has
			// seen. The address must differ for the new cover.jpg to be drawn.
			const after = current().getAttribute("src")!;
			expect(new URL(after, "http://localhost").pathname).toBe(SMALL.url);
			expect(after).not.toBe(before);
		});
	});
});
