import { describe, expect, it } from "vitest";

import type { AlbumView, FileFacts, PlanEntry } from "@/shared/api/types";
import rawEdits from "@/test/fixtures/raw-edits-owner-cover/plan.json";
import { renderWithProviders, screen, userEvent, within } from "@/test/render";

import { usePending } from "./pending";
import { TagEditor } from "./TagEditor";

const NAMES: AlbumView["names"] = {
	id3: {
		TIT2: "Title",
		TPE1: "Artist",
		TALB: "Album",
		TPE2: "Album artist",
		TDRC: "Date",
		TCON: "Genre",
		TCOM: "Composer",
		TRCK: "Track number",
		TPOS: "Disc number",
		"TXXX:MusicBrainz Album Id": "MusicBrainz release id",
		"TXXX:MusicBrainz Release Group Id": "MusicBrainz release group id",
		"UFID:http://musicbrainz.org": "MusicBrainz recording id",
		"TXXX:MusicBrainz Release Track Id": "MusicBrainz track id",
		"TXXX:MusicBrainz Artist Id": "MusicBrainz artist id",
		"TXXX:MusicBrainz Album Artist Id": "MusicBrainz album artist id",
	},
	vorbis: {},
	mp4: {},
	asf: {},
};

// The fixture was planned under the owner's edits. This is the same album
// before any: 1-1 has no composer and keeps its mood, 1-2 keeps its title.
// Every track gets two genres, so a chip can go and one stay, and 1-1 gets an
// uploader tag, a rating and a cover frame.
function preview(): PlanEntry {
	const entry = structuredClone(rawEdits.albums[0]) as unknown as PlanEntry;
	const [one, two] = entry.files;
	delete one.after.TCOM;
	one.after["TXXX:MOOD"] = ["Calm"];
	two.after.TIT2 = ["Two"];
	for (const file of entry.files) {
		file.after.TCON = ["Rock", "Pop"];
	}
	one.before["TXXX:uploader"] = ["scene-group"];
	one.after["TXXX:uploader"] = ["scene-group"];
	one.before["POPM:no@email"] = ["196 (0 plays)"];
	one.before["APIC:"] = ["APIC:image/jpeg front cover (6406 bytes)"];
	entry.decision = null;
	entry.owner_edits = {};
	return entry;
}

function facts(position: string): FileFacts {
	return {
		position,
		path_now: `Edited Album/${position}.mp3`,
		path_after: `E/Edited Band/(2010) Edited Album/${position}.mp3`,
		format: "MP3",
		family: "id3",
		lossless: false,
		bitrate: 320000,
		sample_rate: 44100,
		bit_depth: null,
		channels: 2,
		length: 200,
		size: 8_000_000,
		audio_url: `/api/drops/x/albums/01/audio/${position}.mp3`,
	};
}

// A drop of its own per view, so a store kept per album cannot carry one
// test's edits into the next.
let drops = 0;

function view(): AlbumView {
	const entry = preview();
	drops += 1;
	return {
		drop: `20260929-2100${String(drops).padStart(2, "0")}`,
		n: "01",
		name: "Edited Album",
		state: "ready",
		stderr: "",
		error: null,
		step: null,
		file: null,
		busy: false,
		preview: entry,
		files: entry.files.map((file) => facts(file.position)),
		names: NAMES,
		library_path: `/srv/music/library/${entry.destination}`,
		tree: [],
		extras_to: [],
		decision: null,
		cover: null,
		duplicate: null,
		approvable: { ok: true, reason: null, code: null, hold: null },
	};
}

// The draft and the dirty flag are what the page will send and whether it
// must, which the owner never sees as such, so the harness prints them under
// test ids.
function Harness({
	view,
	position,
}: {
	view: AlbumView;
	position: string | "all";
}) {
	const pending = usePending(view);
	return (
		<>
			<TagEditor view={view} position={position} pending={pending} />
			<pre data-testid="draft">{JSON.stringify(pending.draft.edits)}</pre>
			<pre data-testid="dirty">{String(pending.dirty)}</pre>
		</>
	);
}

