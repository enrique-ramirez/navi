import { describe, expect, it } from "vitest";

import type {
	AlbumView,
	FileFacts,
	PlanEntry,
	TagMap,
} from "@/shared/api/types";
import autoClean from "@/test/fixtures/auto-clean/plan.json";
import { renderWithProviders, screen, userEvent, within } from "@/test/render";

import { AlbumHeader } from "./AlbumHeader";

const NAMES: AlbumView["names"] = {
	id3: {
		TALB: "Album",
		TPE2: "Album artist",
		TDRC: "Date",
		TCON: "Genre",
		TIT2: "Title",
		TRCK: "Track number",
		TPOS: "Disc number",
	},
	vorbis: {
		album: "Album",
		albumartist: "Album artist",
		date: "Date",
		genre: "Genre",
		title: "Title",
		tracknumber: "Track number",
		discnumber: "Disc number",
	},
	mp4: {
		"©alb": "Album",
		aART: "Album artist",
		"©day": "Date",
		"©gen": "Genre",
		"©nam": "Title",
		trkn: "Track number",
		disk: "Disc number",
	},
	asf: {
		"WM/AlbumTitle": "Album",
		"WM/AlbumArtist": "Album artist",
		"WM/Year": "Date",
		"WM/Genre": "Genre",
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
		length: 185.2,
		size: 7_400_000,
		audio_url: `/api/drops/x/albums/01/audio/Clean%20Album/${position}.mp3`,
		...over,
	};
}

// The auto-clean preview, changed where the fixture cannot tell two readings
// apart: its album artist equals its track artist, its before album title
// equals the after one, and it has one genre.
function preview(): PlanEntry {
	const entry = structuredClone(autoClean.albums[0]) as PlanEntry;
	for (const file of entry.files) {
		file.after.TPE2 = ["The Clean Band"];
		file.after.TCON = ["rock", "britpop"];
		file.before.TALB = ["Clean Album (2009 rip)"];
	}
	return entry;
}

function view(over: Partial<AlbumView> = {}): AlbumView {
	const entry = over.preview ?? preview();
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
		files: entry.files.map((file) => facts(file.position)),
		names: NAMES,
		library_path: `/srv/music/library/${entry.destination}`,
		tree: [],
		extras_to: [],
		decision: null,
		cover: {
			url: "/api/drops/x/albums/01/cover",
			width: 600,
			height: 600,
			passes: true,
			problem: null,
		},
		duplicate: null,
		approvable: { ok: true, reason: null, code: null, hold: null },
		...over,
	};
}

// A FLAC album, so the header has to find the four tags by the files' family
// and not by id3's keys.
function flacView(): AlbumView {
	const tags = (title: string): TagMap => ({
		album: ["Ecliptica"],
		albumartist: ["Sonata Arctica"],
		artist: ["Sonata Arctica"],
		date: ["1999-11-11"],
		genre: ["power metal"],
		title: [title],
	});
	const entry = preview();
	entry.files = [
		{
			source: "drop/album/Ecliptica/01.flac",
			destination: "S/Sonata Arctica/(1999) Ecliptica/01. Blank File.flac",
			position: "1-1",
			before: { album: ["ecliptica"], date: ["1999"], title: ["blank file"] },
			after: tags("Blank File"),
		},
	];
	return view({
		preview: entry,
		files: [facts("1-1", { format: "FLAC", family: "vorbis", lossless: true })],
	});
}

describe("AlbumHeader", () => {
	it("shows the preview's album title as the page heading, with its album artist and year", async () => {
		renderWithProviders(<AlbumHeader view={view()} />);

		expect(
			await screen.findByRole("heading", { level: 1, name: "Clean Album" }),
		).toBeInTheDocument();
		// TPE2, not the track artist TPE1 ("Clean Band").
		expect(screen.getByText("The Clean Band")).toBeInTheDocument();
		expect(screen.queryByText("Clean Band")).not.toBeInTheDocument();
		// The after date is 2010-05-24; the source's 1989 must not stand in for it.
		expect(screen.getByText(/\b2010\b/)).toBeInTheDocument();
		expect(screen.queryByText(/\b1989\b/)).not.toBeInTheDocument();
	});

	it("shows each genre as a chip, in the preview's order", async () => {
		renderWithProviders(<AlbumHeader view={view()} />);

		const genres = await screen.findByRole("list", { name: "Genres" });
		// Declared rock then britpop: sorting would swap them.
		expect(
			within(genres)
				.getAllByRole("listitem")
				.map((chip) => chip.textContent?.trim()),
		).toEqual(["rock", "britpop"]);
	});

	it("shows the cover from the view's cover URL, named after the album", async () => {
		renderWithProviders(<AlbumHeader view={view()} />);

		const cover = await screen.findByRole("img", { name: "Clean Album cover" });
		expect(cover).toHaveAttribute("src", "/api/drops/x/albums/01/cover");
	});

	it("shows a placeholder and requests no image when the album has no cover", async () => {
		renderWithProviders(<AlbumHeader view={view({ cover: null })} />);

		await screen.findByRole("heading", { level: 1, name: "Clean Album" });
		// Any <img> with a src, even an unnamed one, asks the server for a cover it does not have.
		expect(document.querySelector("img[src]")).toBeNull();
	});

	it("keeps the source's tags one click away and hides them again", async () => {
		const user = userEvent.setup();
		renderWithProviders(<AlbumHeader view={view()} />);

		expect(
			screen.queryByRole("region", { name: "Original tags" }),
		).not.toBeInTheDocument();

		await user.click(
			await screen.findByRole("button", { name: "Show original tags" }),
		);

		const original = screen.getByRole("region", { name: "Original tags" });
		expect(
			within(original).getByText("Clean Album (2009 rip)"),
		).toBeInTheDocument();
		expect(within(original).getByText(/\b1989\b/)).toBeInTheDocument();
		// The heading still carries the after title while the before one shows.
		expect(
			screen.getByRole("heading", { level: 1, name: "Clean Album" }),
		).toBeInTheDocument();

		await user.click(
			screen.getByRole("button", { name: "Hide original tags" }),
		);

		expect(
			screen.queryByRole("region", { name: "Original tags" }),
		).not.toBeInTheDocument();
		expect(
			screen.getByRole("button", { name: "Show original tags" }),
		).toBeInTheDocument();
	});

	it("reads the album-wide tags by the files' family", async () => {
		const user = userEvent.setup();
		renderWithProviders(<AlbumHeader view={flacView()} />);

		expect(
			await screen.findByRole("heading", { level: 1, name: "Ecliptica" }),
		).toBeInTheDocument();
		expect(screen.getByText("Sonata Arctica")).toBeInTheDocument();
		expect(screen.getByText(/\b1999\b/)).toBeInTheDocument();
		expect(
			within(screen.getByRole("list", { name: "Genres" }))
				.getAllByRole("listitem")
				.map((chip) => chip.textContent?.trim()),
		).toEqual(["power metal"]);
		expect(
			screen.getByRole("img", { name: "Ecliptica cover" }),
		).toBeInTheDocument();

		await user.click(
			screen.getByRole("button", { name: "Show original tags" }),
		);
		expect(
			within(screen.getByRole("region", { name: "Original tags" })).getByText(
				"ecliptica",
			),
		).toBeInTheDocument();
	});

	it("gives every button an accessible name", async () => {
		renderWithProviders(<AlbumHeader view={view()} />);

		const buttons = await screen.findAllByRole("button");
		for (const button of buttons) {
			expect(button).toHaveAccessibleName();
		}
	});
});
