import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	createMemoryHistory,
	createRootRoute,
	createRoute,
	createRouter,
	RouterProvider,
} from "@tanstack/react-router";
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type {
	AcceptDecision,
	AlbumView,
	GenreSuggestion,
	SoundtrackSuggestion,
	SpellingSuggestion,
	Suggestion,
} from "@/shared/api/types";
import { ALBUM_URL, albumView, DROP, facts, flacFirst } from "@/test/albumView";
import { type Call, fakeFetch } from "@/test/fakeFetch";
import { screen, userEvent, waitFor, within } from "@/test/render";
import { renderApp } from "@/test/renderApp";

import { AlbumPage } from "./AlbumPage";

// What the review page offers from the rest of the library: a genre, the soundtrack choice,
// and the spelling of an artist folder.

const POSITIONS = ["1-1", "1-2", "1-3"];
const TAGS = "Tags on all 3 tracks";

const ACCEPTED = {
	action: "accept",
	release_id: "6f1a2b3c-0000-4000-8000-000100000001",
	edits: {},
	game: null,
	cover: null,
} as const;

const POWER_METAL: GenreSuggestion = {
	kind: "genre",
	genre: "power metal",
	albums: 25,
	of: 34,
	artist: "Sonata Arctica",
};
const POWER_METAL_SAYS = "power metal, on 25 of 34 Sonata Arctica albums";

const SYMPHONIC: GenreSuggestion = {
	kind: "genre",
	genre: "symphonic metal",
	albums: 18,
	of: 34,
	artist: "Sonata Arctica",
};
const SYMPHONIC_SAYS = "symphonic metal, on 18 of 34 Sonata Arctica albums";

const soundtrack = (
	genre: SoundtrackSuggestion["genre"],
): SoundtrackSuggestion => ({
	kind: "soundtrack",
	genre,
	albums: 3,
	of: 4,
	artist: "Yoko Shimomura",
});

// The folder's name is not the last part of the artist's planned folder, nor the whole of its own path.
const SPELLING: SpellingSuggestion = {
	kind: "spelling",
	artist: "Babasónicos",
	lands_in: "B/Babasónicos",
	folders: [{ path: "B/Babasonicos", name: "Babasonicos" }],
};
const SPELLING_SAYS =
	"Babasónicos is in the library as B/Babasonicos; this album would land in B/Babasónicos";

// An album the owner has accepted, so Approve approves at once and an edit turns it into Save.
function suggesting(
	suggestions: Suggestion[],
	over: Partial<AlbumView> = {},
): AlbumView {
	return albumView({ decision: ACCEPTED, suggestions, ...over });
}

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
	render(
		<QueryClientProvider client={queryClient}>
			<RouterProvider router={router} />
		</QueryClientProvider>,
	);
	return queryClient;
}

const textOf = (element: Element) =>
	element.textContent?.replace(/\s+/g, " ").trim() ?? "";

const suggestionsList = () =>
	screen.findByRole("list", { name: "Suggestions" });

const rowsHolding = (text: string) =>
	screen
		.queryAllByRole("listitem")
		.filter((item) => textOf(item).includes(text));

async function suggestion(text: string): Promise<HTMLElement> {
	const list = await suggestionsList();
	return waitFor(() => {
		const rows = rowsHolding(text).filter((row) => list.contains(row));
		expect(rows, `suggestions saying "${text}"`).toHaveLength(1);
		return rows[0]!;
	});
}