async function renderEditor(position: string | "all") {
	const user = userEvent.setup();
	renderWithProviders(<Harness view={view()} position={position} />);
	// The router renders its route after a tick.
	const form = await screen.findByRole("form", { name: "Edit tags" });
	return { user, form };
}

function draft(): unknown {
	return JSON.parse(screen.getByTestId("draft").textContent ?? "");
}

const POSITIONS = ["1-1", "1-2", "1-3"];

function everyPosition(edit: Record<string, string[] | null>) {
	return Object.fromEntries(POSITIONS.map((position) => [position, edit]));
}

// A button whose name holds both the action and the tag, in either order.
function named(action: string, tag: string): RegExp {
	return new RegExp(`^(?=.*\\b${action}\\b)(?=.*\\b${tag}\\b)`, "i");
}

describe("TagEditor on one track", () => {
	it("shows the written value, and a new title goes into the draft under the position and TIT2", async () => {
		const { user, form } = await renderEditor("1-1");
		const title = within(form).getByRole("textbox", { name: "Title" });
		// The after value, not the dropped `one`.
		expect(title).toHaveValue("One");

		await user.clear(title);
		await user.type(title, "New Title");

		expect(draft()).toEqual({ "1-1": { TIT2: ["New Title"] } });
	});

	it("is not dirty until the first change, and is after it", async () => {
		const { user, form } = await renderEditor("1-1");
		expect(screen.getByTestId("dirty")).toHaveTextContent("false");
		expect(draft()).toEqual({});

		await user.type(within(form).getByRole("textbox", { name: "Title" }), "!");

		expect(screen.getByTestId("dirty")).toHaveTextContent("true");
	});

	it("adds a tag by its raw key and sends its value under that key", async () => {
		const { user, form } = await renderEditor("1-1");
		expect(
			within(form).queryByRole("textbox", { name: "Composer" }),
		).not.toBeInTheDocument();

		await user.type(
			within(form).getByRole("textbox", { name: "Tag key" }),
			"TCOM",
		);
		await user.click(within(form).getByRole("button", { name: "Add tag" }));
		await user.type(
			await within(form).findByRole("textbox", { name: "Composer" }),
			"Someone",
		);

		expect(draft()).toEqual({ "1-1": { TCOM: ["Someone"] } });
	});

	it("removes a tag the engine has no name for as null under its raw key", async () => {
		const { user, form } = await renderEditor("1-1");

		await user.click(
			within(form).getByRole("button", { name: "Remove TXXX:uploader" }),
		);

		expect(draft()).toEqual({ "1-1": { "TXXX:uploader": null } });
	});

	it("gives a tag a second value as a two-item list, and takes it away again", async () => {
		const { user, form } = await renderEditor("1-1");

		await user.click(
			within(form).getByRole("button", { name: named("Add value", "Title") }),
		);
		const values = within(form).getAllByRole("textbox", { name: /Title/ });
		expect(values).toHaveLength(2);
		await user.type(values[1], "Second");

		expect(draft()).toEqual({ "1-1": { TIT2: ["One", "Second"] } });

		const removes = within(form).getAllByRole("button", {
			name: named("Remove value", "Title"),
		});
		await user.click(removes[removes.length - 1]);

		expect(
			within(form).getAllByRole("textbox", { name: /Title/ }),
		).toHaveLength(1);
		expect(draft()).toEqual({ "1-1": { TIT2: ["One"] } });
	});

	it("offers genres as chips, and sends the list as the neutral genre", async () => {
		const { user, form } = await renderEditor("1-2");
		const genres = within(form).getByRole("list", { name: "Genres" });
		expect(
			within(genres)
				.getAllByRole("listitem")
				.map((chip) => chip.textContent),
		).toEqual([
			expect.stringContaining("Rock"),
			expect.stringContaining("Pop"),
		]);

		await user.click(
			within(genres).getByRole("button", { name: "Remove Pop" }),
		);
		// Enter adds the chip, from the keyboard alone.
		await user.type(
			within(form).getByRole("textbox", { name: "Add genre" }),
			"New Genre{Enter}",
		);

		expect(draft()).toEqual({ "1-2": { genre: ["Rock", "New Genre"] } });
		expect(
			within(genres)
				.getAllByRole("listitem")
				.map((chip) => chip.textContent),
		).toEqual([
			expect.stringContaining("Rock"),
			expect.stringContaining("New Genre"),
		]);
	});

	it("shows the MusicBrainz IDs, the rating and the cover frame with their reason and no way to edit or remove them", async () => {
		const { form } = await renderEditor("1-1");

		expect(within(form).getAllByText(/comes from the release/i)).toHaveLength(
			6,
		);
		expect(
			within(form).getAllByText(/ratings come from listening/i),
		).toHaveLength(1);
		expect(within(form).getAllByText(/\bbinary\b/i)).toHaveLength(1);

		// By readable name, and by raw key in case the key is part of a name.
		const locked = /musicbrainz.*\bid\b|UFID|POPM|APIC/i;
		expect(within(form).queryAllByRole("textbox", { name: locked })).toEqual(
			[],
		);
		expect(within(form).queryAllByRole("button", { name: locked })).toEqual([]);
		// The release country is not an ID and stays editable.
		expect(
			within(form).getByRole("textbox", {
				name: /TXXX:MusicBrainz Album Release Country/,
			}),
		).toHaveValue("GB");
	});

	it("gives every control a name, including a value just added", async () => {
		const { user, form } = await renderEditor("1-1");
		await user.click(
			within(form).getByRole("button", { name: named("Add value", "Title") }),
		);

		const unnamed = /^\s*$/;
		for (const role of ["button", "textbox", "combobox", "checkbox"]) {
			expect(within(form).queryAllByRole(role, { name: unnamed })).toEqual([]);
		}
		expect(within(form).getAllByRole("textbox").length).toBeGreaterThan(10);
	});
});

