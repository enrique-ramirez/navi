import type {
	Draft,
	GenreList,
	JobAlbum,
	JobState,
	LibraryAlbum,
	LibraryArtist,
	LibraryJob,
	LibraryLetter,
	LibraryPreview,
	LibraryRoot,
	LibraryTrack,
	PreviewAlbum,
	TrackRef,
} from "@/shared/api/types";
import albumFixture from "@/test/fixtures/library/album.json";
import artistFixture from "@/test/fixtures/library/artist.json";
import genresFixture from "@/test/fixtures/library/genres.json";
import jobFixture from "@/test/fixtures/library/job.json";
import letterFixture from "@/test/fixtures/library/letter.json";
import previewFixture from "@/test/fixtures/library/preview.json";
import rootFixture from "@/test/fixtures/library/root.json";

import type { Call } from "./fakeFetch";

type Respond = () => Response | Promise<Response>;

/** The body a folder answers with, or a function for an answer that fails or waits. */
type Answer<T> = T | Respond;

/**
 * What the faked library holds. `letters` is keyed by letter, `artists` by
 * `Letter/Artist` and `albums` by `Letter/Artist/Album`, each as the folder is
 * named on disk. A folder nobody listed answers 404.
 */
export interface Shelves {
	root?: Answer<LibraryRoot>;
	letters?: Record<string, Answer<LibraryLetter>>;
	artists?: Record<string, Answer<LibraryArtist>>;
	albums?: Record<string, Answer<LibraryAlbum>>;
}

export const SONATA = "S/Sonata Arctica";
export const ECLIPTICA = `${SONATA}/(1999) Ecliptica`;

// A JSON import types `family` as `string` and a tag one track lacks as
// `undefined`; `types.test.ts` is where the fixtures are held to the types.
export const fixtures = {
	root: rootFixture as LibraryRoot,
	letter: letterFixture as LibraryLetter,
	artist: artistFixture as unknown as LibraryArtist,
	album: albumFixture as unknown as LibraryAlbum,
	genres: genresFixture as GenreList,
	preview: previewFixture as LibraryPreview,
	job: jobFixture as LibraryJob,
};

/** A library track with the album it is in, which is how the tag panel takes its tracks. */
export type TrackOfAlbum = LibraryTrack & { album: string };

/** The tracks of the album fixture for the panel. A fresh copy on every call, so a case may change them. */
export function albumTracks(album: LibraryAlbum = fixtures.album) {
	return structuredClone(album.tracks).map(
		(track): TrackOfAlbum => ({ ...track, album: album.path }),
	);
}

/** Every track of every album of the artist fixture for the panel, a fresh copy on every call. */
export function artistTracks(artist: LibraryArtist = fixtures.artist) {
	return artist.albums.flatMap((album) =>
		structuredClone(album.tracks).map(
			(track): TrackOfAlbum => ({ ...track, album: album.path }),
		),
	);
}

/** What a selection or an edit names of each track. */
export function refsOf(tracks: TrackOfAlbum[]): TrackRef[] {
	return tracks.map(({ album, path }) => ({ album, path }));
}

/**
 * `fakeFetch` handlers for the library's reading routes. With no argument they
 * serve the fixtures: the root, the letter `S`, Sonata Arctica and Ecliptica.
 * Folders passed in are added to those; a key already there is replaced.
 */
export function libraryHandlers(shelves: Shelves = {}) {
	const root = shelves.root ?? fixtures.root;
	const letters: Shelves["letters"] = {
		S: fixtures.letter,
		...shelves.letters,
	};
	const artists: Shelves["artists"] = {
		[SONATA]: fixtures.artist,
		...shelves.artists,
	};
	const albums: Shelves["albums"] = {
		[ECLIPTICA]: fixtures.album,
		...shelves.albums,
	};

	return {
		"GET /api/library": () => respond(root),
		"GET /api/library/:letter": (req: Request) => respond(letters[folder(req)]),
		"GET /api/library/:letter/:artist": (req: Request) =>
			respond(artists[folder(req)]),
		"GET /api/library/:letter/:artist/:album": (req: Request) =>
			respond(albums[folder(req)]),
	};
}

/** The id the faked save answers with; the job route answers for this id and no other. */
export const JOB = "20261002-021700-a1";

/** What the faked library answers to the routes an edit goes through. */
export interface Writes {
	genres?: Answer<GenreList>;
	/** With none, `preview.json`. */
	preview?: Answer<LibraryPreview>;
	/** With none, `202` and the id `JOB`. */
	save?: Respond;
	/** The job `JOB` as its route answers it; with none, 404. */
	job?: Answer<LibraryJob>;
}

/**
 * `fakeFetch` handlers for the genre list, the preview, the save and its job.
 * Spread them before `libraryHandlers`: the first route that fits answers, and
 * `/api/library/jobs/<id>` also fits a letter and an artist.
 */
export function editingHandlers(writes: Writes = {}) {
	return {
		"GET /api/genres": () => respond(writes.genres ?? fixtures.genres),
		"POST /api/library/preview": () =>
			respond(writes.preview ?? fixtures.preview),
		"POST /api/library/save": () =>
			writes.save
				? writes.save()
				: Response.json({ job: JOB }, { status: 202 }),
		"GET /api/library/jobs/:id": (req: Request) =>
			respond(
				new URL(req.url).pathname.endsWith(`/${JOB}`) ? writes.job : undefined,
			),
	};
}

/** A refusal as every route of the server answers one. */
export function refusal(status: number, error: string): Respond {
	return () => Response.json({ error }, { status });
}

/** The preview fixture's album with some of it replaced. A fresh copy on every call. */
export function previewOf(over: Partial<PreviewAlbum> = {}): LibraryPreview {
	const [album] = structuredClone(fixtures.preview.albums);
	return { albums: [{ ...album!, ...over }] };
}

/** A job of one album: Ecliptica, staying where it is, unless `over` says otherwise. */
export function jobOf(
	state: JobState,
	over: Partial<JobAlbum> = {},
): LibraryJob {
	return {
		albums: [
			{ path: ECLIPTICA, new_path: ECLIPTICA, state, error: null, ...over },
		],
	};
}

/** The bodies posted to a route, parsed, in the order they went. */
export function posted<Body = Draft>(calls: Call[], path: string): Body[] {
	return calls
		.filter(
			(call) => call.method === "POST" && new URL(call.url).pathname === path,
		)
		.map((call) => JSON.parse(call.body) as Body);
}

/** An answer that waits until `release` is called, for a folder that is still loading. */
export function held<T>(body: T) {
	let release = () => {};
	const gate = new Promise<void>((resolve) => {
		release = resolve;
	});
	return {
		answer: async () => {
			await gate;
			return Response.json(body);
		},
		release,
	};
}

/** The page's address of a place in the library, as a browser's address bar holds it. */
export function libraryAddress(...segments: string[]) {
	return ["/library", ...segments.map(encodeURIComponent)].join("/");
}

/** The paths the page requested, as they went over the wire. */
export function requested(calls: Call[]) {
	return calls.map((call) => `${call.method} ${new URL(call.url).pathname}`);
}

// The folder a request names, decoded, so `(1999)` and `%281999%29` are one folder.
function folder(req: Request) {
	return new URL(req.url).pathname
		.split("/")
		.slice(3)
		.map(decodeURIComponent)
		.join("/");
}

function respond<T>(answer: Answer<T> | undefined) {
	if (answer === undefined) return new Response(null, { status: 404 });
	if (typeof answer === "function") return (answer as Respond)();
	return Response.json(answer);
}
