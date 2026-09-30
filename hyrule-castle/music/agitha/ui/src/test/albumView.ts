import type {
	AlbumView,
	Candidate,
	FileFacts,
	PlanEntry,
} from "@/shared/api/types";
import autoClean from "@/test/fixtures/auto-clean/plan.json";

export const DROP = "20260929-210000";
export const ALBUM_URL = `/api/drops/${DROP}/albums/01`;

export function albumView(over: Partial<AlbumView> = {}): AlbumView {
	const preview = structuredClone(autoClean.albums[0]) as PlanEntry;
	return {
		drop: DROP,
		n: "01",
		name: "Clean Album",
		state: "ready",
		stderr: "",
		error: null,
		step: null,
		file: null,
		busy: false,
		preview,
		files: preview.files.map((file) => facts(file.position)),
		uploaded: [],
		names: {
			id3: {
				TIT2: "Title",
				TALB: "Album",
				TPE1: "Artist",
				TPE2: "Album artist",
				TRCK: "Track number",
				TPOS: "Disc number",
				TDRC: "Date",
				TCON: "Genre",
			},
			vorbis: {},
			mp4: {},
			asf: {},
		},
		library_path: "/srv/music/library/C/Clean Band/(2010) Clean Album",
		tree: [],
		extras_to: [],
		decision: null,
		cover: null,
		cover_now: null,
		duplicate: null,
		approvable: { ok: true, reason: null, code: null, hold: null },
		...over,
	};
}

export function facts(
	position: string,
	over: Partial<FileFacts> = {},
): FileFacts {
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
		size: 8_000_000,
		audio_url: `${ALBUM_URL}/audio/${position}.mp3`,
		...over,
	};
}

export function candidate(over: Partial<Candidate> = {}): Candidate {
	return {
		release_id: "6f1a2b3c-0000-4000-8000-000100000001",
		title: "Clean Album",
		artist: "Clean Band",
		date: "2010-05-24",
		country: "GB",
		format: "CD",
		track_counts: [3],
		matches_counts: true,
		duration_diff: 0.5,
		checked: true,
		artist_agrees: true,
		failing_tracks: 0,
		status: "Official",
		thumbnail: "https://coverartarchive.org/release/x/front-250",
		...over,
	};
}
