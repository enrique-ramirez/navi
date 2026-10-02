import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { fakeFetch } from "@/test/fakeFetch";
import {
	fixtures,
	held,
	libraryAddress,
	libraryHandlers,
	requested,
	type Shelves,
} from "@/test/library";
import { screen, userEvent, waitFor } from "@/test/render";
import { renderApp } from "@/test/renderApp";

let server: ReturnType<typeof fakeFetch> | undefined;

afterEach(() => {
	server?.restore();
	server = undefined;
});

// The page through the app's own routes, so the address reaches it as a browser's does.
function openAt(address: string, shelves?: Shelves) {
	server?.restore();
	server = fakeFetch(libraryHandlers(shelves));
	const router = renderApp(address);
	return {
		router,
		calls: server.calls,
		// Decoded: the promise is the place the address names, not how a space is written.
		place: () => decodeURIComponent(router.state.location.pathname),
	};
}

function folder(name: string) {
	return screen.findByRole("treeitem", { name: `${name}, folder` });
}

// One row of the tree as a reader of it has it. An album is a leaf, and whether
// a leaf says collapsed is not decided, so an album's row leaves that out.
type Row = { name: string; is: "open" | "closed" | "album"; here?: true };

const closed = (name: string): Row => ({ name, is: "closed" });
const open = (name: string): Row => ({ name, is: "open" });
const albumRow = (name: string): Row => ({ name, is: "album" });
const here = (row: Row): Row => ({ ...row, here: true });

// Every item of the tree, top to bottom, read against the rows expected: an
// item nobody expected, a missing one and a wrong order all show in the diff.
function rows(expected: Row[]): unknown[] {
	const wanted = expected.map((row) =>
		screen.queryByRole("treeitem", { name: `${row.name}, folder` }),
	);
	return screen.getAllByRole("treeitem").map((item) => {
		const row = expected[wanted.indexOf(item)];
		if (!row) return `an item not expected: ${item.textContent}`;
		const seen: Row = { name: row.name, is: "album" };
		if (row.is !== "album") {
			const expanded = item.getAttribute("aria-expanded");
			if (expanded !== "true" && expanded !== "false")
				return `${row.name} says neither expanded nor collapsed`;
			seen.is = expanded === "true" ? "open" : "closed";
		}
		if (item.getAttribute("aria-current") === "page") seen.here = true;
		return seen;
	});
}

const LETTERS = [closed("A"), closed("N"), closed("S"), closed("#")];

const AT_S = [
	closed("A"),
	closed("N"),
	here(open("S")),
	closed("Sabaton"),
	closed("Sonata Arctica"),
	closed("Stratovarius"),
	closed("#"),
];

const AT_SONATA = [
	closed("A"),
	closed("N"),
	open("S"),
	closed("Sabaton"),
	here(open("Sonata Arctica")),
	albumRow("(1999) Ecliptica"),
	albumRow("(2002) Songs of Silence"),
	closed("Stratovarius"),
	closed("#"),
];

const AT_ECLIPTICA = [
	closed("A"),
	closed("N"),
	open("S"),
	closed("Sabaton"),
	open("Sonata Arctica"),
	here(albumRow("(1999) Ecliptica")),
	albumRow("(2002) Songs of Silence"),
	closed("Stratovarius"),
	closed("#"),
];

const UEMATSU = "植松伸夫";

// A second library, whose names need encoding: `#` unencoded starts a
// fragment, and the artist goes out as UTF-8.
const ODD_NAMES: Shelves = {
	root: { root: "/srv/music/library", readable: true, letters: ["B", "#"] },
	letters: { "#": { artists: [{ name: "10cc" }, { name: UEMATSU }] } },
	artists: { [`#/${UEMATSU}`]: fixtures.artist },
};

const AT_UEMATSU = [
	closed("B"),
	open("#"),
	closed("10cc"),
	here(open(UEMATSU)),
	albumRow("(1999) Ecliptica"),
	albumRow("(2002) Songs of Silence"),
];

