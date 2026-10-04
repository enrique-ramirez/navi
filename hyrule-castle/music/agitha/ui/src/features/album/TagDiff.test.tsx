import { act } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { diffOf } from "@/domain/album/diff";
import type { AlbumView } from "@/shared/api/types";
import { albumView } from "@/test/albumView";
import { fakeFetch } from "@/test/fakeFetch";
import genres from "@/test/fixtures/library/genres.json";
import { renderWithProviders, screen, userEvent, within } from "@/test/render";

import { type Pending, usePending } from "./pending";
import { TagDiff } from "./TagDiff";

const ALL = ["1-1", "1-2", "1-3"];
const TABLE = "Tags on all 3 tracks";

let latest: Pending | undefined;

// The album's shared tags as the page lays them out, rebuilt from the draft on every change.
function AlbumTags({ view }: { view: AlbumView }) {
	const pending = usePending(view);
	latest = pending;
	const edits = pending.draft.action === "accept" ? pending.draft.edits : {};
	return (
		<TagDiff
			view={view}
			pending={pending}
			rows={diffOf(view, edits).album}
			scope="all"
			family="id3"
			label={TABLE}
		/>
	);
}

function renderTags(view = albumView()) {
	renderWithProviders(<AlbumTags view={view} />);
	return screen.findByRole("table", { name: TABLE });
}

// The row whose header names `tag`, with or without the edited mark.
function rowOf(tag: string) {
	const row = within(screen.getByRole("table", { name: TABLE }))
		.getAllByRole("row")
		.find((each) => {
			const header = within(each).queryByRole("rowheader");
			return header?.textContent?.replace("edited by you", "") === tag;
		});
	if (!row) throw new Error(`no row for ${tag}`);
	return row;
}

const queryRow = (tag: string) => {
	try {
		return rowOf(tag);
	} catch {
		return null;
	}
};

const input = (tag: string) =>
	screen.getByRole("textbox", { name: `New ${tag}` });

// What the draft sends for `key` on every track.
const sent = (key: string) =>
	ALL.map((position) =>
		latest?.draft.action === "accept"
			? latest.draft.edits[position]?.[key]
			: undefined,
	);

