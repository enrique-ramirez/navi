import { QueryClient } from "@tanstack/react-query";
import { vi } from "vitest";

import type { Draft, LibraryAlbum, TrackRef } from "@/shared/api/types";

import { fakeFetch } from "./fakeFetch";
import {
	ECLIPTICA,
	editingHandlers,
	fixtures,
	libraryAddress,
	libraryHandlers,
	type Shelves,
	type Writes,
} from "./library";
import { screen, userEvent, within } from "./render";
import { renderApp } from "./renderApp";

// Ecliptica as `album.json` holds it: two FLACs, then two MP3s. My Land alone
// carries `symphonic metal`, 8th Commandment alone a ripper frame, and Replica
// has no genre.
export const BLANK = "01. Blank File.flac";
export const LAND = "02. My Land.flac";
export const EIGHTH = "03. 8th Commandment.mp3";
export const REPLICA = "04. Replica.mp3";

export const TITLES = ["Blank File", "My Land", "8th Commandment", "Replica"];

/** The album fixture with some of it replaced. A fresh copy on every call. */
export function albumOf(over: Partial<LibraryAlbum> = {}): LibraryAlbum {
	return { ...structuredClone(fixtures.album), ...over };
}

let server: ReturnType<typeof fakeFetch> | undefined;

interface Opened {
	shelves?: Shelves;
	writes?: Writes;
	/** Library-relative, as an album's `path` is. */
	album?: string;
	/** Fake timers that also run with the clock, for a case that waits on a poll. */
	clock?: boolean;
}

/**
 * The album page as a browser opening its address has it, with the library
 * and the editing routes faked. `played` is the address of every audio a play
 * control started, and `client` the page's query client, for a case that asks
 * for everything again. Call `closeAlbum` after each case.
 */
export function openAlbum({
	shelves,
	writes,
	album = ECLIPTICA,
	clock = false,
}: Opened = {}) {
	server?.restore();
	if (clock) vi.useFakeTimers({ shouldAdvanceTime: true });
	server = fakeFetch({
		...editingHandlers(writes),
		...libraryHandlers(shelves),
	});

	// jsdom plays nothing and says it can play nothing.
	const played: string[] = [];
	vi.spyOn(HTMLMediaElement.prototype, "canPlayType").mockReturnValue(
		"probably",
	);
	vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (
		this: HTMLMediaElement,
	) {
		played.push(new URL(this.src).pathname);
		return Promise.resolve();
	});
	vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});

	const client = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	const router = renderApp(libraryAddress(...album.split("/")), client);
	return {
		router,
		client,
		calls: server.calls,
		played,
		user: clock
			? userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
			: userEvent.setup(),
		// Decoded: the promise is the place the address names, not how a space is written.
		place: () => decodeURIComponent(router.state.location.pathname),
	};
}

export function closeAlbum() {
	server?.restore();
	server = undefined;
	vi.restoreAllMocks();
	vi.useRealTimers();
}

/** Advances the clock a poll at a time until `check` passes. Needs `clock`. */
export async function throughPolls(check: () => void, polls = 8) {
	for (let i = 0; i < polls; i++) {
		try {
			check();
			return;
		} catch {
			await vi.advanceTimersByTimeAsync(2_100);
		}
	}
	check();
}

/** The page once the album and the table of its tags are on it. */
export async function shown(title = "Ecliptica") {
	await screen.findByRole("heading", { name: new RegExp(title) });
	await screen.findByRole("textbox", { name: "Tag key" });
}

/**
 * The page once the album and the tags of its tracks are on it, whether or not
 * they can be edited. `shown` waits on a control a read-only page may not have.
 */
export async function shownWithTags(title = "Ecliptica") {
	await screen.findByRole("heading", { name: new RegExp(title) });
	await screen.findByRole("rowheader", { name: /^Genre/ });
}

/** A track's checkbox. */
export const box = (title: string) =>
	screen.getByRole("checkbox", { name: `Select ${title}` });
export const queryBox = (title: string) =>
	screen.queryByRole("checkbox", { name: `Select ${title}` });

// A row's header is its tag's name, then the mark of an edit where it has one.
const rowsOf = (name: string) =>
	screen
		.queryAllByRole("rowheader")
		.filter((header) => header.firstChild?.textContent === name)
		.map((header) => header.closest("tr") as HTMLElement);

/** A tag's row, in the album's table or the one of the track on show. */
export const queryTag = (name: string) => {
	const [row, ...rest] = rowsOf(name);
	if (rest.length > 0) throw new Error(`${name} has more than one row`);
	return row ?? null;
};
export const tag = (name: string) => {
	const row = queryTag(name);
	if (!row) throw new Error(`no row for ${name}`);
	return row;
};

/** The table's mark on a tag the draft changes. */
export const marked = (name: string) =>
	within(tag(name)).queryByText("edited by you");

/** The field a tag's new values are typed into. */
export const newValue = (name: string) =>
	within(tag(name)).getByRole("textbox", { name: `New ${name}` });

export const reviewButton = () =>
	screen.getByRole("button", { name: "Review changes" });

/** One edit through the table, over the tracks selected: their Genre becomes `power metal` alone. */
export async function setPowerMetal(user: ReturnType<typeof userEvent.setup>) {
	const field = await screen.findByRole("textbox", { name: "New Genre" });
	await user.clear(field);
	await user.type(field, "power metal{Enter}");
}

/** Asks for the review and gives its region once the preview is in it. */
export async function openReview(user: ReturnType<typeof userEvent.setup>) {
	await user.click(reviewButton());
	const review = await screen.findByRole("region", { name: "Review changes" });
	await within(review).findByRole("button", { name: "Save" });
	return review;
}

/** How many times an album's route was asked for. */
export function albumGets(
	calls: { method: string; url: string }[],
	album = ECLIPTICA,
) {
	const path = `/api${libraryAddress(...album.split("/"))}`;
	return calls.filter(
		(call) => call.method === "GET" && new URL(call.url).pathname === path,
	).length;
}

const byPath = (a: TrackRef, b: TrackRef) => a.path.localeCompare(b.path);

/** A draft with its tracks in path order, in each edit too: the order of either is not promised. */
export function inPathOrder(draft: Draft): Draft {
	return {
		...draft,
		tracks: [...draft.tracks].sort(byPath),
		edits: draft.edits.map((edit) => ({
			...edit,
			tracks: [...edit.tracks].sort(byPath),
		})),
	};
}

const locked = (control: HTMLElement) =>
	(control as HTMLInputElement | HTMLButtonElement).disabled === true;

// The controls an edit goes through. One that is absent is not in the list.
function editingControls() {
	return {
		tracks: [
			...TITLES.flatMap((title) => queryBox(title) ?? []),
			...screen.queryAllByRole("checkbox", { name: "Select all tracks" }),
		],
		tags: [
			...screen.queryAllByRole("button", {
				name: /^(Remove |Undo your edit of |Keep the current )/,
			}),
			...screen.queryAllByRole("textbox", { name: /^(New |Tag key)/ }),
			...screen.queryAllByRole("button", { name: "Add tag" }),
		],
		review: screen.queryAllByRole("button", { name: "Review changes" }),
		save: screen.queryAllByRole("button", { name: "Save" }),
	};
}

/** Which of the page's editing controls can still be used, by name. None while the album is read-only. */
export function usable() {
	return Object.values(editingControls())
		.flat()
		.filter((control) => !locked(control))
		.map(
			(control) =>
				control.getAttribute("aria-label") ||
				control.textContent ||
				control.closest("label")?.textContent ||
				"a checkbox",
		);
}
