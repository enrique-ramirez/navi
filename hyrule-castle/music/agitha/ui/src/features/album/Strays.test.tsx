import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	createMemoryHistory,
	createRootRoute,
	createRoute,
	createRouter,
	RouterProvider,
} from "@tanstack/react-router";
import { fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type {
	AcceptDecision,
	AlbumView,
	PlanEntry,
	Stray,
} from "@/shared/api/types";
import { ALBUM_URL, albumView, DROP } from "@/test/albumView";
import { fakeFetch } from "@/test/fakeFetch";
import strayDecisions from "@/test/fixtures/stray-images/decisions.json";
import strayPlan from "@/test/fixtures/stray-images/plan.json";
import { renderWithProviders, screen, userEvent, within } from "@/test/render";

import { AlbumPage } from "./AlbumPage";
import { type Pending, usePending } from "./pending";
import { Strays } from "./Strays";

// Written by the engine, in plan order: a copy of cover.jpg, the one with no guess,
// one the owner named, a guess, one that lost to the root's tray.jpg, one that won
// over the root's back.jpg, and a copy of another stray.
const ENTRY = strayPlan.albums[0] as unknown as PlanEntry;
const FIXTURE = ENTRY.strays as Stray[];

const COPY_OF_COVER = "COVERS/folder.jpg";
const UNDECIDED = "COVERS/IMG_0001.jpg";
const OWNED = "COVERS/IMG_0002.jpg";
const GUESSED = "COVERS/stray_album-obi.jpg";
const LOST = "COVERS/stray_band-tray.jpg";
const WON = "COVERS/stray_band_stray_album-back.jpg";
const COPY_OF_STRAY = "Scans/IMG_0001 copy.jpg";

// The accept the plan was made under: the owner named IMG_0002.
const ACCEPTED = Object.values(strayDecisions.albums)[0] as AcceptDecision;

// Kinds the fixture lacks: a PDF and a log.
const PDF = "Booklet/notes.pdf";
const LOG = "Info/rip.log";
const OTHERS: Stray[] = [
	{
		path: PDF,
		kind: "pdf",
		answer: { keep: "booklet.pdf" },
		why: "guessed",
		against: null,
		size: null,
	},
	{
		path: LOG,
		kind: "text",
		answer: { keep: "rip.log" },
		why: "guessed",
		against: null,
		size: null,
	},
];

// An undecided image whose extension the engine rewrites: kept, it must end in `.jpg`.
const SHOUTING = "covers/01.JPG";
const SHOUTING_STRAY: Stray = {
	path: SHOUTING,
	kind: "image",
	answer: null,
	why: "no guess",
	against: null,
	size: [1200, 1200],
};

const LIBRARY_NAMES = [
	"front",
	"back",
	"medium",
	"booklet",
	"tray",
	"obi",
	"spine",
	"sticker",
	"poster",
	"liner",
	"track",
	"matrix-runout",
	"top",
	"bottom",
	"other",
];

// The name the server accepts for a kept JPEG, as `musiclib/strays.py` `_LIBRARY_NAME`
// and `_extension` have it: booklet always numbered from 01, any other type plain or
// numbered from 1, then the lowercased extension.
const ACCEPTED_JPG = new RegExp(
	`^(?:booklet-(?:0[1-9]|[1-9]\\d+)|(?:${LIBRARY_NAMES.filter(
		(name) => name !== "booklet",
	).join("|")})(?:-[1-9]\\d*)?)\\.jpg$`,
);

const TITLE = /Files outside the album's rules/;

// The plan's strays on the page's album, which the owner accepted as the decisions file says.
function viewWith(
	strays: Stray[] | undefined,
	over: Partial<AlbumView> = {},
): AlbumView {
	const view = albumView(over);
	view.preview = { ...view.preview!, strays: structuredClone(strays) };
	view.decision = {
		...structuredClone(ACCEPTED),
		release_id: view.preview.release_id ?? "",
	};
	return view;
}

// The last pending the harness saw, so a case can read the draft the Send and Approve buttons post.
let latest: Pending | undefined;

// The owner's stray answers in the draft; a repoint carries none.
const drafted = () =>
	latest?.draft.action === "accept" ? latest.draft.strays : "not an accept";

function Section({ view }: { view: AlbumView }) {
	const pending = usePending(view);
	latest = pending;
	return (
		<>
			<Strays view={view} pending={pending} />
			<p>rendered</p>
		</>
	);
}

async function renderSection(view: AlbumView) {
	const result = renderWithProviders(<Section view={view} />);
	await screen.findByText("rendered");
	return result;
}

const section = () => screen.getByRole("region", { name: TITLE });

// The row whose Keep and Delete group is named by exactly this path. A row's text
// can hold another stray's path (`copy of COVERS/IMG_0001.jpg`), so matching on
// text would find two.
function rowOf(path: string): HTMLElement {
	const rows = within(section())
		.getAllByRole("row")
		.filter((row) => within(row).queryByRole("group", { name: path }));
	expect(rows, `one row for ${path}`).toHaveLength(1);
	return rows[0]!;
}

const nameField = (path: string) => screen.getByLabelText(`Name for ${path}`);

const choices = (path: string) => screen.getByRole("group", { name: path });

// The names a field suggests, whether through a list it points at or options of its own.
function offered(field: HTMLElement): string[] {
	const id = field.getAttribute("list") ?? field.getAttribute("aria-controls");
	const source = id ? document.getElementById(id) : field;
	if (!source) return [];
	return within(source)
		.queryAllByRole("option", { hidden: true })
		.map(
			(option) =>
				(option as HTMLOptionElement).value || option.textContent || "",
		);
}

const thumbnailUrl = (path: string) =>
	`${ALBUM_URL}/strays/${path.split("/").map(encodeURIComponent).join("/")}`;

const dataRows = () =>
	within(section())
		.getAllByRole("row")
		.filter((row) => within(row).queryByRole("group") !== null);

describe("Strays", () => {
	afterEach(() => {
		latest = undefined;
	});

	it("titles the section and says how many files need a choice", async () => {
		await renderSection(viewWith(FIXTURE));

		expect(
			within(section()).getByRole("heading", { name: TITLE }),
		).toBeInTheDocument();
		// A bare substring would also accept "11 files" or "0 files".
		expect(section()).toHaveTextContent(/(^|\D)1 file needs a choice/);
	});

	it("counts several undecided files in the plural", async () => {
		await renderSection(viewWith([...FIXTURE, SHOUTING_STRAY]));

		expect(section()).toHaveTextContent(/(^|\D)2 files need a choice/);
	});

	it("says no file needs a choice when agitha settled them all", async () => {
		await renderSection(
			viewWith(FIXTURE.filter((stray) => stray.answer !== null)),
		);

		expect(section()).toHaveTextContent("No file needs a choice");
	});

	it("lists the undecided files before the settled ones", async () => {
		await renderSection(viewWith(FIXTURE));

		// The plan holds the undecided file second, so plan order puts it elsewhere.
		const rows = dataRows();
		expect(rows).toHaveLength(FIXTURE.length);
		expect(
			within(rows[0]!).getByRole("group", { name: UNDECIDED }),
		).toBeInTheDocument();
	});

	it("says for each file what will happen to it and why", async () => {
		await renderSection(viewWith(FIXTURE));

		expect(rowOf(GUESSED)).toHaveTextContent("kept as obi.jpg");
		expect(rowOf(GUESSED)).toHaveTextContent("guessed");
		expect(rowOf(UNDECIDED)).toHaveTextContent("needs a name");
		expect(rowOf(UNDECIDED)).toHaveTextContent("no guess");
		expect(rowOf(OWNED)).toHaveTextContent("kept as booklet-01.jpg");
		expect(rowOf(OWNED)).toHaveTextContent("your choice");
		expect(rowOf(COPY_OF_COVER)).toHaveTextContent("deleted");
		expect(rowOf(COPY_OF_COVER)).toHaveTextContent("copy of cover.jpg");
		// `against` is another stray's path here, and is shown as written.
		expect(rowOf(COPY_OF_STRAY)).toHaveTextContent("deleted");
		expect(rowOf(COPY_OF_STRAY)).toHaveTextContent(
			"copy of COVERS/IMG_0001.jpg",
		);
	});

	// The engine writes `lost` on a tie as well, and `against` may be the rip's own
	// file or the archive's, so the words claim neither size nor source.
	it("says which file is kept instead of one that lost, and over which one a winner is kept", async () => {
		await renderSection(viewWith(FIXTURE));

		expect(rowOf(LOST)).toHaveTextContent("deleted");
		expect(rowOf(LOST)).toHaveTextContent("another tray.jpg is kept instead");
		expect(rowOf(WON)).toHaveTextContent("kept as back.jpg");
		expect(rowOf(WON)).toHaveTextContent("kept over another back.jpg");
		for (const path of [LOST, WON]) {
			expect(rowOf(path)).not.toHaveTextContent(/bigger|archive/);
		}
	});

	it("suggests only names the server accepts for an image, and none for a PDF or a text file", async () => {
		await renderSection(viewWith([...FIXTURE, SHOUTING_STRAY, ...OTHERS]));

		const names = offered(nameField(SHOUTING));
		// `.JPG` is kept as `.jpg`; booklet is never plain.
		expect(names.filter((name) => !ACCEPTED_JPG.test(name))).toEqual([]);
		expect(names).toContain("booklet-01.jpg");
		expect(names).toContain("back-2.jpg");
		expect(names).not.toContain("booklet.jpg");
		for (const type of LIBRARY_NAMES) {
			expect(
				names.some((name) => new RegExp(`^${type}(-\\d+)?\\.jpg$`).test(name)),
				`${type} offered`,
			).toBe(true);
		}
		expect(
			offered(nameField(UNDECIDED)).filter((name) => !ACCEPTED_JPG.test(name)),
		).toEqual([]);
		expect(offered(nameField(PDF))).toEqual([]);
		expect(offered(nameField(LOG))).toEqual([]);
	});

	it("keeps a text file under any name the owner types", async () => {
		const user = userEvent.setup();
		await renderSection(viewWith(OTHERS));

		await user.clear(nameField(LOG));
		await user.type(nameField(LOG), "EAC rip.log");
		await user.click(
			within(choices(LOG)).getByRole("button", { name: "Keep" }),
		);

		expect(rowOf(LOG)).toHaveTextContent("kept as EAC rip.log");
		expect(drafted()).toEqual({ ...ACCEPTED.strays, [LOG]: "EAC rip.log" });
	});

	it("keeps an undecided image under the name the owner gives it", async () => {
		const user = userEvent.setup();
		await renderSection(viewWith(FIXTURE));

		await user.clear(nameField(UNDECIDED));
		await user.type(nameField(UNDECIDED), "poster.jpg");
		await user.click(
			within(choices(UNDECIDED)).getByRole("button", { name: "Keep" }),
		);

		expect(rowOf(UNDECIDED)).toHaveTextContent("kept as poster.jpg");
		expect(rowOf(UNDECIDED)).not.toHaveTextContent("needs a name");
		expect(section()).toHaveTextContent("No file needs a choice");
		// Only the touched file joins the accepted answers, so agitha's stand for the rest.
		expect(drafted()).toEqual({
			...ACCEPTED.strays,
			[UNDECIDED]: "poster.jpg",
		});
	});

	it("deletes one file and leaves the others as agitha planned them", async () => {
		const user = userEvent.setup();
		await renderSection(viewWith(FIXTURE));

		await user.click(
			within(choices(WON)).getByRole("button", { name: "Delete" }),
		);

		expect(rowOf(WON)).toHaveTextContent("deleted");
		expect(rowOf(WON)).not.toHaveTextContent("kept as");
		expect(rowOf(GUESSED)).toHaveTextContent("kept as obi.jpg");
		expect(rowOf(OWNED)).toHaveTextContent("kept as booklet-01.jpg");
		expect(drafted()).toEqual({ ...ACCEPTED.strays, [WON]: null });
	});

	it("Delete all marks every file deleted in the draft", async () => {
		const user = userEvent.setup();
		await renderSection(viewWith(FIXTURE));

		await user.click(screen.getByRole("button", { name: "Delete all" }));

		for (const { path } of FIXTURE) {
			expect(rowOf(path)).toHaveTextContent("deleted");
			expect(rowOf(path)).not.toHaveTextContent(/kept as|needs a name/);
		}
		expect(section()).toHaveTextContent("No file needs a choice");
		expect(drafted()).toEqual(
			Object.fromEntries(FIXTURE.map(({ path }) => [path, null])),
		);
	});

	it("Use agitha's names takes back every answer the owner gave, the accepted ones too", async () => {
		const user = userEvent.setup();
		await renderSection(viewWith(FIXTURE));

		await user.click(
			within(choices(GUESSED)).getByRole("button", { name: "Delete" }),
		);
		await user.clear(nameField(UNDECIDED));
		await user.type(nameField(UNDECIDED), "poster.jpg");
		await user.click(
			within(choices(UNDECIDED)).getByRole("button", { name: "Keep" }),
		);
		expect(rowOf(GUESSED)).toHaveTextContent("deleted");

		await user.click(
			screen.getByRole("button", { name: "Use agitha's names" }),
		);

		expect(rowOf(GUESSED)).toHaveTextContent("kept as obi.jpg");
		expect(rowOf(UNDECIDED)).toHaveTextContent("needs a name");
		expect(section()).toHaveTextContent(/(^|\D)1 file needs a choice/);
		expect(drafted()).toBeUndefined();
	});

	it("links an image's thumbnail to the file at full size in a new tab", async () => {
		await renderSection(viewWith(FIXTURE));

		// The second path holds a space, so a path sent unencoded shows.
		for (const path of [GUESSED, COPY_OF_STRAY]) {
			expect(
				within(rowOf(path)).getByRole("img", { name: path }),
			).toHaveAttribute("src", thumbnailUrl(path));
			const link = within(rowOf(path)).getByRole("link", { name: path });
			expect(link).toHaveAttribute("href", `${thumbnailUrl(path)}?full`);
			expect(link).toHaveAttribute("target", "_blank");
			expect(link).toHaveAttribute(
				"rel",
				expect.stringContaining("noreferrer"),
			);
		}
	});

	it("shows no thumbnail for a PDF or a text file", async () => {
		const { container } = await renderSection(
			viewWith([...FIXTURE, ...OTHERS]),
		);

		expect(rowOf(PDF)).toHaveTextContent(PDF);
		// The server has no thumbnail for these, so the page must not ask for one.
		for (const path of [PDF, LOG]) {
			expect(
				container.querySelector(`img[src^="${thumbnailUrl(path)}"]`),
			).toBeNull();
		}
		expect(
			container.querySelector(`img[src="${thumbnailUrl(GUESSED)}"]`),
		).not.toBeNull();
	});

	it("drops a thumbnail that fails to load and keeps the row", async () => {
		await renderSection(viewWith(FIXTURE));

		fireEvent.error(within(rowOf(WON)).getByRole("img", { name: WON }));

		expect(
			within(rowOf(WON)).queryByRole("img", { name: WON }),
		).not.toBeInTheDocument();
		expect(rowOf(WON)).toHaveTextContent(WON);
		expect(
			within(rowOf(LOST)).getByRole("img", { name: LOST }),
		).toBeInTheDocument();
	});

	it.each(["queued", "identifying"] as const)(
		"disables every control while the album is %s",
		async (state) => {
			await renderSection(viewWith(FIXTURE, { state, busy: true }));

			for (const { path } of FIXTURE) {
				expect(
					within(choices(path)).getByRole("button", { name: "Keep" }),
				).toBeDisabled();
				expect(
					within(choices(path)).getByRole("button", { name: "Delete" }),
				).toBeDisabled();
				expect(nameField(path)).toBeDisabled();
			}
			expect(screen.getByRole("button", { name: "Delete all" })).toBeDisabled();
			expect(
				screen.getByRole("button", { name: "Use agitha's names" }),
			).toBeDisabled();
		},
	);

	it.each([
		["a plan written before strays existed", undefined],
		["a plan with no strays", []],
	])("shows no section for %s", async (_, strays) => {
		await renderSection(viewWith(strays));

		expect(screen.queryByRole("region", { name: TITLE })).toBeNull();
		expect(screen.queryByText(TITLE)).toBeNull();
		expect(screen.queryByRole("button", { name: "Delete all" })).toBeNull();
	});
});

// The profile's helper mounts the page at a catch-all route, which gives it no
// `drop` and `n`; this router gives it the album route's parameters.
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

describe("the album page", () => {
	let restore: (() => void) | undefined;

	afterEach(() => {
		restore?.();
		restore = undefined;
	});

	it("puts the section after the holds and before the match picker", async () => {
		const view = viewWith(FIXTURE);
		view.preview!.holds = structuredClone(ENTRY.holds);
		restore = fakeFetch({
			[`GET ${ALBUM_URL}`]: () => Response.json(view),
		}).restore;
		renderAlbumPage();

		const strays = await screen.findByRole("region", { name: TITLE });
		const holds = screen.getByRole("list", { name: "Holds" });
		const picker = screen.getByRole("region", { name: "MusicBrainz release" });
		const follows = (a: Node, b: Node) =>
			Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
		expect(follows(holds, strays)).toBe(true);
		expect(follows(strays, picker)).toBe(true);
	});
});