describe("TagDiff", () => {
	afterEach(() => {
		latest = undefined;
	});

	it("shows each tag as it is now and as it will be written", async () => {
		const table = await renderTags();

		expect(
			within(table)
				.getAllByRole("columnheader")
				.map((header) => header.textContent),
		).toEqual(["Tag", "Current", "New", "Actions"]);
		expect(within(rowOf("Date")).getByText("1989")).toBeInTheDocument();
		expect(input("Date")).toHaveValue("2010-05-24");
		expect(input("Album")).toHaveValue("Clean Album");
		// A tag the files lack now shows a dash for its current value.
		expect(within(rowOf("Genre")).getByText("—")).toBeInTheDocument();
		expect(input("Genre")).toHaveValue("rock");
	});

	it("records a new value on every track once the field is left, and marks the row", async () => {
		const user = userEvent.setup();
		await renderTags();

		await user.clear(input("Date"));
		await user.type(input("Date"), "2011");
		await user.tab();

		expect(sent("TDRC")).toEqual([["2011"], ["2011"], ["2011"]]);
		expect(
			within(rowOf("Date")).getByText("edited by you"),
		).toBeInTheDocument();
		expect(
			within(rowOf("Date")).getByRole("button", {
				name: "Undo your edit of Date",
			}),
		).toBeInTheDocument();
	});

	it("splits values on semicolons and edits the genre under its neutral name", async () => {
		const user = userEvent.setup();
		await renderTags();

		await user.clear(input("Genre"));
		await user.type(input("Genre"), "rock; jazz ;;{Enter}");

		expect(sent("genre")).toEqual([
			["rock", "jazz"],
			["rock", "jazz"],
			["rock", "jazz"],
		]);
		expect(sent("TCON")).toEqual([undefined, undefined, undefined]);
		expect(input("Genre")).toHaveValue("rock; jazz");
	});

	it("puts the field back on Escape without recording anything", async () => {
		const user = userEvent.setup();
		await renderTags();

		await user.clear(input("Album"));
		await user.type(input("Album"), "Oops{Escape}");

		expect(input("Album")).toHaveValue("Clean Album");
		await user.tab();
		expect(latest?.dirty).toBe(false);
	});

	it("drops the edit when a value is set back to what the plan writes", async () => {
		const user = userEvent.setup();
		await renderTags();

		await user.clear(input("Date"));
		await user.type(input("Date"), "2011{Enter}");
		await user.clear(input("Date"));
		await user.type(input("Date"), "2010-05-24{Enter}");

		expect(latest?.dirty).toBe(false);
		expect(
			within(rowOf("Date")).queryByText("edited by you"),
		).not.toBeInTheDocument();
	});

	it("removes a tag with the trash button, and the undo button brings it back", async () => {
		const user = userEvent.setup();
		await renderTags();

		await user.click(
			within(rowOf("Date")).getByRole("button", { name: "Remove Date" }),
		);

		expect(sent("TDRC")).toEqual([null, null, null]);
		expect(input("Date")).toHaveValue("");
		expect(input("Date")).toHaveAttribute("placeholder", "removed");

		await user.click(
			within(rowOf("Date")).getByRole("button", {
				name: "Undo your edit of Date",
			}),
		);

		expect(latest?.dirty).toBe(false);
		expect(input("Date")).toHaveValue("2010-05-24");
	});

	// What the draft holds for a track, whole.
	const editsOf = (position: string) =>
		latest?.draft.action === "accept"
			? latest.draft.edits[position]
			: undefined;

	// A typed album artist goes out under the neutral name `albumartist`. A
	// removal goes under `TPE2` alone: identify stops on a neutral field that
	// has no value, for any file that is not a FLAC.
	it("removes the album artist of MP3s under TPE2 alone, with nothing under the neutral name", async () => {
		const user = userEvent.setup();
		await renderTags();

		await user.click(
			within(rowOf("Album artist")).getByRole("button", {
				name: "Remove Album artist",
			}),
		);

		expect(ALL.map(editsOf)).toEqual([
			{ TPE2: null },
			{ TPE2: null },
			{ TPE2: null },
		]);
		expect(input("Album artist")).toHaveValue("");
		expect(input("Album artist")).toHaveAttribute("placeholder", "removed");
	});

	// Emptying the field is the same removal. The name typed before it is
	// not left behind under the neutral name to name a folder.
	it("removes the album artist under TPE2 alone when a typed one is emptied", async () => {
		const user = userEvent.setup();
		await renderTags();
		await user.clear(input("Album artist"));
		await user.type(input("Album artist"), "Other Band{Enter}");
		expect(input("Album artist")).toHaveValue("Other Band");

		await user.clear(input("Album artist"));
		await user.keyboard("{Enter}");

		expect(ALL.map(editsOf)).toEqual([
			{ TPE2: null },
			{ TPE2: null },
			{ TPE2: null },
		]);
		expect(input("Album artist")).toHaveAttribute("placeholder", "removed");
	});

	it("offers no field and no remove for a tag that comes from the release", async () => {
		await renderTags();

		const row = rowOf("TXXX:MusicBrainz Album Id");
		expect(within(row).queryByRole("textbox")).toBeNull();
		expect(within(row).queryByRole("button")).toBeNull();
		// Now and New, the same.
		expect(
			within(row).getAllByText("6f1a2b3c-0000-4000-8000-000100000001"),
		).toHaveLength(2);
	});

	it("shows the ADDED stamp read-only, saying where it comes from", async () => {
		const view = albumView();
		for (const file of view.preview!.files)
			file.after["TXXX:ADDED"] = ["2026-09-30T11:02"];
		await renderTags(view);

		const row = rowOf("TXXX:ADDED");
		expect(within(row).queryByRole("textbox")).toBeNull();
		expect(within(row).queryByRole("button")).toBeNull();
		expect(
			within(row).getByTitle("stamped on import with the upload time"),
		).toHaveTextContent("2026-09-30T11:02");
	});

	it("says which engine rule removes a tag", async () => {
		const view = albumView();
		for (const file of view.preview!.files) file.before["TXXX:JUNK"] = ["x"];
		view.preview!.residue = [
			{
				file: view.preview!.files[0]!.source,
				key: "TXXX:JUNK",
				value: null,
				rule: "unknown frame",
			},
		];
		await renderTags(view);

		expect(
			within(rowOf("TXXX:JUNK")).getByText("removed: unknown frame"),
		).toBeInTheDocument();
	});

	it("keeps a tag the plan removes, as an editable value", async () => {
		const view = albumView();
		for (const file of view.preview!.files) file.before["TXXX:MOOD"] = ["calm"];
		await renderTags(view);
		const user = userEvent.setup();

		await user.click(
			within(rowOf("TXXX:MOOD")).getByRole("button", {
				name: "Keep the current TXXX:MOOD, then edit it",
			}),
		);

		expect(sent("TXXX:MOOD")).toEqual([["calm"], ["calm"], ["calm"]]);
		expect(input("TXXX:MOOD")).toHaveValue("calm");
	});

	it("takes a typed value for a tag the plan removes, where the tracks hold different ones", async () => {
		const view = albumView();
		view.preview!.files.forEach((file, index) => {
			file.before["TXXX:MOOD"] = [`mood ${index}`];
		});
		await renderTags(view);
		const user = userEvent.setup();

		await user.type(input("TXXX:MOOD"), "calm{Enter}");

		expect(sent("TXXX:MOOD")).toEqual([["calm"], ["calm"], ["calm"]]);
		expect(input("TXXX:MOOD")).toHaveValue("calm");
	});

	describe("the genre of an album that has none", () => {
		let fake: ReturnType<typeof fakeFetch> | undefined;

		afterEach(() => fake?.restore());

		// No file and no plan holds a genre, as MusicBrainz knows none for the release.
		async function renderGenreless() {
			fake = fakeFetch({ "GET /api/genres": () => Response.json(genres) });
			const view = albumView();
			for (const file of view.preview!.files) delete file.after.TCON;
			await renderTags(view);
			return userEvent.setup();
		}

		it("is typed into its own row, and goes out under the neutral name on every track", async () => {
			const user = await renderGenreless();

			await user.type(input("Genre"), "jazz{Enter}");

			expect(sent("genre")).toEqual([["jazz"], ["jazz"], ["jazz"]]);
			expect(input("Genre")).toHaveValue("jazz");
		});

		it("offers the list's genres for the value being typed, and a picked one makes way for the next", async () => {
			const user = await renderGenreless();

			await user.type(input("Genre"), "pow");
			await user.click(
				await screen.findByRole("option", { name: "power metal" }),
			);
			expect(input("Genre")).toHaveValue("power metal; ");

			await user.type(input("Genre"), "sym{ArrowDown}{Enter}");
			expect(input("Genre")).toHaveValue("power metal; symphonic metal; ");

			await user.keyboard("{Enter}");
			const both = ["power metal", "symphonic metal"];
			expect(sent("genre")).toEqual([both, both, both]);
		});

		it("refuses a genre that is not on the list, and sends nothing", async () => {
			const user = await renderGenreless();

			await user.type(input("Genre"), "po");
			await screen.findByRole("option", { name: "power metal" });
			await user.type(input("Genre"), "lka{Enter}");

			expect(screen.getByRole("alert")).toHaveTextContent(
				"polka is not a genre on the list",
			);
			expect(sent("genre")).toEqual([undefined, undefined, undefined]);
		});

		it("takes the genre typed with its values into the field for a new tag", async () => {
			const user = await renderGenreless();

			await user.type(
				screen.getByRole("textbox", { name: "Tag key" }),
				"Genre: rock; jazz",
			);
			await user.click(screen.getByRole("button", { name: "Add tag" }));

			const both = ["rock", "jazz"];
			expect(sent("genre")).toEqual([both, both, both]);
			expect(queryRow("Genre: rock; jazz")).toBeNull();
		});
	});

	describe("the artists a credit names", () => {
		let fake: ReturnType<typeof fakeFetch> | undefined;

		afterEach(() => fake?.restore());

		const MARSHMELLO = {
			id: "c0c5b0b9-0000-4000-8000-0000000000a1",
			name: "Marshmello",
			disambiguation: "US electronic music producer and DJ",
			type: "Person",
			country: "US",
		};
		const ARTISTS = "Artists (one value per artist)";

		const searches = () =>
			fake!.calls.filter((call) => call.url.includes("/api/artists"));

		// `answers` are served one per search, the last one for every search after it.
		async function renderWithArtists(
			answers: object[] = [{ answered: true, artists: [MARSHMELLO] }],
		) {
			fake = fakeFetch({
				"GET /api/genres": () => Response.json(genres),
				"GET /api/artists": () =>
					Response.json(
						answers[Math.min(searches().length, answers.length) - 1],
					),
			});
			const view = albumView();
			view.names.id3 = { ...view.names.id3, "TXXX:ARTISTS": "Artists" };
			await renderTags(view);
			return userEvent.setup();
		}

		it("have a row of their own, named for what it holds, that says the credit stands as one act until an artist is typed", async () => {
			await renderWithArtists();

			expect(input(ARTISTS)).toHaveValue("");
			expect(input(ARTISTS)).toHaveAttribute(
				"placeholder",
				"one act, as credited",
			);
		});

		it("are searched for on MusicBrainz by the name being typed, shown with what tells each apart, and written one value each", async () => {
			const user = await renderWithArtists();

			await user.type(input(ARTISTS), "Future; marsh");
			expect(screen.getByRole("status")).toHaveTextContent(
				"Searching MusicBrainz",
			);
			const found = await screen.findByRole("option", { name: /^Marshmello/ });
			expect(found).toHaveTextContent(
				"Person \u00b7 US \u00b7 US electronic music producer and DJ",
			);
			expect(screen.queryByRole("status")).toBeNull();
			expect(searches().at(-1)?.url).toMatch(/\?q=marsh$/);

			await user.click(found);
			expect(input(ARTISTS)).toHaveValue("Future; Marshmello; ");

			await user.keyboard("{Enter}");
			const both = ["Future", "Marshmello"];
			expect(sent("TXXX:ARTISTS")).toEqual([both, both, both]);
		});

		it("says so where MusicBrainz knows nobody by the name, and Search again asks it once more", async () => {
			const user = await renderWithArtists([
				{ answered: true, artists: [] },
				{ answered: true, artists: [MARSHMELLO] },
			]);

			await user.type(input(ARTISTS), "marsh");
			const status = await screen.findByText(
				"No artist called marsh on MusicBrainz",
			);
			expect(searches()).toHaveLength(1);

			await user.click(
				within(status).getByRole("button", { name: "Search again" }),
			);

			expect(
				await screen.findByRole("option", { name: /^Marshmello/ }),
			).toBeVisible();
			expect(searches()).toHaveLength(2);
			expect(input(ARTISTS)).toHaveValue("marsh");
		});

		it("says MusicBrainz did not answer where it did not, and offers to search again", async () => {
			const user = await renderWithArtists([{ answered: false, artists: [] }]);

			await user.type(input(ARTISTS), "marsh");

			const status = await screen.findByText("MusicBrainz did not answer");
			expect(
				within(status).getByRole("button", { name: "Search again" }),
			).toBeEnabled();
		});
	});

	it("adds a tag by its key", async () => {
		const user = userEvent.setup();
		await renderTags();

		await user.type(
			screen.getByRole("textbox", { name: "Tag key" }),
			"TXXX:MOOD",
		);
		await user.click(screen.getByRole("button", { name: "Add tag" }));

		expect(queryRow("TXXX:MOOD")).not.toBeNull();
		expect(input("TXXX:MOOD")).toHaveValue("");
		expect(screen.getByRole("textbox", { name: "Tag key" })).toHaveValue("");
	});

	it("refuses to add a tag the owner cannot edit", async () => {
		const user = userEvent.setup();
		await renderTags();

		await user.type(
			screen.getByRole("textbox", { name: "Tag key" }),
			"TXXX:MusicBrainz Artist Id{Enter}",
		);

		expect(screen.getByRole("alert")).toHaveTextContent(
			"TXXX:MusicBrainz Artist Id cannot be edited",
		);
		expect(latest?.dirty).toBe(false);
	});

	it("shows the values read-only while a release is being looked up", async () => {
		await renderTags();
		act(() =>
			latest?.setRepoint(
				"https://musicbrainz.org/release/6f1a2b3c-0000-4000-8000-000100000009",
			),
		);

		expect(screen.queryByRole("textbox")).toBeNull();
		expect(within(rowOf("Album")).getAllByText("Clean Album")).toHaveLength(2);
	});
});
