import { describe, expect, it } from "vitest";

import type { AlbumView, Candidate, PlanEntry } from "@/shared/api/types";
import autoClean from "@/test/fixtures/auto-clean/plan.json";
import { renderWithProviders, screen, userEvent, within } from "@/test/render";

import { Candidates } from "./Candidates";
import { usePending } from "./pending";

const CD_ID = "6f1a2b3c-0000-4000-8000-000100000001";
const DIGITAL_ID = "6f1a2b3c-0000-4000-8000-000100000002";
const MBID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d";

// The fixture's one candidate is the preview's release. A second one differs
// in every field, and comes first so a page marking the first as chosen shows.
function view(): AlbumView {
	const entry = structuredClone(autoClean.albums[0]) as PlanEntry;
	const [cd] = entry.candidates as [Candidate];
	const digital: Candidate = {
		...cd,
		release_id: DIGITAL_ID,
		title: "Clean Album (Deluxe)",
		artist: "The Clean Band feat. Nobody",
		date: "2011-03",
		country: "XW",
		format: "Digital Media",
		track_counts: [12, 10],
		matches_counts: false,
		duration_diff: 1904.2,
		thumbnail: `https://coverartarchive.org/release/${DIGITAL_ID}/front-250`,
	};
	entry.candidates = [digital, cd];
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
		preview: entry,
		files: [],
		names: { id3: {}, vorbis: {}, mp4: {}, asf: {} },
		library_path: `/srv/music/library/${entry.destination}`,
		tree: [],
		extras_to: [],
		decision: null,
		cover: null,
		duplicate: null,
		approvable: { ok: true, reason: null, code: null, hold: null },
	};
}

// The pending decision is state with no element of its own until Update
// preview sends it, so the harness prints it, and only a test id can reach it.
function Harness({ album }: { album: AlbumView }) {
	const pending = usePending(album);
	return (
		<>
			<Candidates view={album} pending={pending} />
			<pre data-testid="draft">{JSON.stringify(pending.draft)}</pre>
		</>
	);
}

const draftText = () => screen.getByTestId("draft").textContent ?? "";
const draft = () => JSON.parse(draftText());

async function render() {
	renderWithProviders(<Harness album={view()} />);
	// The helper's router mounts the component after a tick.
	const list = await screen.findByRole("list", { name: "Candidates" });
	const item = (thumbnail: string) =>
		within(list)
			.getAllByRole("listitem")
			.find((li) => within(li).queryByRole("img", { name: thumbnail }));
	return {
		list,
		cd: () => item("Clean Album thumbnail"),
		digital: () => item("Clean Album (Deluxe) thumbnail"),
	};
}

const current = (list: HTMLElement) =>
	within(list)
		.getAllByRole("listitem")
		.filter((li) => li.getAttribute("aria-current") === "true");

const CHOOSE = { name: /^choose\b/i };

describe("Candidates", () => {
	it("shows each candidate's thumbnail, title, artist, date, country, format and track counts", async () => {
		const { list, cd, digital } = await render();

		expect(within(list).getAllByRole("listitem")).toHaveLength(2);

		const d = digital()!;
		expect(
			within(d).getByRole("img", { name: "Clean Album (Deluxe) thumbnail" }),
		).toHaveAttribute(
			"src",
			`https://coverartarchive.org/release/${DIGITAL_ID}/front-250`,
		);
		for (const text of [
			"Clean Album (Deluxe)",
			"The Clean Band feat. Nobody",
			"2011-03",
			"XW",
			"Digital Media",
			"12 + 10",
		]) {
			expect(d).toHaveTextContent(text);
		}

		const c = cd()!;
		expect(
			within(c).getByRole("img", { name: "Clean Album thumbnail" }),
		).toHaveAttribute(
			"src",
			`https://coverartarchive.org/release/${CD_ID}/front-250`,
		);
		for (const text of [
			"Clean Album",
			"Clean Band",
			"2010-05-24",
			"GB",
			"CD",
		]) {
			expect(c).toHaveTextContent(text);
		}
		// One medium of three tracks, and none of the other candidate's values.
		expect(c).toHaveTextContent(/\b3\b/);
		expect(c).not.toHaveTextContent("12 + 10");
		expect(c).not.toHaveTextContent("Digital Media");
	});

	it("marks the preview's release as chosen, and offers Choose on the other one only", async () => {
		const { list, cd, digital } = await render();

		expect(current(list)).toEqual([cd()]);
		expect(cd()).toHaveTextContent(/\bchosen\b/);
		expect(within(cd()!).queryByRole("button", CHOOSE)).not.toBeInTheDocument();

		expect(digital()).not.toHaveTextContent(/\bchosen\b/);
		expect(within(digital()!).getByRole("button", CHOOSE)).toBeEnabled();
	});

	it("moves the chosen mark and the pending decision's release to the candidate chosen", async () => {
		const { list, cd, digital } = await render();

		await userEvent.click(within(digital()!).getByRole("button", CHOOSE));

		expect(current(list)).toEqual([digital()]);
		expect(digital()).toHaveTextContent(/\bchosen\b/);
		expect(cd()).not.toHaveTextContent(/\bchosen\b/);
		expect(within(cd()!).getByRole("button", CHOOSE)).toBeEnabled();
		expect(draft()).toMatchObject({ action: "accept", release_id: DIGITAL_ID });
	});

	it.each([
		["a release URL", `https://musicbrainz.org/release/${MBID}`],
		["a bare MBID", MBID],
	])(
		"turns the pending decision into a repoint of %s pasted",
		async (_, pasted) => {
			await render();

			await userEvent.type(
				screen.getByRole("textbox", {
					name: "MusicBrainz release URL or MBID",
				}),
				pasted,
			);
			await userEvent.click(
				screen.getByRole("button", { name: "Use this release" }),
			);

			expect(draft()).toEqual({ action: "repoint", release: pasted });
			expect(
				screen.queryByText("not a MusicBrainz release"),
			).not.toBeInTheDocument();
		},
	);

	// A release group's URL carries a UUID too, and the engine's release_ref
	// refuses it: it names no one release.
	it.each([
		["plain text", "hello"],
		["a release group's URL", `https://musicbrainz.org/release-group/${MBID}`],
	])(
		"says `not a MusicBrainz release` for %s and leaves the pending decision alone",
		async (_, pasted) => {
			await render();
			const before = draftText();

			await userEvent.type(
				screen.getByRole("textbox", {
					name: "MusicBrainz release URL or MBID",
				}),
				pasted,
			);
			await userEvent.click(
				screen.getByRole("button", { name: "Use this release" }),
			);

			expect(
				await screen.findByText(/not a MusicBrainz release/),
			).toBeInTheDocument();
			expect(draftText()).toBe(before);
		},
	);
});