describe("the library's tree", () => {
	it("lists the letter folders that exist, in the order served, # last", async () => {
		const { calls } = openAt(libraryAddress());

		await folder("#");
		expect(screen.getByRole("tree")).toHaveAccessibleName();
		expect(rows(LETTERS)).toEqual(LETTERS);
		expect(requested(calls)).toContain("GET /api/library");
	});

	it("opens a letter to its artists, and puts the letter in the address", async () => {
		const { calls, place } = openAt(libraryAddress());

		await userEvent.click(await folder("S"));

		await folder("Stratovarius");
		expect(rows(AT_S)).toEqual(AT_S);
		expect(place()).toBe("/library/S");
		expect(requested(calls)).toContain("GET /api/library/S");
		expect(screen.queryByText("No albums here")).toBeNull();
	});

	it("opens an artist to its albums, and puts the artist in the address", async () => {
		const { calls, place } = openAt(libraryAddress());

		await userEvent.click(await folder("S"));
		await userEvent.click(await folder("Sonata Arctica"));

		await folder("(2002) Songs of Silence");
		expect(rows(AT_SONATA)).toEqual(AT_SONATA);
		expect(place()).toBe("/library/S/Sonata Arctica");
		expect(requested(calls)).toContain("GET /api/library/S/Sonata%20Arctica");
		expect(screen.queryByText("No albums here")).toBeNull();
	});

	it("shows an artist's address opened cold as the clicks left it, with both folders fetched", async () => {
		const { calls, place } = openAt(libraryAddress("S", "Sonata Arctica"));

		await folder("(2002) Songs of Silence");
		expect(rows(AT_SONATA)).toEqual(AT_SONATA);
		expect(place()).toBe("/library/S/Sonata Arctica");
		expect(requested(calls)).toEqual(
			expect.arrayContaining([
				"GET /api/library",
				"GET /api/library/S",
				"GET /api/library/S/Sonata%20Arctica",
			]),
		);
	});

	it("puts a clicked album in the address and marks it in the tree", async () => {
		const { place } = openAt(libraryAddress("S", "Sonata Arctica"));

		await userEvent.click(await folder("(1999) Ecliptica"));

		await waitFor(() =>
			expect(place()).toBe("/library/S/Sonata Arctica/(1999) Ecliptica"),
		);
		await screen.findByRole("treeitem", {
			name: "(1999) Ecliptica, folder",
			current: "page",
		});
		expect(rows(AT_ECLIPTICA)).toEqual(AT_ECLIPTICA);
	});

	it("shows an album's address opened cold with the tree open to the album", async () => {
		openAt(libraryAddress("S", "Sonata Arctica", "(1999) Ecliptica"));

		await folder("(2002) Songs of Silence");
		expect(rows(AT_ECLIPTICA)).toEqual(AT_ECLIPTICA);
	});

	it("asks for the letter # as %23 and for an artist in another script as its UTF-8", async () => {
		const { calls } = openAt(libraryAddress("#", UEMATSU), ODD_NAMES);

		await folder("(2002) Songs of Silence");
		expect(rows(AT_UEMATSU)).toEqual(AT_UEMATSU);
		expect(requested(calls)).toEqual(
			expect.arrayContaining([
				"GET /api/library/%23",
				`GET /api/library/%23/${encodeURIComponent(UEMATSU)}`,
			]),
		);
	});

	// The address a click writes has to survive the reload: a bare `#` in it
	// would be read back as a fragment, and the place would be lost.
	it("shows the same place when the address two clicks left is opened again", async () => {
		const { router } = openAt(libraryAddress(), ODD_NAMES);
		await userEvent.click(await folder("#"));
		await userEvent.click(await folder(UEMATSU));
		await folder("(2002) Songs of Silence");
		expect(rows(AT_UEMATSU)).toEqual(AT_UEMATSU);
		const left = router.history.location.href;

		cleanup();
		const again = openAt(left, ODD_NAMES);

		await folder("(2002) Songs of Silence");
		expect(rows(AT_UEMATSU)).toEqual(AT_UEMATSU);
		expect(requested(again.calls)).toContain("GET /api/library/%23");
	});
});

