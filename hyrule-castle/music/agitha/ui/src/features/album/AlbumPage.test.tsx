import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	createMemoryHistory,
	createRootRoute,
	createRoute,
	createRouter,
	RouterProvider,
} from "@tanstack/react-router";
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AcceptDecision, AlbumView, Hold } from "@/shared/api/types";
import { ALBUM_URL, albumView, DROP, flacFirst } from "@/test/albumView";
import { type Call, fakeFetch } from "@/test/fakeFetch";
import { screen, userEvent, waitFor, within } from "@/test/render";

import { AlbumPage } from "./AlbumPage";

// How the album page shows a `missing` hold.

// The details exactly as `musiclib batch identify --drop-unreadable` words them.
const TOLD_WITH_FILE: Hold = {
	kind: "missing",
	detail:
		'track 3, "It Was Always You": 03 It Was Always You.mp3 could be it, but it cannot be read',
};
const TOLD_WITHOUT_FILE: Hold = {
	kind: "missing",
	detail: 'track 3, "It Was Always You"',
};
const UNPLACED = (file: string): Hold => ({
	kind: "missing",
	detail: `a track is missing: ${file} cannot be read`,
});
const FOLDER: Hold = {
	kind: "missing",
	detail: "tracks may be missing: Scans cannot be read",
};

// Holds of other kinds, sent before the `missing` one so the page has to move it up.
const STATUS: Hold = {
	kind: "status",
	detail: "unidentified: no candidate matched",
};
const VALIDATION: Hold = { kind: "validation", detail: "subfolder: covers" };

const TRACK_3 = 'Track 3, "It Was Always You", is missing';
const COULD_BE_3 =
	"03 It Was Always You.mp3 could be it, but it cannot be read";
const DISCARD =
	"Discard this album and drop it again with a good copy of the file.";

// A view as the server sends it: the holds in the engine's order, and Approve refused
// by the first `missing` hold (`agitha/state.py` puts it first).
function viewWith(missing: Hold[]): AlbumView {
	const view = albumView();
	view.preview!.state = "held";
	view.preview!.holds = [STATUS, VALIDATION, ...missing];
	const [first] = missing;
	if (first) {
		view.approvable = {
			ok: false,
			reason: `held: ${first.kind}: ${first.detail}`,
			code: "held",
			hold: first,
		};
	}
	return view;
}

// The profile's helper mounts the page at a catch-all route, which gives it no
// `drop` and `n`; this router gives it the album route's parameters (as in Strays.test.tsx).
// A case that looks at what the page keeps of other routes passes its own client.
function renderAlbumPage(
	page: typeof AlbumPage = AlbumPage,
	queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	}),
) {
	const rootRoute = createRootRoute();
	const album = createRoute({
		getParentRoute: () => rootRoute,
		path: "drops/$drop/albums/$n",
		component: page,
	});
	const router = createRouter({
		routeTree: rootRoute.addChildren([album]),
		history: createMemoryHistory({
			initialEntries: [`/drops/${DROP}/albums/01`],
		}),
	});
	return render(
		<QueryClientProvider client={queryClient}>
			<RouterProvider router={router} />
		</QueryClientProvider>,
	);
}

// The one alert on the page. The review bar raises one only for a refused request,
// and these views send none, so a second alert is the page splitting the warning.
async function theAlert(): Promise<HTMLElement> {
	const alerts = await screen.findAllByRole("alert");
	expect(alerts, "alerts on the page").toHaveLength(1);
	return alerts[0]!;
}

// The innermost elements under `root` whose text contains `text`, however the
// sentence is split across markup.
function holding(root: HTMLElement, text: string): HTMLElement[] {
	return [root, ...root.querySelectorAll<HTMLElement>("*")].filter(
		(element) =>
			element.textContent?.includes(text) &&
			![...element.children].some((child) => child.textContent?.includes(text)),
	);
}

function shows(root: HTMLElement, text: string) {
	const found = holding(root, text);
	expect(found, `"${text}" shown`).not.toEqual([]);
	for (const element of found) expect(element).toBeVisible();
}

const precedes = (a: Node, b: Node) =>
	Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

// The holds list, once the page has rendered it with the status and validation holds.
const holdsList = () => screen.findByRole("list", { name: "Holds" });

