import type {
	AlbumView,
	Family,
	FileFacts,
	PlanFile,
	TagMap,
} from "@/shared/api/types";

interface Keys {
	title: string;
	artist: string;
	date: string;
	genre: string;
	track: string;
	trackTitle: string;
}

const KEYS: Record<Family, Keys> = {
	id3: {
		title: "TALB",
		artist: "TPE2",
		date: "TDRC",
		genre: "TCON",
		track: "TRCK",
		trackTitle: "TIT2",
	},
	vorbis: {
		title: "album",
		artist: "albumartist",
		date: "date",
		genre: "genre",
		track: "tracknumber",
		trackTitle: "title",
	},
	mp4: {
		title: "©alb",
		artist: "aART",
		date: "©day",
		genre: "©gen",
		track: "trkn",
		trackTitle: "©nam",
	},
	asf: {
		title: "WM/AlbumTitle",
		artist: "WM/AlbumArtist",
		date: "WM/Year",
		genre: "WM/Genre",
		track: "WM/TrackNumber",
		trackTitle: "Title",
	},
};

const BY_EXTENSION: Record<string, Family> = {
	mp3: "id3",
	flac: "vorbis",
	ogg: "vorbis",
	opus: "vorbis",
	m4a: "mp4",
	mp4: "mp4",
	wma: "asf",
};

export interface AlbumValues {
	title: string;
	artist: string;
	year: string;
	genres: string[];
}

export interface AlbumTags extends AlbumValues {
	before: AlbumValues;
}

export function factsOf(view: AlbumView, position: string) {
	return view.files.find((facts) => facts.position === position);
}

export function familyOf(view: AlbumView, file: PlanFile): Family {
	const facts: FileFacts | undefined = factsOf(view, file.position);
	if (facts) return facts.family;
	const extension = file.source.split(".").pop()?.toLowerCase() ?? "";
	return BY_EXTENSION[extension] ?? "id3";
}

const first = (tags: TagMap, key: string) => tags[key]?.[0] ?? "";

function yearOf(date: string) {
	return /^\d{4}/.exec(date)?.[0] ?? date;
}

function valuesOf(tags: TagMap, keys: Keys): AlbumValues {
	return {
		title: first(tags, keys.title),
		artist: first(tags, keys.artist),
		year: yearOf(first(tags, keys.date)),
		genres: tags[keys.genre] ?? [],
	};
}

export function albumTags(view: AlbumView): AlbumTags {
	const file = view.preview?.files[0];
	if (!file) {
		const none: AlbumValues = { title: "", artist: "", year: "", genres: [] };
		return { ...none, before: none };
	}
	const keys = KEYS[familyOf(view, file)];
	return {
		...valuesOf(file.after, keys),
		before: valuesOf(file.before, keys),
	};
}

export function trackTitle(view: AlbumView, file: PlanFile): string {
	return first(file.after, KEYS[familyOf(view, file)].trackTitle);
}

export const genreKeyOf = (family: Family) => KEYS[family].genre;
