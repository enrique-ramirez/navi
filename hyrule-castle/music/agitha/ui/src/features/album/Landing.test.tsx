import { afterEach, describe, expect, it, vi } from "vitest";

import type { AlbumView, PlanEntry } from "@/shared/api/types";
import { fakeFetch } from "@/test/fakeFetch";
import autoClean from "@/test/fixtures/auto-clean/plan.json";
import decisionHold from "@/test/fixtures/decision-hold/plan.json";
import { renderWithProviders, screen, within } from "@/test/render";

import { Landing } from "./Landing";

// The fixtures are shared by every test in the file, so a case copies before it edits.
const clean = autoClean.albums[0] as PlanEntry;
const held = decisionHold.albums[0] as PlanEntry;

const LIBRARY_PATH = "/srv/music/library/C/Clean Band/(2010) Clean Album";
const DELETED = "drop/album/Clean Album/cover.jpg";
const EXTRA = {
	source: "drop/album/Clean Album/Scans/booklet.pdf",
	path: "/srv/music/extras/C/Clean Band/(2010) Clean Album/Scans/booklet.pdf",
};

// Out of sorted order on purpose, so a page that sorts the tree is caught.
const TREE = [
	"03. Three.mp3",
	"01. One.mp3",
	"Scans/booklet.pdf",
	"02. Two.mp3",
	"cover.jpg",
];

function view(
	preview: PlanEntry | null,
	over: Partial<AlbumView> = {},
): AlbumView {
	return {
		drop: "20260929-210000",
		n: "01",
		name: "Clean Album",
		state: "ready",
		stderr: "",
		error: null,
		step: null,
		file: null,
		busy: false,
		preview,
		files: [],
		names: { id3: {}, vorbis: {}, mp4: {}, asf: {} },
		library_path: LIBRARY_PATH,
		tree: TREE,
		extras_to: [EXTRA],
		decision: null,
		cover: null,
		cover_now: null,
		uploaded: [],
		duplicate: null,
		approvable: { ok: true, reason: null, code: null, hold: null },
		replaces: null,
		suggestions: [],
		...over,
	};
}

async function landing(): Promise<HTMLElement> {
	return screen.findByRole("region", { name: "Where it lands" });
}

// The items of `list` itself, not those of the lists nested in it.
function ownItems(list: HTMLElement): HTMLElement[] {
	return within(list)
		.getAllByRole("listitem")
		.filter(
			(item) => item.parentElement?.closest("ul, ol, [role='list']") === list,
		);
}

// The list a folder item holds.
function nestedList(item: HTMLElement): HTMLElement {
	const lists = within(item).getAllByRole("list");
	return lists[0];
}