// The kind's own name as a label: `missing`, `missing:` or `Missing: ...` at the head of
// an element. The sentence's own "is missing" does not start one.
const kindLabels = (root: HTMLElement) =>
	[root, ...root.querySelectorAll<HTMLElement>("*")].filter((element) =>
		/^missing\b/i.test(element.textContent?.trim() ?? ""),
	);

describe("the album page, for an album with a track it cannot read", () => {
	let restore: (() => void) | undefined;

	afterEach(() => {
		restore?.();
		restore = undefined;
	});

	function serve(view: AlbumView) {
		restore = fakeFetch({
			[`GET ${ALBUM_URL}`]: () => Response.json(view),
		}).restore;
		renderAlbumPage();
	}

	it("raises an alert naming the missing track and the file that could be it", async () => {
		serve(viewWith([TOLD_WITH_FILE]));

		const alert = await theAlert();

		shows(alert, TRACK_3);
		shows(alert, COULD_BE_3);
	});

	it("puts the alert above every other hold, and still lists those", async () => {
		serve(viewWith([TOLD_WITH_FILE]));

		const alert = await theAlert();
		const list = await holdsList();

		for (const other of [STATUS.detail, VALIDATION.detail]) {
			const [shown] = holding(list, other);
			expect(shown, `"${other}" in the holds list`).toBeDefined();
			expect(precedes(alert, shown!), `alert before "${other}"`).toBe(true);
		}
	});

	it("does not repeat the missing hold in the holds list, nor label anything with the kind's name", async () => {
		serve(viewWith([TOLD_WITH_FILE]));

		const alert = await theAlert();
		const list = await holdsList();

		expect(list).not.toHaveTextContent("It Was Always You");
		expect(list).not.toHaveTextContent("cannot be read");
		expect(kindLabels(alert), "kind labels in the alert").toEqual([]);
		expect(kindLabels(list), "kind labels in the holds list").toEqual([]);
	});

	it("tells the owner to discard the album and drop a good copy, and offers Discard", async () => {
		serve(viewWith([TOLD_WITH_FILE]));

		const alert = await theAlert();

		shows(alert, DISCARD);
		expect(screen.getByRole("button", { name: "Discard" })).toBeEnabled();
	});

	it("names a track the engine could tell with no file to point at, and no 'could be it' line", async () => {
		serve(viewWith([TOLD_WITHOUT_FILE]));

		const alert = await theAlert();

		shows(alert, TRACK_3);
		shows(alert, DISCARD);
		expect(alert).not.toHaveTextContent("could be it");
	});

	// The track's words end at the closing quote, not at the first colon: a page that
	// splits on `:` like the holds list's topics cuts this title in two.
	it("keeps a title with a colon in it whole", async () => {
		serve(
			viewWith([
				{
					kind: "missing",
					detail:
						'track 7, "Interlude: Rain": 07 Interlude.mp3 could be it, but it cannot be read',
				},
			]),
		);

		const alert = await theAlert();

		shows(alert, 'Track 7, "Interlude: Rain", is missing');
		shows(alert, "07 Interlude.mp3 could be it, but it cannot be read");
	});

	// English reads the same as the engine's wording with a capital; the Spanish case below
	// is what tells the page's own sentence from the detail passed through.
	it("says in its own words that a track is missing where the engine could not place the file", async () => {
		serve(viewWith([UNPLACED("04.mp3")]));

		const alert = await theAlert();

		shows(alert, "A track is missing: 04.mp3 cannot be read");
		shows(alert, DISCARD);
	});

	it("says in its own words that tracks may be missing where a folder could not be listed", async () => {
		serve(viewWith([FOLDER]));

		const alert = await theAlert();

		shows(alert, "Tracks may be missing: Scans cannot be read");
	});

	// Both share the topic `a track is missing`; the holds list folds such holds into
	// one "on 2 tracks" line behind a closed <details>, which would hide the file names.
	it("shows every missing hold in the one alert, each in full", async () => {
		serve(
			viewWith([
				UNPLACED("03 It Was Always You.mp3"),
				UNPLACED("15 Hidden Track.mp3"),
				FOLDER,
			]),
		);

		const alert = await theAlert();

		shows(alert, "A track is missing: 03 It Was Always You.mp3 cannot be read");
		shows(alert, "A track is missing: 15 Hidden Track.mp3 cannot be read");
		shows(alert, "Tracks may be missing: Scans cannot be read");
		expect(alert).not.toHaveTextContent("on 2 tracks");
	});

	// The engine sends `track 3, ""` for a track the release gives no title.
	it("reads a track with no title without an empty pair of quotes", async () => {
		serve(
			viewWith([
				{ kind: "missing", detail: 'track 3, ""' },
				{
					kind: "missing",
					detail: 'track 5, "": 05 x.mp3 could be it, but it cannot be read',
				},
			]),
		);

		const alert = await theAlert();

		shows(alert, "Track 3 is missing");
		shows(alert, "Track 5 is missing");
		shows(alert, "05 x.mp3 could be it, but it cannot be read");
		expect(alert).not.toHaveTextContent('""');
	});

	it("raises no alert for an album with no missing hold", async () => {
		serve(viewWith([]));

		// The list is rendered with the rest of the page, so the page has settled.
		await holdsList();

		expect(screen.queryAllByRole("alert")).toEqual([]);
		expect(screen.queryByText(DISCARD)).toBeNull();
	});
});

