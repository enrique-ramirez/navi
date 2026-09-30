import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createAppRouter } from "@/app/router";
import type { Drop } from "@/shared/api/types";
import { fakeFetch } from "@/test/fakeFetch";
import { screen, userEvent, waitFor } from "@/test/render";

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

let server: ReturnType<typeof fakeFetch> | undefined;

afterEach(() => {
	server?.restore();
	server = undefined;
});

// The app's own routes, so this renders the router itself; the test helper
// brings a router of its own and cannot take these.
function openAt(address: string) {
	server = fakeFetch({ "GET /api/drops": () => Response.json([listed]) });
	// jsdom has no matchMedia, and the shell's theme asks it for the system's choice.
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
	const router = createAppRouter(
		createMemoryHistory({ initialEntries: [address] }),
	);
	render(
		<QueryClientProvider
			client={
				new QueryClient({ defaultOptions: { queries: { retry: false } } })
			}
		>
			<RouterProvider router={router} />
		</QueryClientProvider>,
	);
	return router;
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
});
