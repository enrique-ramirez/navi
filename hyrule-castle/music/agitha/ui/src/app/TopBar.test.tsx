import { afterEach, describe, expect, it, vi } from "vitest";

import { libraryAddress } from "@/test/library";
import { renderWithProviders, screen, within } from "@/test/render";

import { TopBar } from "./TopBar";

afterEach(() => {
	vi.unstubAllGlobals();
});

async function barAt(route: string) {
	// jsdom has no matchMedia, and the bar's theme asks it for the system's choice.
	vi.stubGlobal("matchMedia", (query: string) => ({
		matches: false,
		media: query,
		addEventListener: () => {},
		removeEventListener: () => {},
		addListener: () => {},
		removeListener: () => {},
		onchange: null,
		dispatchEvent: () => false,
	}));
	renderWithProviders(<TopBar />, { route });
	const bar = await screen.findByRole("banner");
	return {
		bar,
		nav: within(within(bar).getByRole("navigation")),
	};
}

describe("the top bar", () => {
	it("has Drop and Library after the brand, leading to / and /library", async () => {
		const { bar, nav } = await barAt("/");

		const drop = nav.getByRole("link", { name: "Drop" });
		const library = nav.getByRole("link", { name: "Library" });
		const links = nav.getAllByRole("link");
		expect(links).toHaveLength(2);
		expect(links[0]).toBe(drop);
		expect(links[1]).toBe(library);
		expect(drop).toHaveAttribute("href", "/");
		expect(library).toHaveAttribute("href", "/library");

		const brand = within(bar).getByRole("heading", { name: "agitha" });
		expect(
			brand.compareDocumentPosition(drop) & Node.DOCUMENT_POSITION_FOLLOWING,
		).toBeTruthy();
	});

	it("marks Drop as the current page at /", async () => {
		const { nav } = await barAt("/");

		expect(nav.getByRole("link", { name: "Drop" })).toHaveAttribute(
			"aria-current",
			"page",
		);
		expect(nav.getByRole("link", { name: "Library" })).not.toHaveAttribute(
			"aria-current",
		);
	});

	it.each([
		["the library", libraryAddress()],
		["a letter", libraryAddress("S")],
		["an artist", libraryAddress("S", "Sonata Arctica")],
		["an album", libraryAddress("S", "Sonata Arctica", "(1999) Ecliptica")],
		["the letter #", libraryAddress("#")],
	])("marks Library as the current page at %s (%s)", async (_place, route) => {
		const { nav } = await barAt(route);

		expect(nav.getByRole("link", { name: "Library" })).toHaveAttribute(
			"aria-current",
			"page",
		);
		expect(nav.getByRole("link", { name: "Drop" })).not.toHaveAttribute(
			"aria-current",
		);
	});

	// Whether Drop is current on a review page is the owner's to say, so only
	// Library is pinned here.
	it("does not mark Library on an album's review page", async () => {
		const { nav } = await barAt("/drops/20260929-210000/albums/07");

		expect(nav.getByRole("link", { name: "Library" })).not.toHaveAttribute(
			"aria-current",
		);
	});
});
