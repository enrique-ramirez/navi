import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	createMemoryHistory,
	createRootRoute,
	createRoute,
	createRouter,
	RouterProvider,
} from "@tanstack/react-router";
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { AlbumView, Comparison, Copy } from "@/shared/api/types";
import { ALBUM_URL, albumView, DROP } from "@/test/albumView";
import { type Call, fakeFetch } from "@/test/fakeFetch";
import { screen, userEvent, waitFor } from "@/test/render";

import { AlbumPage } from "./AlbumPage";

// The review page of a match: an album copied out of the library to be identified again.

// The library album the match replaces, as the server names it: relative to the library root.
const REPLACES = "S/Sonata Arctica/(1999) Ecliptica";
const LINE = `Replaces ${REPLACES}`;
const TAGS = "Tags on all 3 tracks";

const ACCEPTED = {
	action: "accept",
	release_id: "6f1a2b3c-0000-4000-8000-000100000001",
	edits: {},
	game: null,
	cover: null,
} as const;

// A match the owner has accepted, so Approve approves at once.
const match = (over: Partial<AlbumView> = {}) =>
	albumView({ decision: ACCEPTED, replaces: REPLACES, ...over });

function copy(folder: string, over: Partial<Copy> = {}): Copy {
	return {
		folder,
		format: "MP3",
		lossless: false,
		bit_depth: null,
		sample_rate: 44100,
		bitrate: 320000,
		bitrate_min: 320000,
		bitrate_max: 320000,
		files: 3,
		length: 600,
		size: 24_000_000,
		cover: null,
		release_id: null,
		album: "Clean Album",
		album_artist: "Clean Band",
		date: "2010",
		label: null,
		catalog: null,
		country: null,
		media: null,
		discs: 1,
		encoder: null,
		tag_count: 14,
		...over,
	};
}

const COMPARISON: Comparison = {
	new: copy(`/srv/music/inbox/${DROP}/01/C/Clean Band/(2010) Clean Album`),
	library: copy("/srv/music/library/C/Clean Band/(2010) Clean Album"),
	recommended: "library",
	rule: "the copy in the library",
	rule_code: "library",
	tracks: {
		paired: 3,
		length_differs: 0,
		only_new: 0,
		only_library: 0,
		max_length_diff: 0,
	},
};

