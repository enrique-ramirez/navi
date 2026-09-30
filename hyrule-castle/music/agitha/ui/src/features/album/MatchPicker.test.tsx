import { afterEach, describe, expect, it } from "vitest";

import { releaseUrl } from "@/domain/album/match";
import type { AlbumView } from "@/shared/api/types";
import { albumView, candidate } from "@/test/albumView";
import { renderWithProviders, screen, userEvent, within } from "@/test/render";

import { MatchPicker } from "./MatchPicker";
import { type Pending, usePending } from "./pending";

const id = (n: number) => `6f1a2b3c-0000-4000-8000-00010000000${n}`;

// Out of order on purpose: the list must sort them by how well they fit.
const CANDIDATES = [
	candidate({
		release_id: id(3),
		title: "Clean Album Live",
		track_counts: [12],
		matches_counts: false,
		failing_tracks: null,
	}),
	candidate({
		release_id: id(4),
		title: "Clean Album Box",
		checked: false,
		matches_counts: false,
	}),
	candidate({
		release_id: id(2),
		title: "Clean Album Deluxe",
		duration_diff: 40,
	}),
	candidate({ release_id: id(1), title: "Clean Album" }),
];

function view(): AlbumView {
	const v = albumView();
	v.preview!.candidates = CANDIDATES;
	v.preview!.release_id = id(1);
	return v;
}

let latest: Pending | undefined;

function Picker({ view }: { view: AlbumView }) {
	const pending = usePending(view);
	latest = pending;
	return <MatchPicker view={view} pending={pending} />;
}

async function trigger() {
	return screen.findByRole("button", { expanded: false });
}

async function open(user: ReturnType<typeof userEvent.setup>) {
	await user.click(await trigger());
	return screen.getByRole("list", { name: "MusicBrainz release" });
}

// The name each choose button starts with: the candidate's title.
const titles = (list: HTMLElement) =>
	within(list)
		.getAllByRole("listitem")
		.map(
			(item) =>
				within(item).getAllByRole("button")[0]?.textContent?.split(" · ")[0] ??
				"",
		);

describe("MatchPicker", () => {
	afterEach(() => {
		latest = undefined;
	});

	it("shows the chosen release with how well it fits and why, and links it on MusicBrainz", async () => {
		renderWithProviders(<Picker view={view()} />);

		const chosen = await trigger();
		expect(chosen).toHaveTextContent("Clean Album · Clean Band");
		expect(chosen).toHaveTextContent("Strong match");
		expect(chosen).toHaveTextContent(
			"3 tracks, like the folder · same length · artist agrees",
		);
		expect(chosen).toHaveTextContent("4 found");
		expect(
			screen.getByRole("link", { name: "Open Clean Album on MusicBrainz" }),
		).toHaveAttribute("href", releaseUrl(id(1)));
	});

	it("lists the releases best fit first, with the unchecked ones set apart", async () => {
		const user = userEvent.setup();
		renderWithProviders(<Picker view={view()} />);

		const list = await open(user);
		expect(titles(list)).toEqual([
			"Clean Album",
			"Clean Album Deluxe",
			"Clean Album Live",
		]);
		const items = within(list).getAllByRole("listitem");
		expect(items[1]).toHaveTextContent("Possible match");
		expect(items[1]).toHaveTextContent("length off by 40 s");
		expect(items[2]).toHaveTextContent("Weak match");
		expect(items[2]).toHaveTextContent("12 tracks, the folder has 3");
		expect(items[0]).toHaveAttribute("aria-current", "true");

		const more = screen.getByText("1 more that musiclib didn't check");
		const unchecked = more.closest("details");
		expect(unchecked).not.toBeNull();
		expect(unchecked).toHaveTextContent("Clean Album Box");
		expect(unchecked).toHaveTextContent("Not checked");
		expect(within(list).queryByText(/Clean Album Box/)).toBeNull();
	});

	it("chooses another release and closes the list", async () => {
		const user = userEvent.setup();
		renderWithProviders(<Picker view={view()} />);

		const list = await open(user);
		const deluxe = within(list)
			.getAllByRole("listitem")
			.find((item) => item.textContent?.startsWith("Clean Album Deluxe"));
		await user.click(within(deluxe!).getAllByRole("button")[0]!);

		expect(
			screen.queryByRole("list", { name: "MusicBrainz release" }),
		).not.toBeInTheDocument();
		const chosen = await trigger();
		expect(chosen).toHaveTextContent("Clean Album Deluxe");
		expect(chosen).toHaveTextContent("Possible match");
		expect(
			screen.getByRole("link", {
				name: "Open Clean Album Deluxe on MusicBrainz",
			}),
		).toHaveAttribute("href", releaseUrl(id(2)));
		expect(latest?.draft).toMatchObject({
			action: "accept",
			release_id: id(2),
		});
	});

	it("closes the list on Escape without choosing", async () => {
		const user = userEvent.setup();
		renderWithProviders(<Picker view={view()} />);

		await open(user);
		await user.keyboard("{Escape}");

		expect(
			screen.queryByRole("list", { name: "MusicBrainz release" }),
		).not.toBeInTheDocument();
		expect(latest?.draft).toMatchObject({ release_id: id(1) });
	});

	it.each([
		["a release URL", `https://musicbrainz.org/release/${id(9)}`],
		["a bare MBID", id(9)],
	])("chooses %s pasted in", async (_, pasted) => {
		const user = userEvent.setup();
		renderWithProviders(<Picker view={view()} />);

		await open(user);
		await user.type(
			screen.getByRole("textbox", { name: "MusicBrainz release URL or MBID" }),
			pasted,
		);
		await user.click(screen.getByRole("button", { name: "Use this release" }));

		const chosen = await trigger();
		expect(chosen).toHaveTextContent("Release you pasted");
		expect(chosen).toHaveTextContent(id(9));
		expect(latest?.draft).toMatchObject({
			action: "accept",
			release_id: id(9),
		});
	});

	it.each([
		["a release group's URL", `https://musicbrainz.org/release-group/${id(9)}`],
		["another site", `https://example.org/release/${id(9)}`],
		["words", "clean album"],
	])("refuses %s", async (_, pasted) => {
		const user = userEvent.setup();
		renderWithProviders(<Picker view={view()} />);

		await open(user);
		await user.type(
			screen.getByRole("textbox", { name: "MusicBrainz release URL or MBID" }),
			`${pasted}{Enter}`,
		);

		expect(screen.getByRole("alert")).toHaveTextContent(
			"not a MusicBrainz release",
		);
		expect(latest?.draft).toMatchObject({
			action: "accept",
			release_id: id(1),
		});
	});
});