describe("TagEditor on every track at once", () => {
	it("writes a change to an album-wide tag under every position", async () => {
		const { user, form } = await renderEditor("all");
		const album = within(form).getByRole("textbox", { name: "Album" });
		expect(album).toHaveValue("Edited Album");

		await user.clear(album);
		await user.type(album, "New Album");

		expect(draft()).toEqual(everyPosition({ TALB: ["New Album"] }));
	});

	it("adds a tag to every track", async () => {
		const { user, form } = await renderEditor("all");

		await user.type(
			within(form).getByRole("textbox", { name: "Tag key" }),
			"TCOM",
		);
		await user.click(within(form).getByRole("button", { name: "Add tag" }));
		await user.type(
			await within(form).findByRole("textbox", { name: "Composer" }),
			"Someone",
		);

		expect(draft()).toEqual(everyPosition({ TCOM: ["Someone"] }));
	});

	it("removes a tag every track has from every track", async () => {
		const { user, form } = await renderEditor("all");

		await user.click(
			within(form).getByRole("button", { name: "Remove TXXX:MOOD" }),
		);

		expect(draft()).toEqual(everyPosition({ "TXXX:MOOD": null }));
	});

	it("edits the genre chips of every track at once", async () => {
		const { user, form } = await renderEditor("all");
		const genres = within(form).getByRole("list", { name: "Genres" });

		await user.click(
			within(genres).getByRole("button", { name: "Remove Pop" }),
		);
		await user.type(
			within(form).getByRole("textbox", { name: "Add genre" }),
			"New Genre{Enter}",
		);

		expect(draft()).toEqual(everyPosition({ genre: ["Rock", "New Genre"] }));
	});

	it("gives every control a name", async () => {
		const { form } = await renderEditor("all");

		const unnamed = /^\s*$/;
		for (const role of ["button", "textbox", "combobox", "checkbox"]) {
			expect(within(form).queryAllByRole(role, { name: unnamed })).toEqual([]);
		}
		expect(within(form).getAllByRole("textbox").length).toBeGreaterThan(10);
	});
});
