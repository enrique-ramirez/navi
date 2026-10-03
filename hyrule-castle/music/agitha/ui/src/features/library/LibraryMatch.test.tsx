import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
	LibraryAlbum,
	LibraryJob,
	MatchRef,
	MatchRequest,
} from "@/shared/api/types";
import { albumView } from "@/test/albumView";
import type { Call } from "@/test/fakeFetch";
import uploadFixture from "@/test/fixtures/library/cover-upload.json";
import {
	ECLIPTICA,
	fixtures,
	JOB,
	jobOf,
	posted,
	refusal,
	requested,
} from "@/test/library";
import {
	albumGets,
	albumOf,
	closeAlbum,
	EIGHTH,
	openAlbum,
	REPLICA,
	reviewButton,
	setPowerMetal,
	shown,
	shownWithTags,
	tag,
	throughPolls,
	usable,
} from "@/test/libraryAlbum";
import { screen, waitFor } from "@/test/render";
import {
	FLAGGED,
	openOrdered,
	selectOnly,
	swapOffered,
} from "@/test/trackOrder";

const MATCH = "/api/library/match";
const COVERS = "/api/library/covers";
const MATCH_NAME = "Match to MusicBrainz";
const REVIEW_LINK = "Open the review";

// A match the server has only now made, and one that was open before the
// click. The second is not album 01, so a page that writes `01` itself is caught.
const NEW: MatchRef = { drop: "20261002-033400", n: "01" };
const OPEN: MatchRef = { drop: "20260930-221500", n: "02" };

const reviewPage = ({ drop, n }: MatchRef) => `/drops/${drop}/albums/${n}`;
const reviewApi = (ref: MatchRef) => `/api${reviewPage(ref)}`;

type Respond = () => Response | Promise<Response>;

interface Served {
	/** What `POST /api/library/match` answers. With none, 404 and no sentence. */
	match?: Respond;
	/** The one review whose route answers, as a match of Ecliptica. Any other is 404. */
	review?: MatchRef;
}

// `openAlbum` takes no route of the match, so they are laid over its fake once
// the page is mounted, as `openOrdered` lays the order route. The calls join
// the page's own list. A cover upload is answered here too: the fake under
// this one cannot read a jsdom `File`.
function serve<Page extends { calls: Call[] }>(
	page: Page,
	{ match, review }: Served = {},
): Page {
	const under = globalThis.fetch;
	vi.stubGlobal(
		"fetch",
		async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = new URL(
				String(input instanceof Request ? input.url : input),
				"http://localhost",
			);
			const method = (
				init?.method ?? (input instanceof Request ? input.method : "GET")
			).toUpperCase();
			const route = `${method} ${url.pathname}`;

			let answer: Respond | undefined;
			if (route === `POST ${MATCH}`)
				answer = match ?? (() => new Response(null, { status: 404 }));
			else if (route === `PUT ${COVERS}`)
				answer = () => Response.json(uploadFixture);
			else if (review && route === `GET ${reviewApi(review)}`)
				answer = () =>
					Response.json(albumView({ ...review, replaces: ECLIPTICA }));
			if (!answer) return under(input, init);

			page.calls.push({
				method,
				url: url.href,
				body: typeof init?.body === "string" ? init.body : "",
			});
			return answer();
		},
	);
	return page;
}

const made = (ref: MatchRef, status: 200 | 201): Respond => {
	return () => Response.json(ref, { status });
};

const matchButton = () => screen.getByRole("button", { name: MATCH_NAME });

const matchPosts = (calls: Call[]) => posted<MatchRequest>(calls, MATCH);

// Every request for a review page's album, whichever drop it names.
const reviewGets = (calls: Call[]) =>
	requested(calls).filter((each) => each.startsWith("GET /api/drops/"));

const canBeUsed = (control: HTMLElement) =>
	!(control as HTMLButtonElement | HTMLInputElement).disabled &&
	control.getAttribute("aria-disabled") !== "true";

