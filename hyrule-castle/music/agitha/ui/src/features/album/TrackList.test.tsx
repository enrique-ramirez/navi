import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
	AlbumView,
	FileFacts,
	PlanEntry,
	PlanFile,
} from "@/shared/api/types";
import autoClean from "@/test/fixtures/auto-clean/plan.json";
import { renderWithProviders, screen, userEvent, within } from "@/test/render";

import { TrackList } from "./TrackList";

// As the server sends them: the page may find a tag by its readable name here
// or by the known keys, and either must work.
const NAMES: AlbumView["names"] = {
	id3: { TIT2: "Title", TRCK: "Track number", TPOS: "Disc number" },
	vorbis: {
		title: "Title",
		tracknumber: "Track number",
		discnumber: "Disc number",
	},
	mp4: { "©nam": "Title", trkn: "Track number", disk: "Disc number" },
	asf: {
		Title: "Title",
		"WM/TrackNumber": "Track number",
		"WM/PartOfSet": "Disc number",
	},
};

function facts(position: string, over: Partial<FileFacts> = {}): FileFacts {
	return {
		position,
		path_now: `Clean Album/${position}.mp3`,
		path_after: `C/Clean Band/(2010) Clean Album/${position}.mp3`,
		format: "MP3",
		family: "id3",
		lossless: false,
		bitrate: 320000,
		sample_rate: 44100,
		bit_depth: null,
		channels: 2,
		length: 200,
		size: 7_400_000,
		audio_url: `/api/drops/x/albums/01/audio/${position}.mp3`,
		...over,
	};
}

function view(files: PlanFile[], facts: FileFacts[]): AlbumView {
	const entry = structuredClone(autoClean.albums[0]) as PlanEntry;
	entry.files = files;
	return {
		drop: "x",
		n: "01",
		name: "Clean Album",
		state: "ready",
		stderr: "",
		error: null,
		step: null,
		file: null,
		busy: false,
		preview: entry,
		files: facts,
		names: NAMES,
		library_path: null,
		tree: [],
		extras_to: [],
		decision: null,
		cover: null,
		cover_now: null,
		duplicate: null,
		approvable: { ok: true, reason: null, code: null, hold: null },
	};
}

// The auto-clean album: one disc, three MP3s, titled One, Two, Three in plan
// order (alphabetically One, Three, Two). The lengths cover a padded second
// and a two-digit minute.
function cleanAlbum(): AlbumView {
	const files = structuredClone(autoClean.albums[0].files) as PlanFile[];
	return view(files, [
		facts("1-1", { length: 185.2 }),
		facts("1-2", { length: 62 }),
		facts("1-3", { length: 600.3 }),
	]);
}

// Two discs of FLAC with Vorbis keys, which carry no `/total` in the number.
function twoDiscFlac(): AlbumView {
	const file = (position: string, title: string): PlanFile => {
		const [disc = "", track = ""] = position.split("-");
		return {
			source: `drop/album/Ecliptica/${position}.flac`,
			destination: `S/Sonata Arctica/(1999) Ecliptica/${position}.flac`,
			position,
			before: { title: [title.toLowerCase()] },
			after: {
				title: [title],
				discnumber: [disc],
				disctotal: ["2"],
				tracknumber: [track],
			},
		};
	};
	const flac = (position: string, length: number) =>
		facts(position, {
			format: "FLAC",
			family: "vorbis",
			lossless: true,
			bit_depth: 16,
			length,
			audio_url: `/api/drops/x/albums/01/audio/${position}.flac`,
		});
	return view(
		[
			file("1-1", "Blank File"),
			file("1-12", "FullMoon"),
			file("2-3", "Kingdom for a Heart"),
		],
		[flac("1-1", 250), flac("1-12", 309), flac("2-3", 234)],
	);
}

