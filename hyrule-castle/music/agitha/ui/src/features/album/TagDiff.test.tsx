import { act } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { diffOf } from "@/domain/album/diff";
import type { AlbumView } from "@/shared/api/types";
import { albumView } from "@/test/albumView";
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