// The profile's helper mounts the page at a catch-all route, which gives it no
// `drop` and `n`; this router gives it the album route's parameters (as in AlbumPage.test.tsx).
function renderAlbumPage() {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	const rootRoute = createRootRoute();
	const album = createRoute({
		getParentRoute: () => rootRoute,
		path: "drops/$drop/albums/$n",
		component: AlbumPage,
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

const textOf = (element: Element) =>
	element.textContent?.replace(/\s+/g, " ").trim() ?? "";

// The innermost elements whose text contains `text`, however the sentence is split across markup.
function holding(text: string): HTMLElement[] {
	return [...document.body.querySelectorAll<HTMLElement>("*")].filter(
		(element) =>
			textOf(element).includes(text) &&
			![...element.children].some((child) => textOf(child).includes(text)),
	);
}

function replacesLine(): Promise<HTMLElement> {
	return waitFor(() => {
		const found = holding(LINE);
		expect(found, `"${LINE}" on the page`).toHaveLength(1);
		return found[0]!;
	});
}

const precedes = (a: Node, b: Node) =>
	Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

const comparison = () =>
	screen.queryByRole("region", { name: "Already in the library" });
const keepButtons = () => screen.queryAllByRole("button", { name: /^Keep / });

const posts = (calls: Call[]) => calls.filter((call) => call.method === "POST");
const pathOf = (call: Call) => new URL(call.url).pathname;

describe("the review page of a match", () => {
	let restore: (() => void) | undefined;

	afterEach(() => {
		restore?.();
		restore = undefined;
	});

	function serve(view: AlbumView, approve?: () => Response) {
		const fake = fakeFetch({
			[`GET ${ALBUM_URL}`]: () => Response.json(view),
			[`POST ${ALBUM_URL}/approve`]:
				approve ??
				(() =>
					Response.json({
						state: "applying",
						path: null,
						error: null,
						step: null,
						file: null,
					})),
		});
		restore = fake.restore;
		renderAlbumPage();
		return fake;
	}

	// A new upload's comparison sits under the review bar and above the tags; the line takes that place.
	it("says which library album it replaces, where a new upload's page compares the two copies", async () => {
		serve(match());

		const line = await replacesLine();

		expect(line).toBeVisible();
		const title = screen.getByRole("heading", { level: 1 });
		const tags = screen.getByRole("table", { name: TAGS });
		expect(precedes(title, line), "under the review bar").toBe(true);
		expect(precedes(line, tags), "above the tags").toBe(true);
		expect(comparison()).toBeNull();
		expect(keepButtons()).toEqual([]);
	});

	// The server sends a match no comparison. The second view carries one all the same, so the
	// page is what keeps Keep the one in the library off a match and not the server's silence.
	it.each([
		["the server sends no comparison", null],
		["the view carries a comparison", COMPARISON],
	])("approves with no copy to choose, where %s", async (_, duplicate) => {
		const fake = serve(match({ duplicate }));
		const user = userEvent.setup();

		await replacesLine();
		expect(comparison()).toBeNull();
		expect(keepButtons()).toEqual([]);
		expect(screen.queryByText("Choose which copy to keep below")).toBeNull();

		const approve = screen.getByRole("button", { name: "Approve" });
		expect(approve).toBeEnabled();
		await user.click(approve);

		await waitFor(() => expect(posts(fake.calls)).toHaveLength(1));
		const [post] = posts(fake.calls);
		expect(pathOf(post!)).toBe(`${ALBUM_URL}/approve`);
		expect(JSON.parse(post!.body)).toEqual({});
	});

	// The path of the first is another album's folder, so the page cannot build the sentence
	// from the view it holds.
	it.each([
		["already in the library: S/Sonata Arctica/(2001) Silence"],
		["the library's copy changed since this match began; start over"],
	])("shows Approve's refusal as served: %s", async (sentence) => {
		const fake = serve(match(), () =>
			Response.json({ error: sentence }, { status: 409 }),
		);
		const user = userEvent.setup();

		await replacesLine();
		await user.click(screen.getByRole("button", { name: "Approve" }));

		const alerts = await screen.findAllByRole("alert");
		expect(alerts.map(textOf)).toEqual([sentence]);
		expect(posts(fake.calls).map(pathOf)).toEqual([`${ALBUM_URL}/approve`]);
		// The album is still a match under review.
		expect(holding(LINE)).toHaveLength(1);
		expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
	});

	it("offers Discard", async () => {
		serve(match());

		await replacesLine();

		expect(screen.getByRole("button", { name: "Discard" })).toBeEnabled();
	});
});

describe("the review page of a new upload", () => {
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

	it("compares the two copies and offers both to keep, with no Replaces line", async () => {
		serve(albumView({ decision: ACCEPTED, duplicate: COMPARISON }));

		expect(
			await screen.findByRole("region", { name: "Already in the library" }),
		).toBeVisible();
		expect(
			screen.getByRole("button", { name: "Keep the one in the library" }),
		).toBeEnabled();
		expect(
			screen.getByRole("button", { name: "Keep the new one" }),
		).toBeEnabled();
		// The comparison's own `Replaces the library's copy...` is the only line that opens so.
		expect(
			holding("Replaces ")
				.map(textOf)
				.filter((text) => !text.startsWith("Replaces the library's copy")),
		).toEqual([]);
	});

	it("says nothing of replacing for an upload the library holds no copy of", async () => {
		serve(albumView({ decision: ACCEPTED }));

		await screen.findByRole("table", { name: TAGS });

		expect(holding("Replaces")).toEqual([]);
	});
});