// Two MP3s and a WMA with ASF keys.
function mixedAlbum(): AlbumView {
	const files = structuredClone(autoClean.albums[0].files) as PlanFile[];
	const wma = files[2]!;
	wma.source = "drop/album/Clean Album/03 three.wma";
	wma.after = {
		Title: ["Three"],
		"WM/TrackNumber": ["3"],
		"WM/PartOfSet": ["1/1"],
		"WM/AlbumTitle": ["Clean Album"],
	};
	return view(files, [
		facts("1-1"),
		facts("1-2"),
		facts("1-3", {
			format: "WMA",
			family: "asf",
			path_now: "Clean Album/03 three.wma",
			audio_url: "/api/drops/x/albums/01/audio/Clean%20Album/03%20three.wma",
		}),
	]);
}

let unplayable: string[] = [];
let played: HTMLMediaElement[] = [];
let paused: HTMLMediaElement[] = [];

beforeEach(() => {
	unplayable = [];
	played = [];
	paused = [];
	vi.spyOn(HTMLMediaElement.prototype, "canPlayType").mockImplementation(
		(mime: string) => (unplayable.includes(mime) ? "" : "probably"),
	);
	vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (
		this: HTMLMediaElement,
	) {
		played.push(this);
		return Promise.resolve();
	});
	vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (
		this: HTMLMediaElement,
	) {
		paused.push(this);
	});
});

// The player may outlive a render; ending whatever played leaves the next test
// with nothing playing.
afterEach(() => {
	act(() => {
		for (const audio of new Set(played))
			audio.dispatchEvent(new Event("ended"));
	});
	vi.restoreAllMocks();
});

// The body rows: the header row has column headers, not cells.
function trackRows() {
	const table = screen.getByRole("table", { name: "Tracks" });
	return within(table)
		.getAllByRole("row")
		.filter((row) => within(row).queryAllByRole("cell").length > 0);
}

function rowOf(title: string) {
	const row = trackRows().find((r) => cellTexts(r).includes(title));
	if (!row) throw new Error(`no row titled ${title}`);
	return row;
}

// The row's texts, one per innermost element, so a title reads apart from the file path under it.
function cellTexts(row: HTMLElement) {
	return Array.from(row.querySelectorAll("*"))
		.filter((element) => element.childElementCount === 0)
		.map((element) => element.textContent?.trim() ?? "")
		.filter((text) => text !== "");
}

// Tabs until focus is on the row's select control: the row itself or a
// control inside it other than the play button.
async function tabToSelect(
	user: ReturnType<typeof userEvent.setup>,
	row: HTMLElement,
) {
	const play = within(row).queryByRole("button", { name: /^(Play|Stop) / });
	for (let i = 0; i < 30; i++) {
		await user.tab();
		const focused = document.activeElement;
		if (focused && row.contains(focused) && focused !== play) return;
	}
	throw new Error("the row cannot be reached by keyboard");
}