// An album the owner has accepted, so an edit turns Approve into Save & re-preview.
const ACCEPTED: AcceptDecision = {
	action: "accept",
	release_id: "6f1a2b3c-0000-4000-8000-000100000001",
	edits: {},
	game: null,
	cover: null,
};

const POSITIONS = ["1-1", "1-2", "1-3"];

const posts = (calls: Call[], path: string) =>
	calls.filter(
		(call) =>
			call.method === "POST" &&
			new URL(call.url).pathname === `${ALBUM_URL}/${path}`,
	);

// The engine moves the artist folder for the neutral field `albumartist`, and
// converts what is typed there. An edit under a file's own key (`TPE2` in an
// MP3) is laid over it as written. A saved review can hold the album artist
// under the own key, and it would win over a typed one.
describe("the album artist on the review page", () => {
	let fake: ReturnType<typeof fakeFetch> | undefined;

	afterEach(() => {
		fake?.restore();
		fake = undefined;
	});

	function serve(view: AlbumView) {
		fake = fakeFetch({
			[`GET ${ALBUM_URL}`]: () => Response.json(view),
			[`POST ${ALBUM_URL}/decision`]: () => Response.json({ state: "queued" }),
			"GET /api/drops": () => Response.json([]),
		});
		renderAlbumPage();
		return userEvent.setup();
	}

	// A view whose saved decision names the album artist under `TPE2`, on every track.
	const savedUnderOwnKey = () =>
		albumView({
			decision: {
				...ACCEPTED,
				edits: Object.fromEntries(
					POSITIONS.map((position) => [position, { TPE2: ["Raw A"] }]),
				),
			},
		});

	const table = (name: string) => screen.findByRole("table", { name });

	function rowIn(tags: HTMLElement, tag: string) {
		const row = within(tags)
			.getAllByRole("row")
			.find(
				(each) =>
					within(each)
						.queryByRole("rowheader")
						?.textContent?.replace("edited by you", "") === tag,
			);
		if (!row) throw new Error(`no row for ${tag}`);
		return row;
	}

	const albumArtist = (tags: HTMLElement) =>
		within(tags).getByRole("textbox", { name: "New Album artist" });

	async function typeAlbumArtist(
		user: ReturnType<typeof userEvent.setup>,
		tags: HTMLElement,
		name: string,
	) {
		await user.clear(albumArtist(tags));
		await user.type(albumArtist(tags), `${name}{Enter}`);
	}

	async function saved(
		user: ReturnType<typeof userEvent.setup>,
	): Promise<AcceptDecision> {
		await user.click(screen.getByRole("button", { name: "Save & re-preview" }));
		await waitFor(() => expect(posts(fake!.calls, "decision")).toHaveLength(1));
		return JSON.parse(posts(fake!.calls, "decision")[0]!.body);
	}

	it("shows a typed album artist over one saved under the files' own key, and sends it under the neutral name with the saved edit gone", async () => {
		const user = serve(savedUnderOwnKey());
		const tags = await table("Tags on all 3 tracks");
		expect(albumArtist(tags)).toHaveValue("Raw A");

		await typeAlbumArtist(user, tags, "Typed B");

		expect(albumArtist(tags)).toHaveValue("Typed B");
		const decision = await saved(user);
		// `TPE2` is absent, and not `null`: a `null` there removes the tag.
		expect(decision.edits).toEqual(
			Object.fromEntries(
				POSITIONS.map((position) => [position, { albumartist: ["Typed B"] }]),
			),
		);
	});

	it("leaves no album artist edit after Undo, and the row shows what the plan writes", async () => {
		const user = serve(savedUnderOwnKey());
		const tags = await table("Tags on all 3 tracks");
		await typeAlbumArtist(user, tags, "Typed B");

		await user.click(
			within(rowIn(tags, "Album artist")).getByRole("button", {
				name: "Undo your edit of Album artist",
			}),
		);

		expect(albumArtist(tags)).toHaveValue("Clean Band");
		expect(
			within(rowIn(tags, "Album artist")).queryByText("edited by you"),
		).toBeNull();
		// The saved edit went when the name was typed, and Undo took the typed one.
		const decision = await saved(user);
		expect(decision.edits).toEqual({});
	});

	// The first track is a FLAC, whose own key is the neutral name. The MP3
	// after it holds a saved edit under `TPE2`, which goes by that track's own
	// format and not by the first file's. The third track is not typed on.
	it("sends an album artist typed on a track under the neutral name where a FLAC comes before the MP3s, and takes that MP3's saved TPE2 edit out", async () => {
		const view = flacFirst(albumView());
		view.decision = {
			...ACCEPTED,
			edits: { "1-2": { TPE2: ["Raw A"] }, "1-3": { TPE2: ["Raw A"] } },
		};
		const user = serve(view);
		const tracks = await table("Tracks");

		await user.click(within(tracks).getByRole("button", { name: /^Two/ }));
		const mp3 = await table("Tags of Two");
		expect(albumArtist(mp3)).toHaveValue("Raw A");
		await typeAlbumArtist(user, mp3, "Typed B");
		expect(albumArtist(mp3)).toHaveValue("Typed B");
		// One tag, one row: the neutral name is not listed as a tag of the MP3's own.
		expect(
			within(mp3)
				.getAllByRole("rowheader")
				.map((header) => header.textContent?.replace("edited by you", "")),
		).not.toContain("albumartist");

		await user.click(within(tracks).getByRole("button", { name: /^One/ }));
		const flac = await table("Tags of One");
		await typeAlbumArtist(user, flac, "Typed C");
		expect(albumArtist(flac)).toHaveValue("Typed C");

		const decision = await saved(user);
		expect(decision.edits).toEqual({
			"1-1": { albumartist: ["Typed C"] },
			"1-2": { albumartist: ["Typed B"] },
			"1-3": { TPE2: ["Raw A"] },
		});
	});
});

