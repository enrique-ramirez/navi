import { describe, expect, it } from "vitest";

import type { AlbumView, FileFacts } from "@/shared/api/types";
import { renderWithProviders, screen, within } from "@/test/render";

import { FilePanel } from "./FilePanel";

const flac: FileFacts = {
	position: "1-1",
	path_now: "drop/album/Acoustic Adventures/01 Morning.flac",
	path_after: "A/Aoi Kasa/(2024) Acoustic Adventures/01. Morning.flac",
	format: "FLAC",
	family: "vorbis",
	lossless: true,
	bitrate: 2304000,
	sample_rate: 88200,
	bit_depth: 24,
	channels: 2,
	length: 245.5,
	size: 70_000_000,
	audio_url: "/api/drops/20260929-210000/albums/01/audio/01%20Morning.flac",
};

const mp3: FileFacts = {
	position: "1-2",
	path_now: "drop/album/Acoustic Adventures/02 Noon.mp3",
	path_after: "A/Aoi Kasa/(2024) Acoustic Adventures/02. Noon.mp3",
	format: "MP3",
	family: "id3",
	lossless: false,
	bitrate: 320000,
	sample_rate: 44100,
	bit_depth: null,
	channels: 2,
	length: 61,
	size: 2_430_000,
	audio_url: "/api/drops/20260929-210000/albums/01/audio/02%20Noon.mp3",
};

function albumView(files: FileFacts[]): AlbumView {
	return {
		drop: "20260929-210000",
		n: "01",
		name: "Acoustic Adventures",
		state: "ready",
		stderr: "",
		error: null,
		step: null,
		file: null,
		busy: false,
		preview: null,
		files,
		names: { id3: {}, vorbis: {}, mp4: {}, asf: {} },
		library_path: "/srv/music/library/A/Aoi Kasa/(2024) Acoustic Adventures",
		tree: [],
		extras_to: [],
		decision: null,
		cover: null,
		duplicate: null,
		approvable: { ok: true, reason: null, code: null, hold: null },
	};
}

async function filePanel() {
	return screen.findByRole("region", { name: "File" });
}

// The definition that follows the term named `name`.
function fact(panel: HTMLElement, name: string) {
	const terms = within(panel)
		.getAllByRole("term")
		.filter((term) => term.textContent?.trim() === name);
	expect(terms, `terms named ${name}`).toHaveLength(1);
	const definition = (terms[0] as HTMLElement).nextElementSibling;
	expect(definition?.getAttribute("role") ?? definition?.tagName, name).toMatch(
		/^(definition|DD)$/,
	);
	return definition?.textContent?.trim();
}

describe("the file panel", () => {
	it("shows a FLAC's format, bitrate, length, size and both paths", async () => {
		renderWithProviders(
			<FilePanel view={albumView([flac, mp3])} position="1-1" />,
		);

		const panel = await filePanel();

		expect(fact(panel, "Format")).toBe(
			"FLAC, lossless, 24-bit, 88.2 kHz, 2 channels",
		);
		expect(fact(panel, "Bitrate")).toBe("2304 kbps");
		// 245.5 s: whole seconds, not rounded up to 4:06.
		expect(fact(panel, "Length")).toBe("4:05");
		expect(fact(panel, "Size")).toBe("70.0 MB");
		expect(fact(panel, "Path now")).toBe(flac.path_now);
		expect(fact(panel, "Path after")).toBe(flac.path_after);
	});

	it("shows the file at the selected position, and a lossy one with no bit depth", async () => {
		// The MP3 is second, so a panel that always reads the first file fails here.
		renderWithProviders(
			<FilePanel view={albumView([flac, mp3])} position="1-2" />,
		);

		const panel = await filePanel();

		expect(fact(panel, "Format")).toBe("MP3, lossy, 44.1 kHz, 2 channels");
		expect(fact(panel, "Bitrate")).toBe("320 kbps");
		expect(fact(panel, "Length")).toBe("1:01");
		expect(fact(panel, "Size")).toBe("2.4 MB");
		expect(fact(panel, "Path now")).toBe(mp3.path_now);
		expect(fact(panel, "Path after")).toBe(mp3.path_after);
		expect(panel).not.toHaveTextContent("-bit");
	});
});