describe("TrackList", () => {
	it("lists one row per file in plan order with its number, title and length", async () => {
		renderWithProviders(
			<TrackList
				changes={{}}
				view={cleanAlbum()}
				selected={null}
				onSelect={() => {}}
			/>,
		);

		await screen.findByRole("table", { name: "Tracks" });
		const rows = trackRows();
		expect(rows).toHaveLength(3);

		// The after titles (the source has them in lower case), not sorted.
		const texts = rows.map(cellTexts);
		expect(
			texts.map((cells) =>
				cells.find((text) => /^(One|Two|Three)$/.test(text)),
			),
		).toEqual(["One", "Two", "Three"]);
		// One disc: the track alone, padded.
		expect(texts[0]).toContain("01");
		expect(texts[1]).toContain("02");
		expect(texts[2]).toContain("03");
		expect(texts[0]).toContain("3:05");
		expect(texts[1]).toContain("1:02");
		expect(texts[2]).toContain("10:00");
	});

	it("numbers tracks disc-track when the album has more than one disc", async () => {
		renderWithProviders(
			<TrackList
				changes={{}}
				view={twoDiscFlac()}
				selected={null}
				onSelect={() => {}}
			/>,
		);

		await screen.findByRole("table", { name: "Tracks" });
		const texts = trackRows().map(cellTexts);
		expect(texts[0]).toEqual(
			expect.arrayContaining(["1-01", "Blank File", "4:10"]),
		);
		expect(texts[1]).toEqual(
			expect.arrayContaining(["1-12", "FullMoon", "5:09"]),
		);
		expect(texts[2]).toEqual(
			expect.arrayContaining(["2-03", "Kingdom for a Heart", "3:54"]),
		);
	});

	it("marks the selected track's row, and only it", async () => {
		renderWithProviders(
			<TrackList
				changes={{}}
				view={cleanAlbum()}
				selected="1-2"
				onSelect={() => {}}
			/>,
		);

		await screen.findByRole("table", { name: "Tracks" });
		expect(rowOf("Two")).toHaveAttribute("aria-selected", "true");
		expect(rowOf("One")).not.toHaveAttribute("aria-selected", "true");
		expect(rowOf("Three")).not.toHaveAttribute("aria-selected", "true");
	});

	it("selects a track when its row is clicked", async () => {
		const user = userEvent.setup();
		const onSelect = vi.fn();
		renderWithProviders(
			<TrackList
				changes={{}}
				view={cleanAlbum()}
				selected={null}
				onSelect={onSelect}
			/>,
		);

		await screen.findByRole("table", { name: "Tracks" });
		await user.click(within(rowOf("Three")).getByText("Three"));

		expect(onSelect).toHaveBeenCalledTimes(1);
		expect(onSelect).toHaveBeenCalledWith("1-3");
	});

	it.each(["{Enter}", " "])(
		"selects a track from the keyboard with %j",
		async (key) => {
			const user = userEvent.setup();
			const onSelect = vi.fn();
			renderWithProviders(
				<TrackList
					changes={{}}
					view={cleanAlbum()}
					selected={null}
					onSelect={onSelect}
				/>,
			);

			await screen.findByRole("table", { name: "Tracks" });
			await tabToSelect(user, rowOf("Two"));
			await user.keyboard(key);

			expect(onSelect).toHaveBeenCalledTimes(1);
			expect(onSelect).toHaveBeenCalledWith("1-2");
		},
	);

	it("plays the track's uploaded file and offers to stop it", async () => {
		const user = userEvent.setup();
		renderWithProviders(
			<TrackList
				changes={{}}
				view={cleanAlbum()}
				selected={null}
				onSelect={() => {}}
			/>,
		);

		await user.click(await screen.findByRole("button", { name: "Play Two" }));

		expect(played).toHaveLength(1);
		expect(new URL(played[0]?.src ?? "").pathname).toBe(
			"/api/drops/x/albums/01/audio/1-2.mp3",
		);
		expect(
			await screen.findByRole("button", { name: "Stop Two" }),
		).toBeInTheDocument();
		expect(
			screen.getByRole("button", { name: "Play One" }),
		).toBeInTheDocument();

		// Only pauses from the Stop click count: starting a track may pause first.
		paused = [];
		await user.click(screen.getByRole("button", { name: "Stop Two" }));

		expect(paused).toContain(played[0]);
		expect(
			await screen.findByRole("button", { name: "Play Two" }),
		).toBeInTheDocument();
		expect(screen.queryAllByRole("button", { name: /^Stop / })).toHaveLength(0);
	});

	it("plays one track at a time", async () => {
		const user = userEvent.setup();
		renderWithProviders(
			<TrackList
				changes={{}}
				view={cleanAlbum()}
				selected={null}
				onSelect={() => {}}
			/>,
		);

		await user.click(await screen.findByRole("button", { name: "Play One" }));
		await screen.findByRole("button", { name: "Stop One" });
		const first = played[0];

		await user.click(screen.getByRole("button", { name: "Play Three" }));

		expect(
			await screen.findByRole("button", { name: "Stop Three" }),
		).toBeInTheDocument();
		expect(screen.getAllByRole("button", { name: /^Stop / })).toHaveLength(1);
		expect(
			screen.getByRole("button", { name: "Play One" }),
		).toBeInTheDocument();
		// Whatever element was playing One stopped before Three started, or is
		// the same element now playing Three.
		const last = played.at(-1);
		expect(new URL(last?.src ?? "").pathname).toBe(
			"/api/drops/x/albums/01/audio/1-3.mp3",
		);
		expect(first === last || paused.includes(first!)).toBe(true);
	});

	it("goes back to Play when the track ends", async () => {
		const user = userEvent.setup();
		renderWithProviders(
			<TrackList
				changes={{}}
				view={cleanAlbum()}
				selected={null}
				onSelect={() => {}}
			/>,
		);

		await user.click(await screen.findByRole("button", { name: "Play One" }));
		await screen.findByRole("button", { name: "Stop One" });

		act(() => {
			played[0]?.dispatchEvent(new Event("ended"));
		});

		expect(
			await screen.findByRole("button", { name: "Play One" }),
		).toBeInTheDocument();
		expect(screen.queryAllByRole("button", { name: /^Stop / })).toHaveLength(0);
	});

	it("says the browser can't play WMA on that row, and the MP3 rows still play", async () => {
		unplayable = ["audio/x-ms-wma"];
		const user = userEvent.setup();
		renderWithProviders(
			<TrackList
				changes={{}}
				view={mixedAlbum()}
				selected={null}
				onSelect={() => {}}
			/>,
		);

		await screen.findByRole("table", { name: "Tracks" });
		const control = within(rowOf("Three")).getByRole("button", {
			name: "this browser can't play WMA",
		});
		expect(control).toBeDisabled();
		// Written out in the row, not only in the button's name: a sighted user
		// must not be left with a dead icon.
		expect(
			within(rowOf("Three")).getByText("this browser can't play WMA"),
		).toBeInTheDocument();
		expect(
			within(rowOf("Three")).queryByRole("button", { name: /^Play / }),
		).toBeNull();

		await user.click(control);
		expect(played).toHaveLength(0);

		await user.click(
			within(rowOf("One")).getByRole("button", { name: "Play One" }),
		);
		expect(played).toHaveLength(1);
		expect(
			await screen.findByRole("button", { name: "Stop One" }),
		).toBeInTheDocument();
	});

	it("never says it can't play an empty format when the file's facts are missing", async () => {
		renderWithProviders(
			<TrackList
				changes={{}}
				view={{ ...cleanAlbum(), files: [] }}
				selected={null}
				onSelect={() => {}}
			/>,
		);

		await screen.findByRole("table", { name: "Tracks" });
		expect(trackRows()).toHaveLength(3);
		const emptyFormat = /can't play\s*$/;
		for (const button of screen.queryAllByRole("button")) {
			expect(button).not.toHaveAccessibleName(emptyFormat);
		}
		expect(screen.queryAllByText(emptyFormat)).toHaveLength(0);
	});

	it("names the format the browser can't play", async () => {
		unplayable = ["audio/flac"];
		renderWithProviders(
			<TrackList
				changes={{}}
				view={twoDiscFlac()}
				selected={null}
				onSelect={() => {}}
			/>,
		);

		await screen.findByRole("table", { name: "Tracks" });
		const controls = screen.getAllByRole("button", {
			name: "this browser can't play FLAC",
		});
		expect(controls).toHaveLength(3);
		for (const control of controls) expect(control).toBeDisabled();
	});

	it("says how many of a track's own tags change, and nothing on a track whose tags stay", async () => {
		renderWithProviders(
			<TrackList
				changes={{ "1-1": 0, "1-2": 2 }}
				view={cleanAlbum()}
				selected={null}
				onSelect={() => {}}
			/>,
		);

		await screen.findByRole("table", { name: "Tracks" });
		const [one, two, three] = trackRows();
		expect(within(two!).getByText("2 of its tags change")).toBeInTheDocument();
		for (const row of [one!, three!])
			expect(within(row).queryByText(/of its tags change/)).toBeNull();
	});

	it("gives every button an accessible name", async () => {
		unplayable = ["audio/x-ms-wma"];
		renderWithProviders(
			<TrackList
				changes={{}}
				view={mixedAlbum()}
				selected="1-1"
				onSelect={() => {}}
			/>,
		);

		await screen.findByRole("table", { name: "Tracks" });
		const buttons = screen.getAllByRole("button");
		expect(buttons.length).toBeGreaterThanOrEqual(3);
		for (const button of buttons) expect(button).toHaveAccessibleName();
	});
});