describe("the library's states", () => {
	// A root other than the box's, so a sentence with the path written into it fails.
	const ELSEWHERE = "/mnt/tank/music";

	it.each([
		["the library", libraryAddress()],
		["an artist", libraryAddress("S", "Sonata Arctica")],
	])(
		"says the root cannot be read, naming it, and shows no tree at the address of %s",
		async (_place, address) => {
			openAt(address, {
				root: { root: ELSEWHERE, readable: false, letters: [] },
			});

			expect(
				await screen.findByText(new RegExp(ELSEWHERE)),
			).toBeInTheDocument();
			expect(screen.queryByRole("tree")).toBeNull();
			expect(screen.queryByRole("treeitem")).toBeNull();
			expect(screen.queryByText("No albums here")).toBeNull();
		},
	);

	it("does not name the root when it can be read", async () => {
		openAt(libraryAddress(), {
			root: { root: ELSEWHERE, readable: true, letters: ["S"] },
		});

		await folder("S");
		expect(screen.queryByText(new RegExp(ELSEWHERE))).toBeNull();
	});

	it("says No albums here for a letter folder with nothing in it", async () => {
		openAt(libraryAddress("N"), { letters: { N: { artists: [] } } });

		expect(await screen.findByText("No albums here")).toBeInTheDocument();
		// The letters are still there to go to.
		expect(screen.getByRole("treeitem", { name: "S, folder" })).toBeVisible();
	});

	it("says No albums here for an artist folder with nothing in it", async () => {
		openAt(libraryAddress("S", "Sabaton"), {
			artists: {
				"S/Sabaton": { albums: [], names: fixtures.artist.names },
			},
		});

		expect(await screen.findByText("No albums here")).toBeInTheDocument();
		expect(
			screen.getByRole("treeitem", { name: "Sonata Arctica, folder" }),
		).toBeVisible();
	});

	it("marks a letter while it loads, keeps the letters, and does not call it empty", async () => {
		const letter = held(fixtures.letter);
		openAt(libraryAddress(), { letters: { S: letter.answer } });

		await userEvent.click(await folder("S"));

		await screen.findByRole("treeitem", { name: "S, folder", busy: true });
		for (const name of ["A", "N", "S", "#"])
			expect(
				screen.getByRole("treeitem", { name: `${name}, folder` }),
			).toBeVisible();
		// A folder not yet answered is not an empty one.
		expect(screen.queryByText("No albums here")).toBeNull();

		letter.release();

		await folder("Stratovarius");
		expect(
			screen.getByRole("treeitem", { name: "S, folder" }),
		).not.toHaveAttribute("aria-busy", "true");
		expect(rows(AT_S)).toEqual(AT_S);
	});

	it("marks an artist while it loads, and keeps the artists beside it", async () => {
		const artist = held(fixtures.artist);
		openAt(libraryAddress("S"), {
			artists: { "S/Sonata Arctica": artist.answer },
		});

		await userEvent.click(await folder("Sonata Arctica"));

		await screen.findByRole("treeitem", {
			name: "Sonata Arctica, folder",
			busy: true,
		});
		for (const name of ["S", "Sabaton", "Sonata Arctica", "Stratovarius"])
			expect(
				screen.getByRole("treeitem", { name: `${name}, folder` }),
			).toBeVisible();
		expect(screen.queryByText("No albums here")).toBeNull();
		// Only the folder loading is marked.
		expect(screen.getAllByRole("treeitem", { busy: true })).toHaveLength(1);

		artist.release();

		await folder("(2002) Songs of Silence");
		expect(rows(AT_SONATA)).toEqual(AT_SONATA);
		expect(screen.queryAllByRole("treeitem", { busy: true })).toHaveLength(0);
	});

	it("keeps an open letter's artists on show while another letter loads", async () => {
		const other = held({ artists: [{ name: "Nightwish" }] });
		openAt(libraryAddress("S"), { letters: { N: other.answer } });
		await folder("Stratovarius");

		await userEvent.click(await folder("N"));

		await screen.findByRole("treeitem", { name: "N, folder", busy: true });
		for (const name of ["Sabaton", "Sonata Arctica", "Stratovarius"])
			expect(
				screen.getByRole("treeitem", { name: `${name}, folder` }),
			).toBeVisible();

		other.release();

		expect(await folder("Nightwish")).toBeVisible();
	});
});