function tagRow(tag: string) {
	const row = within(screen.getByRole("table", { name: TAGS }))
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

function namesOf(root: HTMLElement, pattern: RegExp): string[] {
	const names: string[] = [];
	within(root).queryAllByRole("button", {
		name: (name) => {
			if (pattern.test(name)) names.push(name);
			return false;
		},
	});
	return names;
}

const field = (tag: string) =>
	screen.getByRole("textbox", { name: `New ${tag}` });

const values = (input: HTMLElement) =>
	(input as HTMLInputElement).value
		.split(";")
		.map((value) => value.trim())
		.sort();

const edited = (tag: string) =>
	within(tagRow(tag)).queryByText("edited by you") !== null;

const posts = (calls: Call[], path: string) =>
	calls.filter(
		(call) =>
			call.method === "POST" &&
			new URL(call.url).pathname === `${ALBUM_URL}/${path}`,
	);

describe("suggestions on the review page", () => {
	let fake: ReturnType<typeof fakeFetch> | undefined;
	let client: QueryClient | undefined;
	// What the album's address answers; a case changes it and asks again.
	let served: AlbumView;

	afterEach(() => {
		fake?.restore();
		fake = undefined;
		client = undefined;
	});

	function serve(view: AlbumView) {
		served = view;
		fake = fakeFetch({
			[`GET ${ALBUM_URL}`]: () => Response.json(served),
			[`POST ${ALBUM_URL}/decision`]: () => Response.json({ state: "queued" }),
			[`POST ${ALBUM_URL}/approve`]: () =>
				Response.json({
					state: "applying",
					path: null,
					error: null,
					step: null,
					file: null,
				}),
			"GET /api/drops": () => Response.json([]),
		});
		client = renderAlbumPage();
		return fake;
	}

	// The page asks for the album again, as it does after every request it sends.
	async function askAgain(view: AlbumView) {
		served = view;
		await act(async () => {
			await client?.invalidateQueries();
		});
	}

	async function saved(): Promise<AcceptDecision> {
		await userEvent.click(
			screen.getByRole("button", { name: "Save & re-preview" }),
		);
		await waitFor(() => expect(posts(fake!.calls, "decision")).toHaveLength(1));
		return JSON.parse(posts(fake!.calls, "decision")[0]!.body);
	}

	const sorted = (list: string[] | null | undefined) =>
		[...(list ?? [])].sort();

	describe("a genre the artist's other albums carry", () => {
		it("is shown with its count and an Add, and nothing is added before the click", async () => {
			serve(suggesting([POWER_METAL]));

			const row = await suggestion(POWER_METAL_SAYS);

			expect(row).toBeVisible();
			expect(
				within(row).getByRole("button", { name: "Add power metal" }),
			).toBeEnabled();
			expect(field("Genre")).toHaveValue("rock");
			expect(edited("Genre")).toBe(false);
			expect(screen.queryByText("Unsaved changes")).toBeNull();
			expect(
				screen.queryByRole("button", { name: "Save & re-preview" }),
			).toBeNull();
			expect(posts(fake!.calls, "decision")).toEqual([]);
		});

		// A typed genre goes out under the neutral name `genre` (TagDiff.test.tsx), and so does this one.
		it("goes on every track beside the genre the plan writes, as an edit of the owner's", async () => {
			serve(suggesting([POWER_METAL]));
			const row = await suggestion(POWER_METAL_SAYS);

			await userEvent.click(
				within(row).getByRole("button", { name: "Add power metal" }),
			);

			expect(values(field("Genre"))).toEqual(["power metal", "rock"]);
			expect(edited("Genre")).toBe(true);
			expect(screen.getByText("Unsaved changes")).toBeVisible();

			const decision = await saved();
			expect(Object.keys(decision.edits).sort()).toEqual(POSITIONS);
			for (const position of POSITIONS) {
				expect(Object.keys(decision.edits[position]!)).toEqual(["genre"]);
				expect(sorted(decision.edits[position]!.genre)).toEqual([
					"power metal",
					"rock",
				]);
			}
		});

		// One list of genres laid on every track would write `rock` over the second track's `jazz`.
		it("keeps each track's own genres where the tracks differ", async () => {
			const view = suggesting([POWER_METAL]);
			view.preview!.files[1]!.after.TCON = ["jazz"];
			view.preview!.fields["1-2"]!.genre = ["jazz"];
			serve(view);
			const row = await suggestion(POWER_METAL_SAYS);

			await userEvent.click(
				within(row).getByRole("button", { name: "Add power metal" }),
			);

			const { edits } = await saved();
			expect(sorted(edits["1-1"]?.genre)).toEqual(["power metal", "rock"]);
			expect(sorted(edits["1-2"]?.genre)).toEqual(["jazz", "power metal"]);
			expect(sorted(edits["1-3"]?.genre)).toEqual(["power metal", "rock"]);
		});

		// A second Add that starts from the plan and not from the draft loses the first.
		it("adds each of two suggestions by its own button, the second on top of the first", async () => {
			serve(suggesting([POWER_METAL, SYMPHONIC]));
			const first = await suggestion(POWER_METAL_SAYS);
			const second = await suggestion(SYMPHONIC_SAYS);

			await userEvent.click(
				within(second).getByRole("button", { name: "Add symphonic metal" }),
			);
			expect(values(field("Genre"))).toEqual(["rock", "symphonic metal"]);

			await userEvent.click(
				within(first).getByRole("button", { name: "Add power metal" }),
			);
			expect(values(field("Genre"))).toEqual([
				"power metal",
				"rock",
				"symphonic metal",
			]);

			const { edits } = await saved();
			for (const position of POSITIONS)
				expect(sorted(edits[position]?.genre)).toEqual([
					"power metal",
					"rock",
					"symphonic metal",
				]);
		});
	});

	describe("the soundtrack choice the artist's other albums made", () => {
		// The plan waits for the choice, so the page shows its Soundtrack control.
		function waiting(genre: SoundtrackSuggestion["genre"]) {
			const view = suggesting([soundtrack(genre)]);
			view.preview!.game_choice = true;
			return view;
		}

		const choice = (name: string) =>
			within(screen.getByRole("group", { name: "Soundtrack" })).getByRole(
				"radio",
				{ name },
			);

		it("is suggested with its count and a Choose, and is not chosen before the click", async () => {
			serve(waiting("video game music"));

			const row = await within(await suggestionsList()).findByRole("listitem");

			expect(row).toHaveTextContent("video game music");
			expect(row).toHaveTextContent("Yoko Shimomura");
			// 3 of the artist's 4 albums, in that order.
			expect(textOf(row)).toMatch(/\b3\b.*\b4\b/);
			expect(
				within(row).getByRole("button", { name: "Choose video game music" }),
			).toBeEnabled();
			for (const name of ["video game music", "soundtrack", "neither"])
				expect(choice(name)).not.toBeChecked();
			expect(screen.queryByText("Unsaved changes")).toBeNull();
			expect(posts(fake!.calls, "decision")).toEqual([]);
		});

		it.each([
			["video game music", "soundtrack"],
			["soundtrack", "video game music"],
		] as const)(
			"Choose picks %s as the Soundtrack control does",
			async (genre, other) => {
				serve(waiting(genre));
				await suggestionsList();

				await userEvent.click(
					screen.getByRole("button", { name: `Choose ${genre}` }),
				);

				expect(choice(genre)).toBeChecked();
				expect(choice(other)).not.toBeChecked();
				expect(choice("neither")).not.toBeChecked();

				const decision = await saved();
				expect(decision.game).toBe(genre);
				expect(decision.edits).toEqual({});
			},
		);
	});

	describe("an artist folder the library spells another way", () => {
		// The album as the suggestion describes it: planned under the accented name.
		function accented(spelling: SpellingSuggestion = SPELLING) {
			const view = suggesting([spelling]);
			for (const file of view.preview!.files) file.after.TPE2 = ["Babasónicos"];
			return view;
		}

		const use = (row: HTMLElement) =>
			within(row).getAllByRole("button", {
				name: /^Use the library's spelling/,
			});

		it("warns with both folders named and offers the library's spelling, changing nothing before the click", async () => {
			serve(accented());

			const row = await suggestion(SPELLING_SAYS);

			expect(row).toBeVisible();
			expect(use(row)).toHaveLength(1);
			expect(use(row)[0]).toBeEnabled();
			expect(field("Album artist")).toHaveValue("Babasónicos");
			expect(edited("Album artist")).toBe(false);
			expect(screen.queryByText("Unsaved changes")).toBeNull();
		});

		// The engine moves the artist folder only for the neutral field
		// `albumartist`, and converts what is typed there. An edit under the
		// file's own key (`TPE2` here) is laid over it as written, and the
		// folder would follow that text: the own key is not sent.
		it("Use the library's spelling puts the folder's name as the album artist on every track, as an edit of the owner's under the neutral name alone", async () => {
			serve(accented());
			const row = await suggestion(SPELLING_SAYS);

			await userEvent.click(use(row)[0]!);

			// The row the owner reads the album artist from shows what was just chosen.
			expect(field("Album artist")).toHaveValue("Babasonicos");
			expect(edited("Album artist")).toBe(true);
			expect(screen.getByText("Unsaved changes")).toBeVisible();
			// One tag, one row: the neutral name is not listed as a tag of its own.
			expect(
				within(screen.getByRole("table", { name: TAGS }))
					.getAllByRole("rowheader")
					.map((header) => header.textContent?.replace("edited by you", "")),
			).not.toContain("albumartist");

			const decision = await saved();
			expect(decision.edits).toEqual(
				Object.fromEntries(
					POSITIONS.map((position) => [
						position,
						{ albumartist: ["Babasonicos"] },
					]),
				),
			);
		});

		it("takes the edit back from the Album artist row, as any edit of the owner's", async () => {
			serve(accented());
			await userEvent.click(use(await suggestion(SPELLING_SAYS))[0]!);
			expect(field("Album artist")).toHaveValue("Babasonicos");

			await userEvent.click(
				within(tagRow("Album artist")).getByRole("button", {
					name: /^Undo/,
				}),
			);

			expect(field("Album artist")).toHaveValue("Babasónicos");
			expect(edited("Album artist")).toBe(false);
			expect(screen.queryByText("Unsaved changes")).toBeNull();
		});

		// An album artist an older page saved under the files' own key, on every track.
		const savedUnder = (key: string) => ({
			...ACCEPTED,
			edits: Object.fromEntries(
				POSITIONS.map((position) => [position, { [key]: ["Raw A"] }]),
			),
		});

		// The neutral name is the same whatever the files are. An edit a review
		// already holds under the files' own key would be laid over it, so it
		// leaves the decision, by each file's own key: `aART` in an M4A.
		it("sends the spelling under the neutral name alone for M4A files, and takes a saved aART edit out of the decision", async () => {
			const view = suggesting([SPELLING], { decision: savedUnder("aART") });
			view.files = view.preview!.files.map((file) =>
				facts(file.position, { family: "mp4", format: "M4A" }),
			);
			for (const file of view.preview!.files) {
				const { TPE2: _mp3s, ...rest } = file.after;
				file.after = { ...rest, aART: ["Babasónicos"] };
			}
			view.names.mp4 = { aART: "Album artist" };
			serve(view);
			await suggestion(SPELLING_SAYS);
			expect(field("Album artist")).toHaveValue("Raw A");

			await userEvent.click(use(await suggestion(SPELLING_SAYS))[0]!);

			expect(field("Album artist")).toHaveValue("Babasonicos");
			const decision = await saved();
			// Absent, and not `null`: a `null` there removes the tag.
			expect(decision.edits).toEqual(
				Object.fromEntries(
					POSITIONS.map((position) => [
						position,
						{ albumartist: ["Babasonicos"] },
					]),
				),
			);
		});

		// A FLAC's own key is the neutral name. The MP3s after it hold a saved
		// edit under `TPE2`, which goes by their own format and not by the first file's.
		it("sends the spelling under the neutral name on every track where a FLAC comes before the MP3s, and takes the MP3s' saved TPE2 edit out", async () => {
			const view = flacFirst(accented());
			view.preview!.files[0]!.after.albumartist = ["Babasónicos"];
			view.decision = {
				...ACCEPTED,
				edits: { "1-2": { TPE2: ["Raw A"] }, "1-3": { TPE2: ["Raw A"] } },
			};
			serve(view);

			await userEvent.click(use(await suggestion(SPELLING_SAYS))[0]!);

			const decision = await saved();
			expect(decision.edits).toEqual({
				"1-1": { albumartist: ["Babasonicos"] },
				"1-2": { albumartist: ["Babasonicos"] },
				"1-3": { albumartist: ["Babasonicos"] },
			});
		});

		it("offers each name where several folders match, and uses the one pressed", async () => {
			const folders = [
				{ path: "B/Babasonicos", name: "Babasonicos" },
				{ path: "B/BABASÓNICOS", name: "BABASÓNICOS" },
			];
			serve(accented({ ...SPELLING, folders }));

			const row = await suggestion("B/BABASÓNICOS");

			expect(row).toHaveTextContent("Babasónicos is in the library as");
			expect(row).toHaveTextContent("B/Babasonicos");
			expect(row).toHaveTextContent("this album would land in B/Babasónicos");
			const buttons = use(row);
			expect(buttons).toHaveLength(2);
			const named = (folder: string) =>
				within(row).queryAllByRole("button", {
					name: (name) =>
						name.startsWith("Use the library's spelling") &&
						name.includes(folder),
				});
			expect(named("Babasonicos")).toHaveLength(1);
			expect(named("BABASÓNICOS")).toHaveLength(1);

			await userEvent.click(named("BABASÓNICOS")[0]!);

			expect(field("Album artist")).toHaveValue("BABASÓNICOS");
			const { edits } = await saved();
			for (const position of POSITIONS)
				expect(edits[position]).toEqual({ albumartist: ["BABASÓNICOS"] });
		});
	});

	describe("Dismiss", () => {
		const dismissIn = (row: HTMLElement) =>
			within(row).getByRole("button", { name: /^Dismiss/ });

		it("is offered on each suggestion under its own name, and takes away only its own", async () => {
			serve(suggesting([POWER_METAL, SYMPHONIC, SPELLING]));
			const row = await suggestion(POWER_METAL_SAYS);

			const names = namesOf(await suggestionsList(), /^Dismiss/);
			expect(names).toHaveLength(3);
			expect(new Set(names).size, `names ${names.join(" | ")}`).toBe(3);

			await userEvent.click(dismissIn(row));

			expect(rowsHolding(POWER_METAL_SAYS)).toEqual([]);
			expect(rowsHolding(SYMPHONIC_SAYS)).toHaveLength(1);
			expect(rowsHolding(SPELLING_SAYS)).toHaveLength(1);
			// Dismissing is no edit: there is nothing to save.
			expect(screen.queryByText("Unsaved changes")).toBeNull();
		});

		// The second answer has the same preview and one suggestion more, listed first: its arrival
		// shows the page drew the new answer, and a page that remembers a place in the list hides the wrong one.
		it("keeps a suggestion dismissed when the album is asked for again and its preview is the same", async () => {
			serve(suggesting([POWER_METAL]));
			await userEvent.click(dismissIn(await suggestion(POWER_METAL_SAYS)));
			expect(rowsHolding(POWER_METAL_SAYS)).toEqual([]);

			await askAgain(suggesting([SYMPHONIC, POWER_METAL]));

			await suggestion(SYMPHONIC_SAYS);
			expect(rowsHolding(POWER_METAL_SAYS)).toEqual([]);
		});

		// The owner looks at another page of the app and comes back: the review
		// page is drawn afresh, and the album is the same album with the same
		// preview. A reload of the browser is another matter, and not promised.
		it("keeps a suggestion dismissed when the owner leaves the review page inside the app and comes back to the same preview", async () => {
			served = suggesting([POWER_METAL, SPELLING]);
			fake = fakeFetch({
				[`GET ${ALBUM_URL}`]: () => Response.json(served),
				"GET /api/drops": () => Response.json([]),
			});
			const router = renderApp(`/drops/${DROP}/albums/01`);
			await userEvent.click(dismissIn(await suggestion(POWER_METAL_SAYS)));
			expect(rowsHolding(POWER_METAL_SAYS)).toEqual([]);

			await userEvent.click(screen.getByRole("link", { name: "Drop" }));
			await waitFor(() => expect(router.state.location.pathname).toBe("/"));
			await waitFor(() =>
				expect(screen.queryByRole("list", { name: "Suggestions" })).toBeNull(),
			);
			// The same preview, with one suggestion more: its arrival shows the page drew the answer it got on the way back.
			served = suggesting([SYMPHONIC, POWER_METAL, SPELLING]);
			await act(async () => {
				router.history.back();
			});

			await suggestion(SYMPHONIC_SAYS);
			expect(router.state.location.pathname).toBe(`/drops/${DROP}/albums/01`);
			expect(rowsHolding(SPELLING_SAYS)).toHaveLength(1);
			expect(rowsHolding(POWER_METAL_SAYS)).toEqual([]);
		});

		// The page tells a changed preview by `plan_digest` (useDecision.ts).
		it("shows a dismissed suggestion again once the album's preview has changed", async () => {
			serve(suggesting([POWER_METAL]));
			await userEvent.click(dismissIn(await suggestion(POWER_METAL_SAYS)));
			expect(rowsHolding(POWER_METAL_SAYS)).toEqual([]);

			const replanned = suggesting([POWER_METAL]);
			replanned.preview!.plan_digest = "a-different-plan";
			await askAgain(replanned);

			expect(await suggestion(POWER_METAL_SAYS)).toBeVisible();
		});
	});

	it("leaves Approve enabled, and Approve approves with every suggestion still showing", async () => {
		const view = suggesting([POWER_METAL, soundtrack("soundtrack"), SPELLING]);
		serve(view);
		await suggestion(POWER_METAL_SAYS);
		await suggestion(SPELLING_SAYS);

		const approve = screen.getByRole("button", { name: "Approve" });
		expect(approve).toBeEnabled();
		expect(screen.queryByText(/^Approve:/)).toBeNull();
		await userEvent.click(approve);

		await waitFor(() => expect(posts(fake!.calls, "approve")).toHaveLength(1));
		expect(JSON.parse(posts(fake!.calls, "approve")[0]!.body)).toEqual({});
		expect(posts(fake!.calls, "decision")).toEqual([]);
	});

	it("shows nothing about suggestions for an album with none", async () => {
		serve(suggesting([]));

		// The tag table is drawn with the rest of the page, so the page has settled.
		await screen.findByRole("table", { name: TAGS });

		expect(screen.queryByRole("list", { name: "Suggestions" })).toBeNull();
		expect(screen.queryByText("Suggestions")).toBeNull();
		expect(screen.queryAllByRole("button", { name: /^Dismiss/ })).toEqual([]);
	});

	it("shows no suggestion on the page of an album that has landed", async () => {
		serve(
			suggesting([POWER_METAL, SPELLING], {
				state: "in the library",
				approvable: {
					ok: false,
					reason: "in the library",
					code: "in-library",
					hold: null,
				},
			}),
		);

		await screen.findByRole("heading", { name: /is in the library$/ });

		expect(screen.queryByRole("list", { name: "Suggestions" })).toBeNull();
		expect(rowsHolding(POWER_METAL_SAYS)).toEqual([]);
		expect(document.body).not.toHaveTextContent("power metal");
		expect(document.body).not.toHaveTextContent(SPELLING_SAYS);
		expect(
			screen.queryAllByRole("button", { name: /^(Add|Use|Dismiss)/ }),
		).toEqual([]);
	});
});