// The library's listings are kept for a while once read. An album that lands
// changes them, and one that is still being applied has changed nothing yet:
// a listing read meanwhile would be kept as fresh, without the album.
describe("the library's listings as the review page keeps them", () => {
	let fake: ReturnType<typeof fakeFetch> | undefined;

	afterEach(() => {
		fake?.restore();
		fake = undefined;
		vi.useRealTimers();
	});

	const LISTING = {
		root: "/srv/music/library",
		readable: true,
		letters: ["C"],
	};

	// A page whose client already holds the library's first listing, and the
	// album's route answering whatever `served.view` is when it is asked.
	function open(view: AlbumView, routes: Parameters<typeof fakeFetch>[0]) {
		// The page asks again every 2 s while the album is being applied.
		vi.useFakeTimers({ shouldAdvanceTime: true });
		const served = { view };
		fake = fakeFetch({
			[`GET ${ALBUM_URL}`]: () => Response.json(served.view),
			"GET /api/drops": () => Response.json([]),
			...routes,
		});
		const client = new QueryClient({
			defaultOptions: { queries: { retry: false } },
		});
		client.setQueryData(["library"], LISTING);
		renderAlbumPage(AlbumPage, client);
		return {
			served,
			user: userEvent.setup({ advanceTimers: vi.advanceTimersByTime }),
			// Whether the listing must be asked for again before it is shown.
			outdated: () => client.getQueryState(["library"])?.isInvalidated,
		};
	}

	const landed = (view: AlbumView): AlbumView => ({
		...view,
		state: "in the library",
		approvable: {
			ok: false,
			reason: "in the library",
			code: "in-library",
			hold: null,
		},
	});

	it("keeps them while an approved album is being applied, and asks for them again once it is in the library", async () => {
		const ready = albumView({ decision: ACCEPTED });
		const page = open(ready, {
			[`POST ${ALBUM_URL}/approve`]: () => {
				page.served.view = { ...ready, state: "applying", busy: true };
				return Response.json(
					{
						state: "applying",
						path: null,
						error: null,
						step: null,
						file: null,
					},
					{ status: 202 },
				);
			},
		});

		await page.user.click(
			await screen.findByRole("button", { name: "Approve" }),
		);
		await waitFor(() => expect(posts(fake!.calls, "approve")).toHaveLength(1));
		// The page has drawn the answer that followed the 202.
		expect(await screen.findByText("applying")).toBeVisible();
		expect(page.outdated()).toBe(false);

		page.served.view = landed(ready);
		await vi.advanceTimersByTimeAsync(2_100);

		expect(
			await screen.findByRole("heading", { name: /is in the library$/ }),
		).toBeVisible();
		await waitFor(() => expect(page.outdated()).toBe(true));
	});

	it("asks for them again once Move into the library has put the album there", async () => {
		const stuck = albumView({
			decision: ACCEPTED,
			state: "written, not moved",
			error: "the disk is full",
		});
		const page = open(stuck, {
			[`POST ${ALBUM_URL}/move`]: () => {
				page.served.view = landed(stuck);
				return Response.json({ state: "in the library" });
			},
		});
		const move = await screen.findByRole("button", {
			name: "Move into the library",
		});
		expect(page.outdated()).toBe(false);

		await page.user.click(move);

		expect(
			await screen.findByRole("heading", { name: /is in the library$/ }),
		).toBeVisible();
		await waitFor(() => expect(page.outdated()).toBe(true));
	});
});