// What an item says of itself: a folder's name, without the files it holds.
function ownText(item: HTMLElement): string {
	const copy = item.cloneNode(true) as HTMLElement;
	for (const list of copy.querySelectorAll("ul, ol, [role='list']"))
		list.remove();
	return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

describe("where the album lands", () => {
	it("shows where in the library the album goes, with the full path on hover", async () => {
		renderWithProviders(<Landing view={view(clean)} />);
		const region = await landing();

		const destination = within(region).getByText(clean.destination ?? "");
		expect(destination).toHaveAttribute("title", LIBRARY_PATH);
		expect(
			within(region).queryByText("no destination yet"),
		).not.toBeInTheDocument();
	});

	it("says there is no destination yet when the plan has none", async () => {
		renderWithProviders(
			<Landing
				view={view({ ...clean, destination: null }, { library_path: null })}
			/>,
		);
		const region = await landing();

		expect(within(region).getByText("no destination yet")).toBeInTheDocument();
	});

	it("counts the files of the album folder in its summary", async () => {
		renderWithProviders(<Landing view={view(clean)} />);
		const region = await landing();

		expect(
			within(region).getByText("Album folder (5 files)"),
		).toBeInTheDocument();
	});

	it("shows the album folder as a tree of folders and files, in the order given", async () => {
		renderWithProviders(<Landing view={view(clean)} />);
		const region = await landing();

		const folder = within(region).getByRole("list", { name: "Album folder" });
		const top = ownItems(folder);
		expect(top.map(ownText)).toEqual([
			"03. Three.mp3",
			"01. One.mp3",
			"Scans",
			"02. Two.mp3",
			"cover.jpg",
		]);

		// Scans is a folder: it holds booklet.pdf, which is not an item of the top level.
		const scans = nestedList(top[2]);
		expect(ownItems(scans).map(ownText)).toEqual(["booklet.pdf"]);

		// A file is a leaf.
		expect(within(top[4]).queryByRole("list")).not.toBeInTheDocument();
		expect(within(top[0]).queryByRole("list")).not.toBeInTheDocument();
	});

	it("gathers files of one folder under a single folder item, at any depth", async () => {
		const tree = [
			"Scans/booklet.pdf",
			"Scans/Inlay/back.jpg",
			"Scans/obi.jpg",
			"01. One.mp3",
		];
		renderWithProviders(<Landing view={view(clean, { tree })} />);
		const region = await landing();

		const top = ownItems(
			within(region).getByRole("list", { name: "Album folder" }),
		);
		expect(top.map(ownText)).toEqual(["Scans", "01. One.mp3"]);

		const scans = ownItems(nestedList(top[0]));
		expect(scans.map(ownText)).toEqual(["booklet.pdf", "Inlay", "obi.jpg"]);
		expect(ownItems(nestedList(scans[1])).map(ownText)).toEqual(["back.jpg"]);
	});

	it("lists the files that will be deleted by name, and counts them", async () => {
		renderWithProviders(<Landing view={view(clean)} />);
		const region = await landing();

		expect(within(region).getByText("Deleted (1)")).toBeInTheDocument();
		const deleted = within(region).getByRole("list", { name: "Deleted" });
		expect(ownItems(deleted).map(ownText)).toEqual([DELETED.split("/").pop()]);
	});

	it("leaves out the deletions when nothing is deleted", async () => {
		const nothingDeleted: PlanEntry = { ...clean, deletions: [] };
		renderWithProviders(<Landing view={view(nothingDeleted)} />);
		const region = await landing();

		expect(
			within(region).queryByRole("list", { name: "Deleted" }),
		).not.toBeInTheDocument();
		expect(within(region).queryByText(/^Deleted/)).not.toBeInTheDocument();
	});

	it("lists each extra with where it is now and its path in /srv/music/extras", async () => {
		renderWithProviders(<Landing view={view(clean)} />);
		const region = await landing();

		expect(within(region).getByText("Extras (1)")).toBeInTheDocument();
		const extras = ownItems(
			within(region).getByRole("list", { name: "Extras" }),
		);
		expect(extras).toHaveLength(1);
		expect(extras[0]).toHaveTextContent(EXTRA.source);
		expect(extras[0]).toHaveTextContent(EXTRA.path);
	});

	it("leaves out the extras when there are none", async () => {
		renderWithProviders(<Landing view={view(clean, { extras_to: [] })} />);
		const region = await landing();

		expect(
			within(region).queryByRole("list", { name: "Extras" }),
		).not.toBeInTheDocument();
	});

	it("names every list it shows", async () => {
		renderWithProviders(<Landing view={view(held)} />);
		const region = await landing();

		const lists = within(region).getAllByRole("list");
		// The tree, its Scans folder, deletions and extras.
		expect(lists.length).toBeGreaterThanOrEqual(4);
		for (const list of lists) expect(list).toHaveAccessibleName();
	});

	it("shows nothing when identify has written no preview yet", async () => {
		renderWithProviders(
			<>
				<p>page</p>
				<Landing
					view={view(null, { library_path: null, tree: [], extras_to: [] })}
				/>
			</>,
		);

		await screen.findByText("page");
		expect(
			screen.queryByRole("region", { name: "Where it lands" }),
		).not.toBeInTheDocument();
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

describe("where the album lands, in Spanish", () => {
	afterEach(() => {
		vi.restoreAllMocks();
		vi.unstubAllGlobals();
	});

	it("names the region and the folder, deletions and extras in Spanish and leaves the paths as written", async () => {
		const title = spanish("landing.title");
		const folder = spanish("landing.folder");
		// A phrase equal to the English one would let an untranslated page pass.
		expect(title).not.toBe("Where it lands");
		expect(folder).not.toBe("Album folder");

		// A fresh page load on a Spanish browser: the locale store starts anew.
		vi.resetModules();
		localStorage.clear();
		sessionStorage.clear();
		vi.spyOn(navigator, "languages", "get").mockReturnValue(["es-ES"]);
		vi.spyOn(navigator, "language", "get").mockReturnValue("es-ES");
		fakeFetch({ "GET /locales/es.json": () => Response.json(SPANISH) });
		const { Landing: SpanishLanding } = await import("./Landing");
		const page = await import("@/test/render");

		page.renderWithProviders(<SpanishLanding view={view(held)} />);
		const region = await page.screen.findByRole("region", { name: title });

		expect(
			within(region).getByText(
				spanish("landing.folderCount").replace("{n}", String(TREE.length)),
			),
		).toBeInTheDocument();
		expect(
			within(region).getByRole("list", { name: folder }),
		).toBeInTheDocument();
		expect(
			within(region).getByRole("list", { name: spanish("landing.extras") }),
		).toBeInTheDocument();
		// The paths are data rather than phrases.
		expect(within(region).getByText(EXTRA.path)).toBeInTheDocument();
	});
});