// The controls `usable()` does not list: the cover picker, the selection's
// Swap, a flagged pair's Swap, and the match. By name, those that can be used.
// A name is listed once: a flagged pair has its Swap on both of its rows.
function alsoUsable() {
	const names = [
		...screen.queryAllByLabelText("Replace cover"),
		...screen.queryAllByRole("button", { name: /^Swap\b/ }),
		...screen.queryAllByRole("button", { name: MATCH_NAME }),
	]
		.filter(canBeUsed)
		.map(
			(control) => control.getAttribute("aria-label") || control.textContent,
		);
	return [...new Set(names)].sort();
}

// Ecliptica as its last two tracks, the pair `order.json` flags. Both open
// selected, so a page that may be edited offers the selection's Swap at once.
function flaggedPair(over: Partial<LibraryAlbum> = {}) {
	const album = albumOf(over);
	album.tracks = album.tracks.filter((track) =>
		[EIGHTH, REPLICA].includes(track.path),
	);
	return album;
}

const openPair = (over: Partial<LibraryAlbum>, served: Served = {}) =>
	serve(
		openOrdered({
			order: FLAGGED,
			shelves: { albums: { [ECLIPTICA]: flaggedPair(over) } },
		}),
		served,
	);

type Page = ReturnType<typeof openAlbum>;

// The three ways a page comes to hold a draft.
const DRAFTS: [string, (page: Page) => Promise<void>][] = [
	["an edit", ({ user }) => setPowerMetal(user)],
	[
		"a swap",
		async ({ user }) => {
			await selectOnly(user, "8th Commandment", "Replica");
			await user.click(swapOffered()!);
		},
	],
	[
		"a new cover",
		async ({ user }) => {
			await user.upload(
				screen.getByLabelText<HTMLInputElement>("Replace cover"),
				new File(["PNG bytes of the reissue"], "reissue.png", {
					type: "image/png",
				}),
			);
			await screen.findByRole("img", { name: "New cover" });
		},
	],
];

