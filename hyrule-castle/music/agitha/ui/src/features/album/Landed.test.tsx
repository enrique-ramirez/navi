import { afterEach, describe, expect, it } from "vitest";

import type { AlbumSummary, Drop } from "@/shared/api/types";
import { albumView, DROP } from "@/test/albumView";
import { fakeFetch } from "@/test/fakeFetch";
import { renderWithProviders, screen } from "@/test/render";

import { Landed } from "./Landed";

const LIBRARY_PATH = "/srv/music/library/C/Clean/(2020) Clean Album";

function summary(n: string, state: AlbumSummary["state"]): AlbumSummary {
	return {
		n,
		name: `Album ${n}`,
		state,
		title: `Title ${n}`,
		artist: null,
		year: null,
		destination: null,
		duplicate_of: null,
		replaces: null,
		stderr: "",
		error: null,
		busy: false,
		actions: [],
	};
}

function serveDrop(albums: AlbumSummary[]) {
	const drop = { id: DROP, state: "ready", albums } as unknown as Drop;
	return fakeFetch({ "GET /api/drops": () => Response.json([drop]) });
}

const landed = () =>
	albumView({ state: "in the library", library_path: LIBRARY_PATH });

describe("Landed", () => {
	let restore: (() => void) | undefined;

	afterEach(() => {
		restore?.();
		restore = undefined;
	});

	it("says where the album went and offers the next album of the drop still to review", async () => {
		restore = serveDrop([
			summary("01", "in the library"),
			summary("02", "ready"),
		]).restore;
		renderWithProviders(<Landed view={landed()} />);

		expect(
			await screen.findByRole("heading", { name: /is in the library$/ }),
		).toBeInTheDocument();
		expect(screen.getByText(LIBRARY_PATH)).toBeInTheDocument();
		expect(
			await screen.findByRole("link", { name: "Next: Title 02" }),
		).toHaveAttribute("href", `/drops/${DROP}/albums/02`);
		expect(screen.getByRole("link", { name: "Back to drops" })).toHaveAttribute(
			"href",
			"/",
		);
	});

	it("offers only the way home once every album of the drop is done", async () => {
		restore = serveDrop([
			summary("01", "in the library"),
			summary("02", "in the library"),
		]).restore;
		renderWithProviders(<Landed view={landed()} />);

		expect(
			await screen.findByRole("link", { name: "Back to drops" }),
		).toBeInTheDocument();
		expect(
			screen.queryByRole("link", { name: /^Next:/ }),
		).not.toBeInTheDocument();
	});
});
