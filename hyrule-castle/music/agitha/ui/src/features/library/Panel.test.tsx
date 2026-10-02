import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { DraftEdit, TrackRef } from "@/shared/api/types";
import {
	albumTracks,
	artistTracks,
	fixtures,
	refsOf,
	type TrackOfAlbum,
} from "@/test/library";
import { renderWithProviders, screen, userEvent, within } from "@/test/render";

// Loaded inside each case: a module that is missing then fails the case that
// asked for it, on its own line, and not the whole file with one import error.
const MODULE = "./Panel";
const load = (): Promise<typeof import("./Panel")> =>
	import(/* @vite-ignore */ MODULE);

// Ecliptica as the fixture holds it: two FLACs, then two MP3s. Blank File has
// one genre and a rating, My Land two genres, 8th Commandment one genre, a
// picture, a rating and a ripper frame, and Replica no genre at all.
const BLANK = "01. Blank File.flac";
const LAND = "02. My Land.flac";
const EIGHTH = "03. 8th Commandment.mp3";
const REPLICA = "04. Replica.mp3";

const RELEASE_ID = "7d3d4b5f-0000-4000-8000-000000001999";

// The tags the artist page leaves to each album's own page, by the names the panel shows.
const LOCKED = [
	"Title",
	"Artist",
	"Album artist",
	"Artist sort order",
	"Album artist sort order",
	"Album",
	"Date",
	"Original release date",
	"Track number",
	"Disc number",
	"Disc subtitle",
];

const only = (tracks: TrackOfAlbum[], ...paths: string[]) =>
	tracks.filter((track) => paths.includes(track.path));

const edit = (
	tracks: TrackOfAlbum[],
	change: Partial<Pick<DraftEdit, "set" | "add" | "remove">>,
): DraftEdit => ({
	tracks: refsOf(tracks),
	set: {},
	add: {},
	remove: {},
	...change,
});

interface Shown {
	tracks?: TrackOfAlbum[];
	selected?: TrackRef[];
	edits?: DraftEdit[];
	genres?: string[];
	locked?: string[];
}

/**
 * The panel as a page mounts it: the page holds the pending edits, and each
 * edit the panel reports joins them. `reported` is every edit it reported.
 */
async function show({
	tracks = albumTracks(),
	selected = refsOf(tracks),
	edits: pending = [],
	genres = fixtures.genres.genres,
	locked,
}: Shown = {}) {
	const { Panel } = await load();
	const reported: DraftEdit[] = [];

	function Page() {
		const [edits, setEdits] = useState(pending);
		return (
			<Panel
				tracks={tracks}
				selected={selected}
				names={fixtures.album.names}
				edits={edits}
				genres={genres}
				locked={locked}
				onEdit={(next) => {
					reported.push(structuredClone(next));
					setEdits((all) => [...all, next]);
				}}
			/>
		);
	}

	renderWithProviders(<Page />);
	await screen.findByRole("textbox", { name: "Tag key" });
	return { reported, user: userEvent.setup() };
}

// A tag's row: a group named by the tag and nothing else.
const row = (tag: string) => screen.getByRole("group", { name: tag });
const queryRow = (tag: string) => screen.queryByRole("group", { name: tag });

const marked = (tag: string) => within(row(tag)).queryByText("changed");

// A value with a count after it, as `rock 54/72` has.
const counted = (value: string) => new RegExp(`${value}\\s*\\d+/\\d+`);

const controlsIn = (tag: string) => [
	...within(row(tag)).queryAllByRole("textbox"),
	...within(row(tag)).queryAllByRole("combobox"),
	...within(row(tag)).queryAllByRole("button"),
];

// The tracks an edit names, in an order of this file's choosing: the order is not promised.
const named = (refs: TrackRef[]) =>
	[...refs].sort((a, b) =>
		`${a.album}/${a.path}`.localeCompare(`${b.album}/${b.path}`),
	);

async function addByKey(
	user: ReturnType<typeof userEvent.setup>,
	key: string,
	value: string,
) {
	await user.type(screen.getByRole("textbox", { name: "Tag key" }), key);
	await user.type(screen.getByRole("textbox", { name: "Tag value" }), value);
	await user.click(screen.getByRole("button", { name: "Add tag" }));
}

