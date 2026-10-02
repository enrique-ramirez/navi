import type {
	Draft,
	JobAlbum,
	JobState,
	LibraryAlbum,
	LibraryAlbumSummary,
	LibraryArtist,
	LibraryJob,
	LibraryPreview,
	PreviewAlbum,
	PreviewTrack,
} from "@/shared/api/types";

import {
	ECLIPTICA,
	fixtures,
	type Shelves,
	SONATA,
	type Writes,
} from "./library";
import { closeAlbum, openAlbum, TITLES } from "./libraryAlbum";
import { screen, type userEvent, within } from "./render";

type User = ReturnType<typeof userEvent.setup>;

export const ARTIST = "Sonata Arctica";
export const SILENCE = `${SONATA}/(2002) Songs of Silence`;
export const REVENGE = `${SONATA}/(2006) For the Sake of Revenge`;

// Sonata Arctica as these cases serve it. Ecliptica and Songs of Silence are
// `artist.json`'s: four tracks each, the second with a match open in review.
// For the Sake of Revenge is added here: no cover, two FLACs, and its second
// track has the file name and the title of Ecliptica's second.
export const ALBUMS = {
	Ecliptica: { path: ECLIPTICA, year: "1999", tracks: TITLES },
	"Songs of Silence": {
		path: SILENCE,
		year: "2002",
		// As served, which is not alphabetical.
		tracks: ["Intro", "Weballergy", "FullMoon", "Letter to Dana"],
	},
	"For the Sake of Revenge": {
		path: REVENGE,
		year: "2006",
		tracks: ["Prelude for Reckoning", "My Land"],
	},
} as const;

export type AlbumTitle = keyof typeof ALBUMS;

export const ALBUM_TITLES = Object.keys(ALBUMS) as AlbumTitle[];

