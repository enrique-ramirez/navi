import { afterEach, describe, expect, it } from "vitest";

import type { AlbumView, Drop } from "@/shared/api/types";
import { fakeFetch } from "@/test/fakeFetch";
import { libraryAddress, libraryHandlers } from "@/test/library";
import { screen, userEvent, waitFor, within } from "@/test/render";
import { renderApp } from "@/test/renderApp";

const DROP = "20260929-210000";

const listed: Drop = {
	id: DROP,
	state: "ready",
	started: "2026-09-29T21:00:00",
	items: [],
	ignored: [],
	refused: [],
	albums: [
		{
			n: "07",
			name: "Pariahs Child rip",
			state: "ready",
			title: "Pariah's Child",
			artist: "Sonata Arctica",
			year: "2014",
			destination: null,
			duplicate_of: null,
			replaces: null,
			stderr: "",
			error: null,
			busy: false,
			actions: ["discard"],
		},
	],
	actions: ["discard"],
	received: { files: 0, bytes: 0 },
	error: null,
};

// Album 07 as its page loads it, before identify has written a preview.
const album: AlbumView = {
	drop: DROP,
	n: "07",
	name: "Pariahs Child rip",
	state: "queued",
	stderr: "",
	error: null,
	step: null,
	file: null,
	busy: true,
	preview: null,
	files: [],
	uploaded: [],
	names: { id3: {}, vorbis: {}, mp4: {}, asf: {} },
	library_path: null,
	tree: [],
	extras_to: [],
	decision: null,
	cover: null,
	cover_now: null,
	duplicate: null,
	approvable: { ok: false, reason: null, code: "busy", hold: null },
	replaces: null,
	suggestions: [],
	keep: null,
};

let server: ReturnType<typeof fakeFetch> | undefined;

afterEach(() => {
	server?.restore();
	server = undefined;
});

function openAt(address: string) {
	server = fakeFetch({
		"GET /api/drops": () => Response.json([listed]),
		[`GET /api/drops/${DROP}/albums/07`]: () => Response.json(album),
		...libraryHandlers(),
	});
	return renderApp(address);
}

function barLink(name: string) {
	const bar = within(screen.getByRole("banner"));
	return within(bar.getByRole("navigation")).getByRole("link", { name });
}

// Album 07, so the number cannot be read out of the drop's id.
const ALBUM_NUMBER = /(^|\D)07(\D|$)/;

describe("routes", () => {
	it("opens an album from its address with the drop and the album number on screen", async () => {
		openAt(`/drops/${DROP}/albums/07`);

		expect(await screen.findByText(new RegExp(DROP))).toBeInTheDocument();
		expect(screen.getAllByText(ALBUM_NUMBER).length).toBeGreaterThan(0);
		expect(
			screen.queryByRole("region", { name: "Drop music here" }),
		).toBeNull();
	});

	it("shows the drop area above the list of drops at /", async () => {
		openAt("/");

		const area = await screen.findByRole("region", { name: "Drop music here" });
		const heading = await screen.findByRole("heading", {
			name: new RegExp(DROP),
		});
		// DOCUMENT_POSITION_FOLLOWING: the list comes after the drop area.
		expect(
			area.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING,
		).toBeTruthy();
	});

	it("opens an album from the list's Open link", async () => {
		const router = openAt("/");

		await userEvent.click(await screen.findByRole("link", { name: /^Open/ }));

		await waitFor(() =>
			expect(router.state.location.pathname).toBe(`/drops/${DROP}/albums/07`),
		);
		// The home screen holds the id too, so the album screen is known by the drop area going.
		await waitFor(() =>
			expect(
				screen.queryByRole("region", { name: "Drop music here" }),
			).toBeNull(),
		);
		expect(screen.getByText(new RegExp(DROP))).toBeInTheDocument();
	});

	it("says not found at an address the page has no screen for", async () => {
		openAt("/nowhere/at/all");

		expect(await screen.findByText(/not found/i)).toBeInTheDocument();
		expect(
			screen.queryByRole("region", { name: "Drop music here" }),
		).toBeNull();
	});

	it.each([
		["the library", libraryAddress()],
		["a letter", libraryAddress("S")],
		["an artist", libraryAddress("S", "Sonata Arctica")],
		["an album", libraryAddress("S", "Sonata Arctica", "(1999) Ecliptica")],
	])(
		"opens the library's tree at the address of %s (%s)",
		async (_place, address) => {
			openAt(address);

			expect(await screen.findByRole("tree")).toBeInTheDocument();
			expect(screen.queryByText(/not found/i)).toBeNull();
			expect(
				screen.queryByRole("region", { name: "Drop music here" }),
			).toBeNull();
		},
	);

	it("opens the library from the bar's Library link, and marks it current", async () => {
		const router = openAt("/");
		await screen.findByRole("region", { name: "Drop music here" });

		await userEvent.click(barLink("Library"));

		expect(await screen.findByRole("tree")).toBeInTheDocument();
		expect(router.state.location.pathname).toBe("/library");
		expect(
			screen.queryByRole("region", { name: "Drop music here" }),
		).toBeNull();
		expect(barLink("Library")).toHaveAttribute("aria-current", "page");
		expect(barLink("Drop")).not.toHaveAttribute("aria-current");
	});

	it("returns to the drop page from the bar's Drop link, and marks it current", async () => {
		const router = openAt(libraryAddress("S", "Sonata Arctica"));
		await screen.findByRole("tree");

		await userEvent.click(barLink("Drop"));

		expect(
			await screen.findByRole("region", { name: "Drop music here" }),
		).toBeInTheDocument();
		expect(router.state.location.pathname).toBe("/");
		expect(screen.queryByRole("tree")).toBeNull();
		expect(barLink("Drop")).toHaveAttribute("aria-current", "page");
		expect(barLink("Library")).not.toHaveAttribute("aria-current");
	});
});