// What a field says of itself to someone looking at it: its placeholder, or
// the text of a label of its own. An `aria-label` is heard and not seen, and
// neither is a label the page hides with its `visually-hidden` class.
function wordsOn(field: HTMLElement) {
	const placeholder = field.getAttribute("placeholder");
	if (placeholder) return placeholder.trim();
	const labels = [...((field as HTMLInputElement).labels ?? [])].filter(
		(label) => label.closest(".visually-hidden") === null,
	);
	return labels
		.map((label) => label.textContent ?? "")
		.join(" ")
		.trim();
}

// Every genre a genre field offers, each once: a datalist's options are not
// in the accessibility tree and a listbox's are, so both are read.
function offered() {
	const options = screen.getAllByRole("option", { hidden: true });
	return [
		...new Set(
			options.map(
				(option) =>
					(option as HTMLOptionElement).value || option.textContent || "",
			),
		),
	].sort();
}

describe("Panel", () => {
	it("lists every tag a selected track carries, by its readable name where it has one and its own key where not", async () => {
		await show();

		for (const tag of [
			"Album",
			"Album artist",
			"Artist",
			"Date",
			"Disc number",
			"Genre",
			"Title",
			"Track number",
			"MusicBrainz release id",
			"MusicBrainz recording id",
			"rating",
			"APIC:",
			"POPM:Windows Media Player 9 Series",
			"TXXX:RIPPER",
		])
			expect(row(tag)).toBeInTheDocument();
		// A key with a readable name is not listed under its own key as well.
		for (const key of ["genre", "TCON", "title", "TIT2"])
			expect(queryRow(key)).toBeNull();
	});

	it("shows a value every selected track carries plainly, and one only some carry with its count", async () => {
		await show();

		expect(row("Album")).toHaveTextContent("Ecliptica");
		expect(row("Album")).not.toHaveTextContent(counted("Ecliptica"));
		expect(row("Genre")).toHaveTextContent("power metal 3/4");
		expect(row("Genre")).toHaveTextContent("symphonic metal 1/4");
		expect(row("TXXX:RIPPER")).toHaveTextContent("EAC 0.99 1/4");
	});

	it("counts over the selected tracks alone", async () => {
		const tracks = albumTracks();
		await show({ tracks, selected: refsOf(only(tracks, BLANK, LAND)) });

		expect(row("Genre")).toHaveTextContent("power metal");
		expect(row("Genre")).not.toHaveTextContent(counted("power metal"));
		expect(row("Genre")).toHaveTextContent("symphonic metal 1/2");
		// Only the MP3s carry these, and neither is selected.
		expect(queryRow("TXXX:RIPPER")).toBeNull();
		expect(queryRow("APIC:")).toBeNull();
	});

	it("tells two tracks of one path apart by their album", async () => {
		const OTHER = "S/Sonata Arctica/(2000) Other";
		const [here] = only(albumTracks(), BLANK);
		const there = { ...only(albumTracks(), BLANK)[0]!, album: OTHER };
		there.tags.album = ["Other"];
		const { reported, user } = await show({
			tracks: [here!, there],
			selected: refsOf([there]),
		});

		expect(row("Album")).toHaveTextContent("Other");
		expect(row("Album")).not.toHaveTextContent("Ecliptica");

		await user.click(screen.getByRole("button", { name: "Remove Date" }));

		expect(reported).toEqual([edit([there], { set: { Date: null } })]);
	});

	it("shows a pending edit as already applied and marks the tag it names", async () => {
		const tracks = albumTracks();
		await show({
			tracks,
			edits: [edit(tracks, { set: { Album: ["Winterheart's Guild"] } })],
		});

		expect(row("Album")).toHaveTextContent("Winterheart's Guild");
		expect(row("Album")).not.toHaveTextContent(counted("Winterheart's Guild"));
		expect(row("Album")).not.toHaveTextContent("Ecliptica");
		expect(marked("Album")).toBeInTheDocument();
		expect(marked("Genre")).toBeNull();
		expect(marked("Artist")).toBeNull();
	});

	it("marks a tag an edit names by a format's own key", async () => {
		const tracks = albumTracks();
		await show({
			tracks,
			edits: [edit(only(tracks, EIGHTH), { add: { TCON: ["rock"] } })],
		});

		expect(row("Genre")).toHaveTextContent("rock 1/4");
		expect(marked("Genre")).toBeInTheDocument();
	});

	it("leaves a tag unmarked when the edit names no selected track", async () => {
		const tracks = albumTracks();
		await show({
			tracks,
			selected: refsOf(only(tracks, BLANK, LAND)),
			edits: [edit(only(tracks, EIGHTH), { add: { Genre: ["rock"] } })],
		});

		expect(row("Genre")).not.toHaveTextContent("rock");
		expect(marked("Genre")).toBeNull();
	});

	it("keeps a tag the pending edits take from every selected track, marked changed", async () => {
		const tracks = albumTracks();
		await show({ tracks, edits: [edit(tracks, { set: { Genre: null } })] });

		expect(marked("Genre")).toBeInTheDocument();
		expect(marked("Album")).toBeNull();
	});

	it("sets a tag on every selected track, and the row shows the new value, marked", async () => {
		const tracks = albumTracks();
		const { reported, user } = await show({ tracks });

		await user.type(
			screen.getByRole("textbox", { name: "Set Album" }),
			"Winterheart's Guild{Enter}",
		);

		expect(reported).toEqual([
			edit(tracks, { set: { Album: ["Winterheart's Guild"] } }),
		]);
		expect(await within(row("Album")).findByText("changed")).toBeVisible();
		expect(row("Album")).toHaveTextContent("Winterheart's Guild");
		expect(row("Album")).not.toHaveTextContent("Ecliptica");
	});

	it("adds a value to a tag, after the values the tracks have", async () => {
		const tracks = albumTracks();
		const { reported, user } = await show({ tracks });

		await user.type(
			screen.getByRole("textbox", { name: "Add value, Artist" }),
			"Tony Kakko{Enter}",
		);

		expect(reported).toEqual([
			edit(tracks, { add: { Artist: ["Tony Kakko"] } }),
		]);
		expect(await within(row("Artist")).findByText("changed")).toBeVisible();
		expect(row("Artist")).toHaveTextContent("Sonata Arctica");
		expect(row("Artist")).toHaveTextContent("Tony Kakko");
		expect(row("Artist")).not.toHaveTextContent(counted("Tony Kakko"));
	});

	it("removes one value from a tag and keeps its other values", async () => {
		const tracks = albumTracks();
		const { reported, user } = await show({ tracks });

		await user.click(
			screen.getByRole("button", { name: "Remove symphonic metal from Genre" }),
		);

		expect(reported).toEqual([
			edit(tracks, { remove: { Genre: ["symphonic metal"] } }),
		]);
		expect(await within(row("Genre")).findByText("changed")).toBeVisible();
		expect(row("Genre")).not.toHaveTextContent("symphonic metal");
		expect(row("Genre")).toHaveTextContent("power metal 3/4");
	});

	// The server refuses a format's own key over tracks of more than one format,
	// so such a row's edit names the tracks that carry the key. Replica is an
	// MP3 too and has no ripper frame. A tag with a readable name is one tag in
	// every format: Genre goes from all four, Replica with no genre among them.
	it("removes a tag with no readable name by its own key from the tracks that carry it, and one with a readable name from every selected track", async () => {
		const tracks = albumTracks();
		const { reported, user } = await show({ tracks });

		await user.click(
			screen.getByRole("button", { name: "Remove TXXX:RIPPER" }),
		);
		await user.click(screen.getByRole("button", { name: "Remove Genre" }));

		expect(reported).toEqual([
			edit(only(tracks, EIGHTH), { set: { "TXXX:RIPPER": null } }),
			edit(tracks, { set: { Genre: null } }),
		]);
		expect(await within(row("Genre")).findByText("changed")).toBeVisible();
		expect(row("Genre")).not.toHaveTextContent("power metal");
	});

	it("removes a tag only the MP3s carry from both of them, and names no FLAC of the selection", async () => {
		const tracks = albumTracks();
		only(tracks, REPLICA)[0]!.tags["TXXX:RIPPER"] = ["EAC 0.99"];
		const { reported, user } = await show({ tracks });
		expect(row("TXXX:RIPPER")).toHaveTextContent("EAC 0.99 2/4");

		await user.click(
			screen.getByRole("button", { name: "Remove TXXX:RIPPER" }),
		);

		expect(reported).toHaveLength(1);
		expect(reported[0]!.set).toEqual({ "TXXX:RIPPER": null });
		expect(named(reported[0]!.tracks)).toEqual(
			named(refsOf(only(tracks, EIGHTH, REPLICA))),
		);
		// Gone from the tracks that had it, so the row shows the change.
		expect(
			await within(row("TXXX:RIPPER")).findByText("changed"),
		).toBeVisible();
		expect(row("TXXX:RIPPER")).not.toHaveTextContent("EAC 0.99");
	});

	it("names in an edit the selected tracks and no other", async () => {
		const tracks = albumTracks();
		const chosen = only(tracks, BLANK, EIGHTH);
		const { reported, user } = await show({ tracks, selected: refsOf(chosen) });

		await user.click(screen.getByRole("button", { name: "Remove Genre" }));

		expect(reported).toHaveLength(1);
		expect(named(reported[0]!.tracks)).toEqual(named(refsOf(chosen)));
	});

	it("adds a tag no selected track carries by its key, and lists it marked", async () => {
		const tracks = albumTracks();
		const { reported, user } = await show({ tracks });
		expect(queryRow("Composer")).toBeNull();

		await addByKey(user, "Composer", "Tony Kakko");

		// The tag is new to every track, so a set and an add are the same change. Which is sent is not decided.
		expect(reported).toHaveLength(1);
		const [sent] = reported;
		expect({ ...sent!.set, ...sent!.add }).toEqual({
			Composer: ["Tony Kakko"],
		});
		expect(sent!.remove).toEqual({});
		expect(named(sent!.tracks)).toEqual(named(refsOf(tracks)));
		expect(
			await screen.findByRole("group", { name: "Composer" }),
		).toHaveTextContent("Tony Kakko");
		expect(row("Composer")).not.toHaveTextContent(counted("Tony Kakko"));
		expect(marked("Composer")).toBeInTheDocument();
	});

	it("adds a tag with no readable name under the key as typed", async () => {
		const tracks = albumTracks();
		const mp3s = only(tracks, EIGHTH, REPLICA);
		const { reported, user } = await show({ tracks, selected: refsOf(mp3s) });

		await addByKey(user, "TXXX:MOOD", "calm");

		expect(reported).toHaveLength(1);
		expect({ ...reported[0]!.set, ...reported[0]!.add }).toEqual({
			"TXXX:MOOD": ["calm"],
		});
		expect(
			await screen.findByRole("group", { name: "TXXX:MOOD" }),
		).toHaveTextContent("calm");
	});

	it.each([
		["MusicBrainz release id", RELEASE_ID],
		["rating", "5"],
		["APIC:", "APIC (48213 bytes)"],
		["POPM:Windows Media Player 9 Series", "rating=196,count=0"],
	])("shows %s read-only: its value and no control", async (tag, value) => {
		await show();

		expect(row(tag)).toHaveTextContent(value);
		expect(controlsIn(tag)).toEqual([]);
		// A tag the tracks do not refuse has its controls, so the empty list above is not a selector that matches nothing.
		expect(controlsIn("Album")).not.toEqual([]);
	});

	it.each([
		["the first selected track", [BLANK, LAND]],
		["a later selected track", [LAND, BLANK]],
	])("shows a tag read-only when only %s refuses it", async (_which, order) => {
		// Both carry a rating, and only Blank File's list refuses it.
		const tracks = albumTracks();
		only(tracks, LAND)[0]!.tags.rating = ["3"];
		const selected = order.map((path) => refsOf(only(tracks, path))[0]!);
		await show({ tracks, selected });

		expect(row("rating")).toHaveTextContent("5 1/2");
		expect(controlsIn("rating")).toEqual([]);
	});

	it.each(["MusicBrainz release id", "rating"])(
		"refuses to add the read-only %s by its key, naming it",
		async (key) => {
			const { reported, user } = await show();

			await addByKey(user, key, "1");

			expect(await screen.findByRole("alert")).toHaveTextContent(key);
			expect(reported).toEqual([]);
		},
	);

	// The row is MusicBrainz release id, and a format's own key for it is the
	// same tag. Which of the two names the refusal uses is not decided.
	it.each([
		"musicbrainz_albumid",
		"MUSICBRAINZ_ALBUMID",
		"TXXX:MusicBrainz Album Id",
	])(
		"refuses to add a read-only tag typed as a format's own key %s",
		async (key) => {
			const { reported, user } = await show();

			await addByKey(user, key, "1");

			expect(await screen.findByRole("alert")).toBeVisible();
			expect(reported).toEqual([]);
		},
	);

	// The page knows a MusicBrainz id and a rating by their names in any case.
	// Any other tag is read-only because the track's own list says so, in the
	// lower case a FLAC is read by.
	it("refuses a tag the FLACs list as read-only when its key is typed in capitals", async () => {
		const tracks = only(albumTracks(), BLANK, LAND);
		for (const track of tracks) {
			track.tags.encodedby = ["whipper"];
			track.readonly.push("encodedby");
		}
		const { reported, user } = await show({ tracks });
		expect(controlsIn("encodedby")).toEqual([]);

		await addByKey(user, "ENCODEDBY", "EAC");

		expect(await screen.findByRole("alert")).toHaveTextContent(/encodedby/i);
		expect(reported).toEqual([]);
		expect(row("encodedby")).not.toHaveTextContent("EAC");
	});

	describe("a Vorbis key typed in another case", () => {
		it("adds to the genre the FLACs carry when the key is typed GENRE, on the tag's own row", async () => {
			const tracks = albumTracks();
			const flacs = only(tracks, BLANK, LAND);
			const { reported, user } = await show({
				tracks,
				selected: refsOf(flacs),
			});

			await addByKey(user, "GENRE", "heavy metal");

			// The tracks carry the tag, so this is an add: a set would take `power metal` from them.
			expect(reported).toEqual([
				edit(flacs, { add: { GENRE: ["heavy metal"] } }),
			]);
			expect(await within(row("Genre")).findByText("changed")).toBeVisible();
			expect(row("Genre")).toHaveTextContent("power metal");
			expect(row("Genre")).toHaveTextContent("heavy metal");
			expect(queryRow("GENRE")).toBeNull();
		});

		it("adds to a tag with no readable name the FLACs carry: MOOD is their mood", async () => {
			const tracks = albumTracks();
			const flacs = only(tracks, BLANK, LAND);
			for (const track of flacs) track.tags.mood = ["dark"];
			const { reported, user } = await show({
				tracks,
				selected: refsOf(flacs),
			});

			await addByKey(user, "MOOD", "calm");

			expect(reported).toEqual([edit(flacs, { add: { MOOD: ["calm"] } })]);
			expect(await within(row("mood")).findByText("changed")).toBeVisible();
			expect(row("mood")).toHaveTextContent("dark");
			expect(row("mood")).toHaveTextContent("calm");
			expect(queryRow("MOOD")).toBeNull();
		});
	});

	describe("a key with no readable name over tracks of more than one format", () => {
		// The server takes MOOD as `mood` in a FLAC and as a frame of that name
		// in an MP3, which is no frame: it refuses the edit, so the panel does first.
		it("is refused, saying to select tracks of one format, and reports nothing", async () => {
			const { reported, user } = await show();

			await addByKey(user, "MOOD", "calm");

			expect(await screen.findByRole("alert")).toHaveTextContent(/one format/i);
			expect(reported).toEqual([]);
			expect(queryRow("MOOD")).toBeNull();
			expect(queryRow("mood")).toBeNull();
		});

		// Over the MP3s alone it is the case above that adds `TXXX:MOOD`.
		it("is added over the FLACs alone, under the key as typed", async () => {
			const tracks = albumTracks();
			const flacs = only(tracks, BLANK, LAND);
			const { reported, user } = await show({
				tracks,
				selected: refsOf(flacs),
			});

			await addByKey(user, "MOOD", "calm");

			// The tag is new to every track, so a set and an add are the same change.
			expect(reported).toHaveLength(1);
			expect({ ...reported[0]!.set, ...reported[0]!.add }).toEqual({
				MOOD: ["calm"],
			});
			expect(named(reported[0]!.tracks)).toEqual(named(refsOf(flacs)));
			expect(screen.queryByRole("alert")).toBeNull();
		});
	});

	// Both fields of a row are empty boxes. Typing in the first replaces the tag
	// on every selected track, so a sighted owner has to be able to tell which is which.
	it("says on each of a tag's two fields what it does, in words on the page: Set and Add value", async () => {
		await show();

		const set = screen.getByRole("textbox", { name: "Set Album" });
		const add = screen.getByRole("textbox", { name: "Add value, Album" });

		expect(wordsOn(set)).toMatch(/^Set\b/);
		expect(wordsOn(add)).toMatch(/^Add value\b/);
		// A genre's fields are comboboxes, and say the same.
		expect(
			wordsOn(screen.getByRole("combobox", { name: "Set Genre" })),
		).toMatch(/^Set\b/);
		expect(
			wordsOn(screen.getByRole("combobox", { name: "Add value, Genre" })),
		).toMatch(/^Add value\b/);
	});

	it("shows the tags a page locks read-only, saying where to edit them, and leaves the rest editable", async () => {
		await show({ tracks: artistTracks(), locked: LOCKED });

		for (const tag of ["Title", "Album", "Date", "Track number"]) {
			expect(controlsIn(tag)).toEqual([]);
			expect(row(tag)).toHaveTextContent("Edit on the album's page");
		}
		expect(row("Title")).toHaveTextContent("Blank File 1/8");
		expect(
			within(row("Genre")).getByRole("button", { name: "Remove Genre" }),
		).toBeEnabled();
		// A tag the files refuse is read-only on any page: the sentence is for the locked ones.
		expect(row("MusicBrainz release id")).not.toHaveTextContent(
			"Edit on the album's page",
		);
	});

	it("says nothing about the album's page where no tag is locked", async () => {
		await show();

		expect(screen.queryByText("Edit on the album's page")).toBeNull();
		expect(screen.getByRole("textbox", { name: "Set Title" })).toBeEnabled();
	});

	it.each(["Title", "title", "TIT2"])(
		"adds nothing when a locked tag is typed as the key %s",
		async (key) => {
			const { reported, user } = await show({
				tracks: artistTracks(),
				locked: LOCKED,
			});

			await addByKey(user, key, "Intro");

			expect(reported).toEqual([]);
		},
	);

	it.each([
		["the whole list", fixtures.genres.genres],
		["a list of two", ["jazz", "rock"]],
	])(
		"offers for a genre the names it was given and no other: %s",
		async (_which, genres) => {
			const { user } = await show({ genres });

			await user.click(
				screen.getByRole("combobox", { name: "Add value, Genre" }),
			);

			expect(offered()).toEqual([...genres].sort());
		},
	);

	it("adds and sets a genre that is on the list", async () => {
		const tracks = albumTracks();
		const { reported, user } = await show({ tracks });

		await user.type(
			screen.getByRole("combobox", { name: "Add value, Genre" }),
			"heavy metal{Enter}",
		);
		await user.type(
			screen.getByRole("combobox", { name: "Set Genre" }),
			"rock{Enter}",
		);

		expect(reported).toEqual([
			edit(tracks, { add: { Genre: ["heavy metal"] } }),
			edit(tracks, { set: { Genre: ["rock"] } }),
		]);
		expect(screen.queryByRole("alert")).toBeNull();
	});

	it.each([
		// `power` starts a name on the list and is not one.
		["Add value, Genre", "power"],
		["Set Genre", "shoegaze"],
	])(
		"refuses through %s a genre that is not on the list, naming it",
		async (field, genre) => {
			const { reported, user } = await show();

			await user.type(
				screen.getByRole("combobox", { name: field }),
				`${genre}{Enter}`,
			);

			expect(await screen.findByRole("alert")).toHaveTextContent(genre);
			expect(reported).toEqual([]);
			expect(marked("Genre")).toBeNull();
		},
	);

	it.each(["Genre", "genre", "GENRE", "TCON"])(
		"refuses a genre that is not on the list when the key %s is typed",
		async (key) => {
			const { reported, user } = await show();

			await addByKey(user, key, "shoegaze");

			expect(await screen.findByRole("alert")).toHaveTextContent("shoegaze");
			expect(reported).toEqual([]);
		},
	);
});
