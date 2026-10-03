import { act } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { DraftEdit, LibraryAlbum, LibraryTrack } from "@/shared/api/types";
import {
	albumTracks,
	ECLIPTICA,
	fixtures,
	posted,
	previewOf,
	refsOf,
	SONATA,
	type TrackOfAlbum,
} from "@/test/library";
import {
	albumOf,
	BLANK,
	box,
	closeAlbum,
	EIGHTH,
	inPathOrder,
	LAND,
	marked,
	newValue,
	openAlbum,
	openReview,
	queryBox,
	queryTag,
	REPLICA,
	reviewButton,
	setPowerMetal,
	shown,
	TITLES,
	tag,
} from "@/test/libraryAlbum";
import { screen, waitFor, within } from "@/test/render";

// A case opens it with `openAlbum`, which takes the folders and the answers of
// the editing routes the case needs, and waits for it with `shown`.
afterEach(closeAlbum);

const SILENCE = `${SONATA}/(2002) Songs of Silence`;
const PREVIEW = "/api/library/preview";
const UNREADABLE = "05. Kingdom for a Heart.mp3";

// The artist fixture's second album as its own route would serve it.
function songsOfSilence(): LibraryAlbum {
	const summary = fixtures.artist.albums.find(
		(album) => album.path === SILENCE,
	)!;
	return albumOf({
		path: SILENCE,
		cover: null,
		tracks: structuredClone(summary.tracks),
		unreadable: [],
	});
}

const only = (tracks: TrackOfAlbum[], ...paths: string[]) =>
	tracks.filter((track) => paths.includes(track.path));

const edit = (
	tracks: TrackOfAlbum[],
	change: Partial<Pick<DraftEdit, "set" | "add" | "remove">>,
): DraftEdit => ({
	tracks: refsOf(tracks).sort((a, b) => a.path.localeCompare(b.path)),
	set: {},
	add: {},
	remove: {},
	...change,
});

// A track as a draft sends it: what the album route served, and what it showed for the tags edited.
const sent = (track: LibraryTrack, seen: Record<string, string[] | null>) => ({
	album: ECLIPTICA,
	path: track.path,
	loaded: track.loaded,
	seen,
});

// The row or list item a track's checkbox sits in.
function rowOf(title: string) {
	const row = box(title).closest<HTMLElement>(
		"tr, li, [role=row], [role=listitem]",
	);
	if (!row) throw new Error(`${title} is not in a row or a list item`);
	return row;
}

// The button of the confirm that is not Cancel: its label is the builder's to word.
function confirmIn(dialog: HTMLElement) {
	const [confirm, ...rest] = within(dialog)
		.getAllByRole("button")
		.filter((button) => button.textContent !== "Cancel");
	if (!confirm || rest.length > 0)
		throw new Error("the confirm has not one button beside Cancel");
	return confirm;
}