describe("Match to MusicBrainz on the album page", () => {
	const createObjectURL = URL.createObjectURL;
	const revokeObjectURL = URL.revokeObjectURL;

	beforeEach(() => {
		// jsdom has no object URLs, and the cover card makes one for a new cover.
		URL.createObjectURL = vi.fn(() => "blob:http://localhost/picked");
		URL.revokeObjectURL = vi.fn();
	});

	afterEach(() => {
		closeAlbum();
		// `closeAlbum` drops the routes laid here only through its own fake's restore.
		vi.unstubAllGlobals();
		URL.createObjectURL = createObjectURL;
		URL.revokeObjectURL = revokeObjectURL;
	});

	describe("starting a match", () => {
		it("posts the album's library path and opens the review page of the match the server made, without asking", async () => {
			const page = serve(openAlbum(), { match: made(NEW, 201), review: NEW });
			await shown();
			expect(matchButton()).toBeEnabled();

			await page.user.click(matchButton());

			await waitFor(() => expect(page.place()).toBe(reviewPage(NEW)));
			await waitFor(() =>
				expect(requested(page.calls)).toContain(`GET ${reviewApi(NEW)}`),
			);
			// The path as the album route names it, spaces and brackets unescaped, and once.
			expect(matchPosts(page.calls)).toEqual([{ path: ECLIPTICA }]);
			expect(screen.queryByRole("alertdialog")).toBeNull();
		});

		it("opens the review page of the match that was already open where the server answers 200 with it", async () => {
			const page = serve(openAlbum(), { match: made(OPEN, 200), review: OPEN });
			await shown();

			await page.user.click(matchButton());

			await waitFor(() => expect(page.place()).toBe(reviewPage(OPEN)));
			await waitFor(() =>
				expect(requested(page.calls)).toContain(`GET ${reviewApi(OPEN)}`),
			);
			expect(matchPosts(page.calls)).toEqual([{ path: ECLIPTICA }]);
		});

		// The album the page loaded had no match. Shown again from what the page
		// remembers, it would take edits the server refuses until the answer lands.
		it("asks for the album again once a match has started, and never offers it for editing from memory on the way back", async () => {
			const now = { album: albumOf() };
			const page = serve(
				openAlbum({
					shelves: {
						albums: { [ECLIPTICA]: () => Response.json(now.album) },
					},
				}),
				{
					match: () => {
						now.album = albumOf({ match: NEW });
						return Response.json(NEW, { status: 201 });
					},
					review: NEW,
				},
			);
			await shown();
			const before = albumGets(page.calls);
			await page.user.click(matchButton());
			await waitFor(() => expect(page.place()).toBe(reviewPage(NEW)));
			await waitFor(() =>
				expect(requested(page.calls)).toContain(`GET ${reviewApi(NEW)}`),
			);

			// Every control the album was ever offered with from here on.
			const offered = new Set<string>();
			const watch = new MutationObserver(() => {
				for (const button of document.querySelectorAll("button"))
					if (button.textContent === MATCH_NAME && !button.disabled)
						offered.add(MATCH_NAME);
			});
			watch.observe(document.body, {
				subtree: true,
				childList: true,
				attributes: true,
			});
			await act(async () => {
				page.router.history.back();
			});

			expect(
				await screen.findByRole("link", { name: REVIEW_LINK }),
			).toHaveAttribute("href", reviewPage(NEW));
			await screen.findByRole("heading", { name: /Ecliptica/ });
			watch.disconnect();
			expect(page.place()).toBe(`/library/${ECLIPTICA}`);
			expect(albumGets(page.calls)).toBeGreaterThan(before);
			expect([...offered]).toEqual([]);
			expect(usable()).toEqual([]);
			expect(alsoUsable()).toEqual([]);
		});

		it.each([
			[409, "the album is being saved"],
			// The server words its own 404; the page shows whichever sentence it is served.
			[404, "No such album in the library."],
		])(
			"shows the sentence of a %i refusal as served and stays on the album",
			async (status, sentence) => {
				const page = serve(openAlbum(), {
					match: refusal(status, sentence),
					review: NEW,
				});
				await shown();

				await page.user.click(matchButton());

				expect(await screen.findByText(sentence)).toBeVisible();
				expect(matchPosts(page.calls)).toEqual([{ path: ECLIPTICA }]);
				expect(page.place()).toBe(`/library/${ECLIPTICA}`);
				expect(reviewGets(page.calls)).toEqual([]);
			},
		);
	});

	describe("with a draft on the page", () => {
		it.each(DRAFTS)(
			"is disabled once the page holds %s",
			async (_kind, draft) => {
				const page = serve(openAlbum(), { match: made(NEW, 201), review: NEW });
				await shown();
				expect(matchButton()).toBeEnabled();

				await draft(page);

				// Review changes is enabled only over a draft.
				await waitFor(() => expect(reviewButton()).toBeEnabled());
				expect(matchButton()).toBeDisabled();
				expect(matchPosts(page.calls)).toEqual([]);
			},
		);

		it("is enabled again once the draft is discarded", async () => {
			const page = serve(openAlbum(), { match: made(NEW, 201), review: NEW });
			await shown();
			await setPowerMetal(page.user);
			await waitFor(() => expect(matchButton()).toBeDisabled());

			await page.user.click(
				screen.getByRole("button", { name: "Discard changes" }),
			);

			await waitFor(() => expect(reviewButton()).toBeDisabled());
			expect(matchButton()).toBeEnabled();
		});
	});

	describe("an album with a match open", () => {
		it("offers the cover picker, both swaps and the match on the same album while no match is open", async () => {
			// The other half of the read-only case below: every name it looks for
			// is on the page when the album may be edited.
			const page = openPair({ match: null });
			await shown();
			await page.orderSettled();

			expect(alsoUsable()).toEqual([
				MATCH_NAME,
				"Replace cover",
				"Swap",
				"Swap 03 and 04",
			]);
		});

		it("is read-only, says it is open in review and links to that review", async () => {
			const page = openPair({ match: OPEN }, { review: OPEN });
			await screen.findByRole("heading", { name: /Ecliptica/ });
			const link = await screen.findByRole("link", { name: REVIEW_LINK });
			await page.orderSettled();

			expect(link).toHaveAttribute("href", reviewPage(OPEN));
			expect(screen.getByText(/open in review/i)).toBeVisible();
			// The tracks are still listed; nothing that edits them can be used.
			expect(
				screen.getByRole("button", { name: "Play Replica" }),
			).toBeInTheDocument();
			expect(usable()).toEqual([]);
			expect(alsoUsable()).toEqual([]);
			expect(matchPosts(page.calls)).toEqual([]);
		});

		// Read-only is not empty: what the files hold is still worth reading
		// while the match is open, over the selection.
		it("still shows the tags of its tracks with their values, and nothing to edit them by", async () => {
			const page = openPair({ match: OPEN }, { review: OPEN });
			await shownWithTags();
			await page.orderSettled();

			// 8th Commandment carries the genre and the ripper frame; Replica neither.
			expect(tag("Genre")).toHaveTextContent("power metal 1/2");
			expect(tag("Album")).toHaveTextContent("Ecliptica");
			expect(tag("TXXX:RIPPER")).toHaveTextContent("EAC 0.99");
			expect(usable()).toEqual([]);
			expect(alsoUsable()).toEqual([]);
		});

		it("opens the review page from that link", async () => {
			const page = openPair({ match: OPEN }, { review: OPEN });

			await page.user.click(
				await screen.findByRole("link", { name: REVIEW_LINK }),
			);

			await waitFor(() => expect(page.place()).toBe(reviewPage(OPEN)));
			await waitFor(() =>
				expect(requested(page.calls)).toContain(`GET ${reviewApi(OPEN)}`),
			);
			expect(screen.queryByRole("alertdialog")).toBeNull();
		});

		it("still plays a track", async () => {
			const page = openPair({ match: OPEN }, { review: OPEN });
			await screen.findByRole("link", { name: REVIEW_LINK });

			await page.user.click(
				screen.getByRole("button", { name: "Play Replica" }),
			);

			const stop = await screen.findByRole("button", { name: "Stop Replica" });
			expect(page.played).toEqual([
				fixtures.album.tracks.find((track) => track.path === REPLICA)!
					.audio_url,
			]);
			// The player is one for the page and outlives the case.
			await page.user.click(stop);
			await screen.findByRole("button", { name: "Play Replica" });
		});
	});

	describe("while a save runs", () => {
		it("cannot be used, and is offered again once the save is done", async () => {
			// A save from before the page opened: the page holds no draft, so only
			// the save keeps the match back.
			const now: { album: LibraryAlbum; job: LibraryJob } = {
				album: albumOf({ job: { id: JOB, state: "writing" } }),
				job: jobOf("writing"),
			};
			const page = serve(
				openAlbum({
					clock: true,
					shelves: {
						albums: { [ECLIPTICA]: () => Response.json(now.album) },
					},
					writes: { job: () => Response.json(now.job) },
				}),
				{ match: made(NEW, 201), review: NEW },
			);
			await screen.findByRole("heading", { name: /Ecliptica/ });
			await throughPolls(() =>
				expect(screen.getByText("writing")).toBeInTheDocument(),
			);

			expect(alsoUsable()).not.toContain(MATCH_NAME);

			now.album = albumOf({ job: { id: JOB, state: "done" } });
			now.job = jobOf("done");

			await throughPolls(() => expect(matchButton()).toBeEnabled());
			expect(matchPosts(page.calls)).toEqual([]);
		});
	});
});