/** The tags the artist page leaves to each album's own page, by the names the panel shows. */
export const LOCKED = [
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

/**
 * The artist's answer with the readable names beside the albums. The contract
 * gives `LibraryArtist` no `names`, and the panel cannot name a tag without
 * them, so the fake offers them here; the album route goes on serving its own.
 */
export type ServedArtist = LibraryArtist & { names: LibraryAlbum["names"] };

function revenge(): LibraryAlbumSummary {
	const [blank, land] = structuredClone(fixtures.artist.albums[0]!.tracks);
	const audio = (file: string) =>
		`/api/library/S/Sonata%20Arctica/%282006%29%20For%20the%20Sake%20of%20Revenge/audio/${encodeURIComponent(file)}`;
	const { rating: _rating, ...kept } = blank!.tags;
	return {
		path: REVENGE,
		name: "(2006) For the Sake of Revenge",
		year: "2006",
		title: "For the Sake of Revenge",
		cover_url: null,
		match: null,
		tracks: [
			{
				...blank!,
				path: "01. Prelude for Reckoning.flac",
				audio_url: audio("01. Prelude for Reckoning.flac"),
				size: 30100200,
				loaded: { size: 30100200, mtime: 1730000000.25 },
				tags: {
					...kept,
					album: ["For the Sake of Revenge"],
					date: ["2006"],
					title: ["Prelude for Reckoning"],
					genre: ["power metal", "rock"],
				},
			},
			{
				...land!,
				audio_url: audio(land!.path),
				size: 36000111,
				loaded: { size: 36000111, mtime: 1730000002.5 },
				tags: {
					...land!.tags,
					album: ["For the Sake of Revenge"],
					date: ["2006"],
					genre: ["rock"],
				},
			},
		],
	};
}

/** Sonata Arctica's three albums. A fresh copy on every call, so a case may change it. */
export function sonata(): ServedArtist {
	return {
		albums: [...structuredClone(fixtures.artist.albums), revenge()],
		names: structuredClone(fixtures.album.names),
	};
}

/** A track of the artist as served, by its album and its path in it. */
export function trackOf(artist: LibraryArtist, album: string, path: string) {
	const track = artist.albums
		.find((each) => each.path === album)
		?.tracks.find((each) => each.path === path);
	if (!track) throw new Error(`${album} has no ${path}`);
	return track;
}

interface Opened {
	/** The artist's answer, or a function for one that changes while the page is open. */
	artist?: ServedArtist | (() => Response);
	shelves?: Shelves;
	writes?: Writes;
	/** Fake timers that also run with the clock, for a case that waits on a poll. */
	clock?: boolean;
}

/**
 * The artist page as a browser opening its address has it, with the library
 * and the editing routes faked. Call `closeArtist` after each case.
 */
export function openArtist({
	artist = sonata(),
	shelves,
	writes,
	clock,
}: Opened = {}) {
	return openAlbum({
		album: SONATA,
		clock,
		writes,
		shelves: {
			...shelves,
			artists: { ...shelves?.artists, [SONATA]: artist },
		},
	});
}

export const closeArtist = closeAlbum;

export const allBox = () =>
	screen.getByRole("checkbox", { name: "Select all tracks" });

/** The page once the artist and its albums are on it. */
export async function shownArtist() {
	// The app's first render in a file can pass the default second on a busy machine.
	await screen.findByRole("heading", { name: ARTIST }, { timeout: 3000 });
	await screen.findByRole("checkbox", { name: "Select all tracks" });
}

/**
 * The page with the artist on it and no track selected. What is selected when
 * the page opens is one case's to say; every other case starts from here.
 */
export async function unselected(user: User) {
	await shownArtist();
	if ((allBox() as HTMLInputElement).checked) await user.click(allBox());
}

/** An album's own checkbox, which stands for every track of it. */
export const albumBox = (title: AlbumTitle) =>
	screen.getByRole("checkbox", { name: `Select ${title}` });

/**
 * The element an album has to itself: the nearest list item, section or
 * article around its checkbox. Its cover, year, title and tracks are in it.
 */
export function albumBlock(title: AlbumTitle) {
	const block = albumBox(title).closest<HTMLElement>("li, section, article");
	if (!block || block.contains(allBox()))
		throw new Error(
			`${title} is not in a list item, section or article of its own`,
		);
	return block;
}

/** The button that opens an album to its tracks: the one in its block that says whether it is open. */
export function disclosure(title: AlbumTitle) {
	const [button, ...rest] = within(albumBlock(title))
		.getAllByRole("button")
		.filter((each) => each.hasAttribute("aria-expanded"));
	if (!button || rest.length > 0)
		throw new Error(`${title} has not one button with aria-expanded`);
	return button;
}

/** Opens an album to its tracks where it is closed. */
export async function expand(user: User, title: AlbumTitle) {
	if (disclosure(title).getAttribute("aria-expanded") !== "true")
		await user.click(disclosure(title));
	await within(albumBlock(title)).findByRole("checkbox", {
		name: `Select ${ALBUMS[title].tracks[0]}`,
	});
}

/** A track's checkbox in its album: two albums may hold a track of one title. */
export const trackBox = (album: AlbumTitle, title: string) =>
	within(albumBlock(album)).getByRole("checkbox", { name: `Select ${title}` });
export const queryTrackBox = (album: AlbumTitle, title: string) =>
	within(albumBlock(album)).queryByRole("checkbox", {
		name: `Select ${title}`,
	});

/** A tag's row in the panel, once the panel has it. */
export const findTag = (name: string) => screen.findByRole("group", { name });

/** Asks for the review and gives its region once the preview is in it. */
export async function openBatchReview(user: User) {
	await user.click(screen.getByRole("button", { name: "Review changes" }));
	const review = await screen.findByRole("region", { name: "Review changes" });
	await within(review).findByRole("button", { name: "Apply" });
	return review;
}

/**
 * The albums named by the nearest element at or above `from` that names any,
 * looking no further up than `stop`. An album is named by its title, which its
 * path and its folder's name also hold. None where nothing below `stop` names one.
 */
export function albumsAround(
	from: Element,
	stop: Element = document.body,
): AlbumTitle[] {
	for (
		let at: Element | null = from;
		at && at !== stop;
		at = at.parentElement
	) {
		const named = ALBUM_TITLES.filter((title) =>
			at?.textContent?.includes(title),
		);
		if (named.length > 0) return named;
	}
	return [];
}

const isOf = (title: AlbumTitle, from: Element, stop?: Element) =>
	albumsAround(from, stop).join(" | ") === title;

const STATES: JobState[] = [
	"waiting",
	"writing",
	"verifying",
	"done",
	"failed",
];

/** The job states the page shows for an album: each a text of its own beside the album's name. */
export function statesOf(title: AlbumTitle) {
	return STATES.filter((state) =>
		screen.queryAllByText(state).some((shown) => isOf(title, shown)),
	);
}

/** Which of the sentences the page shows beside an album's name, inside `scope`. */
export function sentencesOf(
	title: AlbumTitle,
	sentences: string[],
	scope: HTMLElement = document.body,
) {
	return sentences.filter((sentence) =>
		within(scope)
			.queryAllByText(sentence, { exact: false })
			.some((shown) => isOf(title, shown, scope)),
	);
}

/** An album of a preview that stays where it is, with nothing changed, refused or skipped unless `over` says so. */
export function previewAlbum(
	path: string,
	over: Partial<PreviewAlbum> = {},
): PreviewAlbum {
	return {
		path,
		new_path: path,
		tracks: [],
		cover: null,
		problems: [],
		refused: [],
		skip: null,
		...over,
	};
}

export const previewOver = (...albums: PreviewAlbum[]): LibraryPreview => ({
	albums,
});

/** A track of a preview whose genres change and whose file stays. */
export const genreChange = (
	path: string,
	before: string[] | null,
	after: string[] | null,
): PreviewTrack => ({
	path,
	new_path: path,
	changes: [{ key: "Genre", before, after }],
});

/** An album of a job, staying where it is. */
export const written = (
	path: string,
	state: JobState,
	error: string | null = null,
): JobAlbum => ({ path, new_path: path, state, error });

export const jobOver = (...albums: JobAlbum[]): LibraryJob => ({ albums });

const place = (track: { album: string; path: string }) =>
	`${track.album}/${track.path}`;
const byPlace = (
	a: { album: string; path: string },
	b: { album: string; path: string },
) => place(a).localeCompare(place(b));

/** A draft with its tracks in album then path order, in each edit too: the order of either is not promised. */
export function inAlbumOrder(draft: Draft): Draft {
	return {
		...draft,
		tracks: [...draft.tracks].sort(byPlace),
		edits: draft.edits.map((edit) => ({
			...edit,
			tracks: [...edit.tracks].sort(byPlace),
		})),
	};
}

const off = (control: HTMLElement) =>
	(control as HTMLInputElement | HTMLButtonElement).disabled === true;

/**
 * Which of the page's editing controls can still be used, by name: every
 * selecting checkbox, the panel's controls, Review changes and Apply. One that
 * is not on the page is not in the list. None while a batch is being written.
 */
export function usableOnArtist() {
	return [
		...screen.queryAllByRole("checkbox", { name: /^Select / }),
		...screen.queryAllByRole("button", { name: /^Remove / }),
		...screen.queryAllByRole("textbox", { name: /^(Set |Add value, |Tag )/ }),
		...screen.queryAllByRole("combobox", { name: /^(Set |Add value, )/ }),
		...screen.queryAllByRole("button", {
			name: /^(Add tag|Review changes|Apply)$/,
		}),
	]
		.filter((control) => !off(control))
		.map((control) =>
			(
				control.getAttribute("aria-label") ||
				control.textContent ||
				control.closest("label")?.textContent ||
				"a checkbox"
			).trim(),
		);
}
