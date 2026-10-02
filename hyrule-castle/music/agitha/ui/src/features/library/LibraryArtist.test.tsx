import { afterEach, describe, expect, it } from "vitest";

import type { LibraryTrack } from "@/shared/api/types";
import { ECLIPTICA, posted, SONATA } from "@/test/library";
import {
	dropSymphonicMetal,
	LAND,
	marked,
	queryTag,
	reviewButton,
	TITLES,
	tag,
} from "@/test/libraryAlbum";
import {
	ALBUM_TITLES,
	ALBUMS,
	type AlbumTitle,
	ARTIST,
	albumBlock,
	albumBox,
	allBox,
	closeArtist,
	disclosure,
	expand,
	findTag,
	inAlbumOrder,
	LOCKED,
	openArtist,
	openBatchReview,
	queryTrackBox,
	SILENCE,
	shownArtist,
	sonata,
	trackBox,
	trackOf,
	unselected,
} from "@/test/libraryArtist";
import { screen, waitFor, within } from "@/test/render";

// A case opens the page with `openArtist`, which serves Sonata Arctica's three
// albums unless told otherwise, and starts from `unselected`. The batch's
// preview and its Apply are in `BatchPreview.test.tsx`.
afterEach(closeArtist);

const HERE = `/library/${SONATA}`;
const PREVIEW = "/api/library/preview";
const SENTENCE = "Edit on the album's page";

// The titles of an album's tracks in the order their checkboxes are on the page.
function tracksShown(album: AlbumTitle) {
	const titles: readonly string[] = ALBUMS[album].tracks;
	return within(albumBlock(album))
		.getAllByRole("checkbox")
		.flatMap(
			(each) =>
				titles.find((title) => each === queryTrackBox(album, title)) ?? [],
		);
}

// A track as a draft sends it: its album, what the artist route served, and what it showed for the tags edited.
const sent = (
	album: string,
	track: LibraryTrack,
	seen: Record<string, string[] | null>,
) => ({ album, path: track.path, loaded: track.loaded, seen });