describe("LibraryAlbum", () => {
	describe("what the files hold", () => {
		it("has the album title as its heading, and shows the cover with its pixel size", async () => {
			const cover = { ...fixtures.album.cover!, width: 600, height: 500 };
			openAlbum({ shelves: { albums: { [ECLIPTICA]: albumOf({ cover }) } } });

			expect(
				await screen.findByRole("heading", { name: /Ecliptica/ }),
			).toBeVisible();
			expect(
				await screen.findByRole("img", { name: /Ecliptica cover$/ }),
			).toHaveAttribute("src", cover.url);
			// Width first, as the review page writes a size.
			expect(screen.getByText("600 × 500")).toBeVisible();
		});

		it("lists the tracks in the order served, each with its number, title, artist, length and file name", async () => {
			// Numbers no file name carries, an artist per track, and a length that
			// rounds up and is cut down. The titles are not in alphabetical order.
			const album = albumOf();
			const [blank, land, eighth, replica] = album.tracks;
			Object.assign(blank!, { number: 21, length: 245.7 });
			Object.assign(land!, { number: 22 });
			Object.assign(eighth!, { number: 23 });
			Object.assign(replica!, { number: 24 });
			land!.tags.artist = ["Tony Kakko"];
			eighth!.tags.TPE1 = ["Timo Kotipelto"];
			openAlbum({ shelves: { albums: { [ECLIPTICA]: album } } });
			await shown();

			expect(TITLES.map((title) => rowOf(title))).toHaveLength(4);
			const order = screen
				.getAllByRole("checkbox")
				.filter((each) => TITLES.some((title) => each === queryBox(title)))
				.map((each) => TITLES.find((title) => each === queryBox(title)));
			expect(order).toEqual(TITLES);

			const facts = (title: string, number: number) => {
				const row = within(rowOf(title));
				return {
					// A disc before the number is not decided; the number itself is.
					number: row.queryAllByText(new RegExp(`^(\\d+[-.])?0?${number}\\.?$`))
						.length,
					artist: (name: string) => row.queryAllByText(name).length,
					length: (text: string) => row.queryAllByText(text).length,
					file: (name: string) => row.queryAllByText(name).length,
				};
			};
			const first = facts("Blank File", 21);
			expect(first.number).toBe(1);
			expect(first.artist("Sonata Arctica")).toBe(1);
			expect(first.length("4:05")).toBe(1);
			expect(first.file(BLANK)).toBe(1);

			const second = facts("My Land", 22);
			expect(second.number).toBe(1);
			expect(second.artist("Tony Kakko")).toBe(1);
			expect(second.length("4:36")).toBe(1);
			expect(second.file(LAND)).toBe(1);

			// An MP3 holds its title and artist under TIT2 and TPE1.
			const third = facts("8th Commandment", 23);
			expect(third.number).toBe(1);
			expect(third.artist("Timo Kotipelto")).toBe(1);
			expect(third.length("4:55")).toBe(1);
			expect(third.file(EIGHTH)).toBe(1);

			const fourth = facts("Replica", 24);
			expect(fourth.number).toBe(1);
			expect(fourth.length("3:41")).toBe(1);
			expect(fourth.file(REPLICA)).toBe(1);
		});

		it("plays a track's own audio from its play control", async () => {
			const { played, user } = openAlbum();
			await shown();

			await user.click(
				within(rowOf("8th Commandment")).getByRole("button", {
					name: "Play 8th Commandment",
				}),
			);

			const stop = await screen.findByRole("button", {
				name: "Stop 8th Commandment",
			});
			expect(played).toEqual([
				fixtures.album.tracks.find((track) => track.path === EIGHTH)!.audio_url,
			]);
			// The player is one for the page and outlives the case.
			await user.click(stop);
			expect(
				await screen.findByRole("button", { name: "Play 8th Commandment" }),
			).toBeEnabled();
		});

		it("lists a file whose tags cannot be read by its path, as unreadable, beside the tracks that can", async () => {
			openAlbum();
			await shown();

			const line = screen
				.getByText(UNREADABLE, { exact: false })
				.closest<HTMLElement>("li, tr, p");
			expect(line).toHaveTextContent(/unreadable|not be read/i);
			// It has no tags to edit, so it is not one of the tracks to select.
			expect(
				screen.queryByRole("checkbox", { name: /Kingdom for a Heart/ }),
			).toBeNull();
			for (const title of TITLES) expect(box(title)).toBeInTheDocument();
		});

		it("says nothing of unreadable files where every file was read", async () => {
			openAlbum({
				shelves: { albums: { [ECLIPTICA]: albumOf({ unreadable: [] }) } },
			});
			await shown();

			expect(screen.queryByText(/unreadable|not be read/i)).toBeNull();
		});
	});

	describe("selection", () => {
		it("opens with every track selected and the table over all of them", async () => {
			const { user } = openAlbum();
			await shown();

			for (const title of TITLES) expect(box(title)).toBeChecked();
			expect(
				screen.getByRole("checkbox", { name: "Select all tracks" }),
			).toBeChecked();
			expect(tag("Genre")).toHaveTextContent("power metal 3/4");
			expect(queryTag("TXXX:RIPPER")).toBeNull();
			await user.click(
				screen.getByRole("button", { name: /^8th Commandment/ }),
			);
			expect(tag("TXXX:RIPPER")).toHaveTextContent("EAC 0.99");
		});

		it("shows the table over the tracks left selected", async () => {
			const { user } = openAlbum();
			await shown();

			await user.click(box("8th Commandment"));
			await user.click(box("Replica"));

			expect(box("Blank File")).toBeChecked();
			expect(box("8th Commandment")).not.toBeChecked();
			expect(tag("Genre")).toHaveTextContent("symphonic metal 1/2");
			// Only the MP3s carry a ripper frame, and neither is selected now.
			expect(queryTag("TXXX:RIPPER")).toBeNull();
			expect(
				screen.getByRole("checkbox", { name: "Select all tracks" }),
			).not.toBeChecked();
		});

		it("selects none of the tracks, then all of them, with one control", async () => {
			const { user } = openAlbum();
			await shown();
			const all = () =>
				screen.getByRole("checkbox", { name: "Select all tracks" });

			await user.click(all());
			for (const title of TITLES) expect(box(title)).not.toBeChecked();
			expect(all()).not.toBeChecked();

			await user.click(all());
			for (const title of TITLES) expect(box(title)).toBeChecked();
			expect(tag("Genre")).toHaveTextContent("power metal 3/4");
		});
	});

	describe("the draft", () => {
		it("offers no review until an edit is made, then marks the tag the edit changes", async () => {
			const { calls, user } = openAlbum();
			await shown();
			expect(reviewButton()).toBeDisabled();
			expect(marked("Genre")).toBeNull();

			await setPowerMetal(user);

			expect(
				await within(tag("Genre")).findByText("edited by you"),
			).toBeInTheDocument();
			expect(marked("Date")).toBeNull();
			expect(reviewButton()).toBeEnabled();
			// The edit is on the page alone until the review is asked for.
			expect(calls.filter((call) => call.method !== "GET")).toEqual([]);
		});

		it("posts to preview each edited track once, as it was loaded, with the values it showed for the tag edited", async () => {
			const tracks = albumTracks();
			const [blank, land, eighth, replica] = tracks;
			const { calls, user } = openAlbum({ writes: { preview: previewOf() } });
			await shown();

			await setPowerMetal(user);
			await openReview(user);

			expect(posted(calls, PREVIEW).map(inPathOrder)).toEqual([
				{
					tracks: [
						sent(blank!, { Genre: ["power metal"] }),
						sent(land!, { Genre: ["power metal", "symphonic metal"] }),
						// Under TCON in the file, and under the name the edit used here.
						sent(eighth!, { Genre: ["power metal"] }),
						sent(replica!, { Genre: null }),
					],
					edits: [edit(tracks, { set: { Genre: ["power metal"] } })],
					swaps: [],
					cover: null,
					batch: false,
				},
			]);
		});

		it("keeps edits made over different selections apart, and sends only the tracks an edit names", async () => {
			const tracks = albumTracks();
			const [blank, land, eighth] = tracks;
			const { calls, user } = openAlbum({ writes: { preview: previewOf() } });
			await shown();

			// Replica is never selected for an edit.
			await user.click(box("Replica"));
			await setPowerMetal(user);
			await user.click(box("8th Commandment"));
			await user.clear(newValue("Genre"));
			await user.type(newValue("Genre"), "power metal; heavy metal{Enter}");
			await user.click(box("Blank File"));
			await user.click(box("My Land"));
			await user.click(box("8th Commandment"));
			await user.click(
				screen.getByRole("button", { name: "Remove TXXX:RIPPER" }),
			);
			await openReview(user);

			expect(posted(calls, PREVIEW).map(inPathOrder)).toEqual([
				{
					tracks: [
						sent(blank!, { Genre: ["power metal"] }),
						// What the file holds, though the first edit set the tag before the second named it again.
						sent(land!, { Genre: ["power metal", "symphonic metal"] }),
						// Two tags were edited on this track and one on the others.
						sent(eighth!, {
							Genre: ["power metal"],
							"TXXX:RIPPER": ["EAC 0.99"],
						}),
					],
					edits: [
						// The first edit named three tracks; the second took two of them over.
						edit(only(tracks, EIGHTH), { set: { Genre: ["power metal"] } }),
						edit(only(tracks, BLANK, LAND), {
							set: { Genre: ["power metal", "heavy metal"] },
						}),
						edit(only(tracks, EIGHTH), { set: { "TXXX:RIPPER": null } }),
					],
					swaps: [],
					cover: null,
					batch: false,
				},
			]);
		});

		// A Vorbis field name has no case: `GENRE` typed in is the `genre` a FLAC
		// holds, so it gets no second row and its edit goes out under the row's name.
		it("lands a Vorbis key typed in capitals on the row of the tag the files hold", async () => {
			const tracks = albumTracks();
			const [blank, land] = tracks;
			const { calls, user } = openAlbum({ writes: { preview: previewOf() } });
			await shown();
			await user.click(box("8th Commandment"));
			await user.click(box("Replica"));

			await user.type(
				screen.getByRole("textbox", { name: "Tag key" }),
				"GENRE{Enter}",
			);
			expect(queryTag("GENRE")).toBeNull();
			await user.clear(newValue("Genre"));
			await user.type(newValue("Genre"), "heavy metal{Enter}");
			await openReview(user);

			expect(
				posted(calls, PREVIEW)
					.map(inPathOrder)
					.map((draft) => ({ tracks: draft.tracks, edits: draft.edits })),
			).toEqual([
				{
					tracks: [
						sent(blank!, { Genre: ["power metal"] }),
						sent(land!, { Genre: ["power metal", "symphonic metal"] }),
					],
					edits: [
						edit(only(tracks, BLANK, LAND), {
							set: { Genre: ["heavy metal"] },
						}),
					],
				},
			]);
		});

		// The tree asks for the artist too. Its answer failing a second time is
		// no reason to take the album, and the edits made on it, off the page.
		it("keeps the album and its draft on the page when the artist cannot be read again", async () => {
			// A switch and not a count: how often the page asks while it opens is not promised.
			const artist = { fails: false, askedSince: 0 };
			const { client, place, user } = openAlbum({
				shelves: {
					artists: {
						[SONATA]: () => {
							if (!artist.fails) return Response.json(fixtures.artist);
							artist.askedSince += 1;
							return new Response(null, { status: 500 });
						},
					},
				},
			});
			await shown();
			await setPowerMetal(user);
			await within(tag("Genre")).findByText("edited by you");

			// Everything is asked for again, as after a save. The client tells the
			// page of the answers a timer tick after the last one is in.
			artist.fails = true;
			await act(async () => {
				await client.invalidateQueries();
				await new Promise((told) => setTimeout(told));
			});

			expect(artist.askedSince).toBeGreaterThan(0);
			expect(place()).toBe(`/library/${ECLIPTICA}`);
			expect(screen.getByRole("heading", { name: /Ecliptica/ })).toBeVisible();
			expect(marked("Genre")).toBeVisible();
			expect(newValue("Genre")).toHaveValue("power metal");
			expect(reviewButton()).toBeEnabled();
		});

		// The list of letters is asked for again with everything else, on a
		// reconnect too. The server being out of reach at that moment takes
		// nothing the page already holds off it.
		it("keeps the album and its draft on the page when the list of letters cannot be read again", async () => {
			// A switch and not a count, as for the artist above.
			const root = { fails: false, askedSince: 0 };
			const { client, place, user } = openAlbum({
				shelves: {
					root: () => {
						if (!root.fails) return Response.json(fixtures.root);
						root.askedSince += 1;
						return new Response(null, { status: 500 });
					},
				},
			});
			await shown();
			await setPowerMetal(user);
			await within(tag("Genre")).findByText("edited by you");

			root.fails = true;
			await act(async () => {
				await client.invalidateQueries();
				await new Promise((told) => setTimeout(told));
			});

			expect(root.askedSince).toBeGreaterThan(0);
			expect(place()).toBe(`/library/${ECLIPTICA}`);
			expect(screen.getByRole("heading", { name: /Ecliptica/ })).toBeVisible();
			expect(marked("Genre")).toBeVisible();
			expect(newValue("Genre")).toHaveValue("power metal");
			expect(reviewButton()).toBeEnabled();
			// The folders stay beside it, and nothing says the library failed.
			expect(
				screen.getByRole("treeitem", { name: "Sabaton, folder" }),
			).toBeVisible();
			expect(screen.queryByRole("alert")).toBeNull();
		});

		it("returns to what the files hold on Discard changes, and the next draft starts empty", async () => {
			const tracks = albumTracks();
			const { calls, user } = openAlbum({ writes: { preview: previewOf() } });
			await shown();
			await setPowerMetal(user);
			await within(tag("Genre")).findByText("edited by you");
			expect(newValue("Genre")).toHaveValue("power metal");

			await user.click(screen.getByRole("button", { name: "Discard changes" }));

			await waitFor(() => expect(marked("Genre")).toBeNull());
			expect(newValue("Genre")).toHaveValue("");
			expect(reviewButton()).toBeDisabled();

			// A draft that was only hidden would still send the discarded edit.
			await user.click(screen.getByRole("button", { name: "Remove Date" }));
			await openReview(user);
			expect(
				posted(calls, PREVIEW)
					.map(inPathOrder)
					.map((draft) => draft.edits),
			).toEqual([[edit(tracks, { set: { Date: null } })]]);
		});
	});

	describe("leaving", () => {
		it("moves to another folder without asking when there is no draft", async () => {
			const { place, user } = openAlbum();
			await shown();

			await user.click(
				screen.getByRole("treeitem", { name: "Sabaton, folder" }),
			);

			await waitFor(() => expect(place()).toBe("/library/S/Sabaton"));
			expect(screen.queryByRole("alertdialog")).toBeNull();
		});

		it("asks before leaving with a draft, and Cancel stays on the album with the draft", async () => {
			const { place, user } = openAlbum();
			await shown();
			await setPowerMetal(user);

			await user.click(
				screen.getByRole("treeitem", { name: "Sabaton, folder" }),
			);

			const dialog = await screen.findByRole("alertdialog");
			expect(place()).toBe(`/library/${ECLIPTICA}`);
			await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

			await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
			expect(place()).toBe(`/library/${ECLIPTICA}`);
			expect(marked("Genre")).toBeVisible();
			expect(reviewButton()).toBeEnabled();
		});

		it("asks before following the Drop link with a draft, and leaves once confirmed", async () => {
			const { place, user } = openAlbum();
			await shown();
			await setPowerMetal(user);

			await user.click(screen.getByRole("link", { name: "Drop" }));

			const dialog = await screen.findByRole("alertdialog");
			expect(place()).toBe(`/library/${ECLIPTICA}`);
			await user.click(confirmIn(dialog));

			await waitFor(() => expect(place()).toBe("/"));
			expect(screen.queryByRole("alertdialog")).toBeNull();
		});

		it("opens another album with no draft after the leaving is confirmed", async () => {
			const { place, user } = openAlbum({
				shelves: { albums: { [SILENCE]: songsOfSilence() } },
			});
			await shown();
			await setPowerMetal(user);

			await user.click(
				screen.getByRole("treeitem", {
					name: "(2002) Songs of Silence, folder",
				}),
			);
			await user.click(confirmIn(await screen.findByRole("alertdialog")));

			await shown("Songs of Silence");
			expect(place()).toBe(`/library/${SILENCE}`);
			expect(box("Weballergy")).toBeChecked();
			expect(queryBox("My Land")).toBeNull();
			expect(marked("Genre")).toBeNull();
			expect(reviewButton()).toBeDisabled();
		});
	});
});