// The Spanish catalogue as shipped, so the case below checks the real phrases.
const SPANISH = import.meta.glob<Record<string, unknown>>(
	"/public/locales/es.json",
	{ eager: true, import: "default" },
)["/public/locales/es.json"];

function spanish(key: string): string {
	const phrase = SPANISH?.[key];
	if (typeof phrase !== "string") throw new Error(`es.json has no ${key}`);
	return phrase;
}

describe("the album page's missing-track alert, in Spanish", () => {
	afterEach(() => {
		vi.restoreAllMocks();
		vi.unstubAllGlobals();
	});

	// The three forms the engine words for itself: the "could be it" tail, a file it could
	// not place and a folder it could not list. The engine never sends the first beside the
	// second for one album; the page reads each hold on its own, so one view holds all three.
	it("puts every form of the hold into Spanish and leaves the file and folder names as written", async () => {
		const discard = spanish("missing.discard");
		// A phrase equal to the English one would let an untranslated page pass.
		expect(discard).not.toBe(DISCARD);

		// A fresh page load on a Spanish browser: the locale store starts anew.
		vi.resetModules();
		localStorage.clear();
		sessionStorage.clear();
		vi.spyOn(navigator, "languages", "get").mockReturnValue(["es-ES"]);
		vi.spyOn(navigator, "language", "get").mockReturnValue("es-ES");
		fakeFetch({
			"GET /locales/es.json": () => Response.json(SPANISH),
			[`GET ${ALBUM_URL}`]: () =>
				Response.json(viewWith([TOLD_WITH_FILE, UNPLACED("04.mp3"), FOLDER])),
		});
		const { AlbumPage: SpanishAlbumPage } = await import("./AlbumPage");
		renderAlbumPage(SpanishAlbumPage);

		// The Discard sentence in Spanish: the catalogue has loaded and the alert is drawn.
		await screen.findByText(discard);
		const alert = await theAlert();

		shows(
			alert,
			spanish("missing.track")
				.replace("{n}", "3")
				.replace("{title}", "It Was Always You"),
		);
		shows(alert, "03 It Was Always You.mp3");
		shows(alert, "04.mp3");
		shows(alert, "Scans");
		for (const english of [
			"could be it",
			"cannot be read",
			"A track is missing",
			"Tracks may be missing",
			"is missing",
		]) {
			expect(alert).not.toHaveTextContent(english);
		}
	});
});