describe("LibraryArtist", () => {
	describe("the albums", () => {
		it("has the artist's name as its heading, and shows each album with its year", async () => {
			openArtist();
			await shownArtist();

			expect(screen.getByRole("heading", { name: ARTIST })).toBeVisible();
			const years = ALBUM_TITLES.map((title) => ALBUMS[title].year);
			for (const title of ALBUM_TITLES)
				expect(
					years.filter((year) => albumBlock(title).textContent?.includes(year)),
				).toEqual([ALBUMS[title].year]);
		});

		it("shows an album's cover, and none for an album that has none", async () => {
			const artist = sonata();
			openArtist({ artist });
			await shownArtist();

			for (const [at, title] of (
				["Ecliptica", "Songs of Silence"] as const
			).entries())
				expect(
					within(albumBlock(title)).getByRole("img", {
						name: `${title} cover`,
					}),
				).toHaveAttribute("src", artist.albums[at]!.cover_url);
			expect(artist.albums[2]!.cover_url).toBeNull();
			expect(
				screen.queryByRole("img", { name: /For the Sake of Revenge/ }),
			).toBeNull();
		});

		it("lists the albums closed, and opens one to its own tracks in the order served", async () => {
			const { user } = openArtist();
			await shownArtist();
			const opener = disclosure("Songs of Silence");
			expect(opener).toHaveAccessibleName(/Songs of Silence/);
			expect(opener).toHaveAttribute("aria-expanded", "false");
			expect(
				screen.queryByRole("checkbox", { name: "Select Intro" }),
			).toBeNull();

			await user.click(opener);

			expect(disclosure("Songs of Silence")).toHaveAttribute(
				"aria-expanded",
				"true",
			);
			expect(tracksShown("Songs of Silence")).toEqual(
				ALBUMS["Songs of Silence"].tracks,
			);
			// The album beside it stays closed.
			expect(disclosure("Ecliptica")).toHaveAttribute("aria-expanded", "false");
			expect(
				screen.queryByRole("checkbox", { name: "Select Blank File" }),
			).toBeNull();
		});

		it("closes an open album again", async () => {
			const { user } = openArtist();
			await shownArtist();
			await expand(user, "Ecliptica");
			expect(tracksShown("Ecliptica")).toEqual(TITLES);

			await user.click(disclosure("Ecliptica"));

			expect(disclosure("Ecliptica")).toHaveAttribute("aria-expanded", "false");
			expect(
				screen.queryByRole("checkbox", { name: "Select Blank File" }),
			).toBeNull();
		});

		it("follows an album's title to the album's page", async () => {
			const { place, user } = openArtist();
			await shownArtist();

			await user.click(
				within(albumBlock("Ecliptica")).getByRole("link", {
					name: /Ecliptica/,
				}),
			);

			await waitFor(() => expect(place()).toBe(`/library/${ECLIPTICA}`));
			expect(screen.queryByRole("alertdialog")).toBeNull();
		});
	});

	describe("selection", () => {
		it("opens with no track selected and the panel over none", async () => {
			const { user } = openArtist();
			await shownArtist();

			expect(allBox()).not.toBeChecked();
			for (const title of ALBUM_TITLES)
				expect(albumBox(title)).not.toBeChecked();
			await expand(user, "Ecliptica");
			for (const title of TITLES)
				expect(trackBox("Ecliptica", title)).not.toBeChecked();
			expect(queryTag("Genre")).toBeNull();
		});

		it("shows the panel over one selected track, and its album stays unchecked while only some of its tracks are selected", async () => {
			const { user } = openArtist();
			await unselected(user);
			await expand(user, "Ecliptica");

			await user.click(trackBox("Ecliptica", "My Land"));

			// Both of its genres are on the one track selected, so neither has a count.
			expect(await findTag("Genre")).toHaveTextContent("symphonic metal");
			expect(tag("Genre")).not.toHaveTextContent(/\d\/\d/);
			expect(trackBox("Ecliptica", "My Land")).toBeChecked();
			expect(trackBox("Ecliptica", "Blank File")).not.toBeChecked();
			expect(albumBox("Ecliptica")).not.toBeChecked();
			expect(allBox()).not.toBeChecked();
		});

		it("selects every track of an album with the album's checkbox, before the album is opened", async () => {
			const { user } = openArtist();
			await unselected(user);

			await user.click(albumBox("Songs of Silence"));

			expect(await findTag("Genre")).toHaveTextContent("heavy metal 1/4");
			// Ecliptica alone carries it.
			expect(tag("Genre")).not.toHaveTextContent("symphonic metal");
			expect(albumBox("Songs of Silence")).toBeChecked();
			expect(albumBox("Ecliptica")).not.toBeChecked();
			expect(allBox()).not.toBeChecked();
			await expand(user, "Songs of Silence");
			for (const title of ALBUMS["Songs of Silence"].tracks)
				expect(trackBox("Songs of Silence", title)).toBeChecked();
		});

		it("counts over a track of one album and the whole of another together", async () => {
			const { user } = openArtist();
			await unselected(user);
			await expand(user, "Ecliptica");

			await user.click(trackBox("Ecliptica", "My Land"));
			await user.click(albumBox("Songs of Silence"));

			expect(await findTag("Genre")).toHaveTextContent("symphonic metal 1/5");
			expect(tag("Genre")).toHaveTextContent("heavy metal 1/5");
		});

		it("selects every track of the artist with one control, and none with the same control", async () => {
			const { user } = openArtist();
			await unselected(user);

			await user.click(allBox());

			expect(await findTag("Genre")).toHaveTextContent("power metal 8/10");
			expect(tag("Genre")).toHaveTextContent("rock 2/10");
			expect(tag("Genre")).toHaveTextContent("symphonic metal 1/10");
			expect(allBox()).toBeChecked();
			for (const title of ALBUM_TITLES) expect(albumBox(title)).toBeChecked();

			await user.click(allBox());

			expect(allBox()).not.toBeChecked();
			for (const title of ALBUM_TITLES)
				expect(albumBox(title)).not.toBeChecked();
			expect(queryTag("Genre")).toBeNull();
		});

		it("takes every track of an album out of the selection with the album's checkbox", async () => {
			const { user } = openArtist();
			await unselected(user);
			await user.click(allBox());

			await user.click(albumBox("Ecliptica"));

			// Songs of Silence's four and one of For the Sake of Revenge's two.
			expect(await findTag("Genre")).toHaveTextContent("power metal 5/6");
			expect(albumBox("Ecliptica")).not.toBeChecked();
			expect(albumBox("Songs of Silence")).toBeChecked();
			expect(allBox()).not.toBeChecked();
		});

		it("unchecks an album and the artist when one track is taken out, and checks both once it is back", async () => {
			const { user } = openArtist();
			await unselected(user);
			await user.click(allBox());
			await expand(user, "For the Sake of Revenge");

			await user.click(trackBox("For the Sake of Revenge", "My Land"));

			expect(albumBox("For the Sake of Revenge")).not.toBeChecked();
			expect(allBox()).not.toBeChecked();
			expect(albumBox("Ecliptica")).toBeChecked();
			expect(await findTag("Genre")).toHaveTextContent("rock 1/9");

			await user.click(trackBox("For the Sake of Revenge", "My Land"));

			expect(albumBox("For the Sake of Revenge")).toBeChecked();
			expect(allBox()).toBeChecked();
		});

		it("tells a track from one of the same file name and title in another album", async () => {
			const { user } = openArtist();
			await unselected(user);
			await expand(user, "Ecliptica");
			await expand(user, "For the Sake of Revenge");

			await user.click(trackBox("For the Sake of Revenge", "My Land"));

			expect(trackBox("For the Sake of Revenge", "My Land")).toBeChecked();
			expect(trackBox("Ecliptica", "My Land")).not.toBeChecked();
			// The one in For the Sake of Revenge is `rock`; Ecliptica's is not.
			expect(await findTag("Genre")).toHaveTextContent("rock");
			expect(tag("Genre")).not.toHaveTextContent("metal");
		});
	});

	describe("the panel on this page", () => {
		it("shows each tag that names a track or an album or moves a file read-only, with where to edit it", async () => {
			// The fixture's tracks carry seven of the eleven; one track gets the other four.
			const artist = sonata();
			Object.assign(trackOf(artist, ECLIPTICA, "01. Blank File.flac").tags, {
				artistsort: ["Sonata Arctica"],
				albumartistsort: ["Sonata Arctica"],
				originaldate: ["1999-11-22"],
				discsubtitle: ["The album"],
			});
			const { user } = openArtist({ artist });
			await unselected(user);
			await user.click(allBox());
			await findTag("Genre");

			const editable = LOCKED.filter((name) => {
				const row = within(tag(name));
				return (
					row.queryByText(SENTENCE) === null ||
					row.queryAllByRole("textbox").length > 0 ||
					row.queryAllByRole("combobox").length > 0 ||
					row.queryAllByRole("button").length > 0
				);
			});
			expect(editable).toEqual([]);
		});

		it("leaves a tag that does neither editable, and says nothing of the album's page on it", async () => {
			const { user } = openArtist();
			await unselected(user);
			await user.click(allBox());

			const genre = within(await findTag("Genre"));
			expect(genre.getByRole("combobox", { name: "Set Genre" })).toBeEnabled();
			expect(
				genre.getByRole("combobox", { name: "Add value, Genre" }),
			).toBeEnabled();
			expect(genre.getByRole("button", { name: "Remove Genre" })).toBeEnabled();
			expect(genre.queryByText(SENTENCE)).toBeNull();
		});

		it("offers no cover to replace and no swap, with two tracks of one album selected", async () => {
			const { user } = openArtist();
			await unselected(user);
			await expand(user, "Ecliptica");
			await user.click(trackBox("Ecliptica", "Blank File"));
			await user.click(trackBox("Ecliptica", "My Land"));
			// The panel is up, so what is missing is not missing for want of a selection.
			await findTag("Genre");

			expect(
				screen
					.queryAllByRole("button", { name: /swap|cover/i })
					.map((button) => button.textContent),
			).toEqual([]);
			expect(document.querySelector('input[type="file"]')).toBeNull();
		});
	});

	describe("the draft", () => {
		it("offers no review until an edit is made, then marks the tag the edit changes", async () => {
			const { calls, user } = openArtist();
			await unselected(user);
			await user.click(allBox());
			await findTag("Genre");
			expect(reviewButton()).toBeDisabled();
			expect(marked("Genre")).toBeNull();

			await dropSymphonicMetal(user);

			expect(await within(tag("Genre")).findByText("changed")).toBeVisible();
			expect(tag("Genre")).not.toHaveTextContent("symphonic metal");
			expect(reviewButton()).toBeEnabled();
			// The edit is on the page alone until the review is asked for.
			expect(calls.filter((call) => call.method !== "GET")).toEqual([]);
		});

		it("posts to preview each selected track once with its album, as it was loaded, and one edit over them all", async () => {
			const artist = sonata();
			const land = trackOf(artist, ECLIPTICA, LAND);
			const [intro, weballergy, fullMoon, dana] = artist.albums[1]!.tracks;
			const { calls, user } = openArtist({ artist });
			await unselected(user);
			await expand(user, "Ecliptica");

			// The whole of a closed album and one track of an open one. For the Sake
			// of Revenge has a track at My Land's path, and none of it is selected.
			await user.click(albumBox("Songs of Silence"));
			await user.click(trackBox("Ecliptica", "My Land"));
			await user.type(
				within(await findTag("Genre")).getByRole("combobox", {
					name: "Add value, Genre",
				}),
				"heavy metal{Enter}",
			);
			await openBatchReview(user);

			expect(posted(calls, PREVIEW).map(inAlbumOrder)).toEqual([
				{
					tracks: [
						sent(ECLIPTICA, land, {
							Genre: ["power metal", "symphonic metal"],
						}),
						sent(SILENCE, intro!, { Genre: ["power metal"] }),
						sent(SILENCE, weballergy!, { Genre: ["power metal"] }),
						// What the file holds: it carried the value added before the edit.
						sent(SILENCE, fullMoon!, { Genre: ["power metal", "heavy metal"] }),
						sent(SILENCE, dana!, { Genre: ["power metal"] }),
					],
					edits: [
						{
							tracks: [
								{ album: ECLIPTICA, path: LAND },
								...[intro, weballergy, fullMoon, dana].map((track) => ({
									album: SILENCE,
									path: track!.path,
								})),
							],
							set: {},
							add: { Genre: ["heavy metal"] },
							remove: {},
						},
					],
					swaps: [],
					cover: null,
					batch: true,
				},
			]);
		});
	});

	describe("leaving", () => {
		it("moves to another folder without asking when there is no draft", async () => {
			const { place, user } = openArtist();
			await unselected(user);
			await user.click(allBox());

			await user.click(
				screen.getByRole("treeitem", { name: "Sabaton, folder" }),
			);

			await waitFor(() => expect(place()).toBe("/library/S/Sabaton"));
			expect(screen.queryByRole("alertdialog")).toBeNull();
		});

		it("asks before leaving with a draft, and Cancel stays on the artist with the draft", async () => {
			const { place, user } = openArtist();
			await unselected(user);
			await user.click(allBox());
			await dropSymphonicMetal(user);

			await user.click(
				screen.getByRole("treeitem", { name: "Sabaton, folder" }),
			);

			const dialog = await screen.findByRole("alertdialog");
			expect(place()).toBe(HERE);
			await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

			await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
			expect(place()).toBe(HERE);
			expect(marked("Genre")).toBeVisible();
			expect(reviewButton()).toBeEnabled();
		});
	});
});
