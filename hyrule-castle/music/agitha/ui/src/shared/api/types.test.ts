import { describe, expect, expectTypeOf, it } from "vitest";

import autoClean from "@/test/fixtures/auto-clean/plan.json";
import decisions from "@/test/fixtures/decision-hold/decisions.json";
import decisionHold from "@/test/fixtures/decision-hold/plan.json";
import libraryAlbum from "@/test/fixtures/library/album.json";
import libraryArtist from "@/test/fixtures/library/artist.json";
import coverUpload from "@/test/fixtures/library/cover-upload.json";
import genres from "@/test/fixtures/library/genres.json";
import libraryJob from "@/test/fixtures/library/job.json";
import libraryLetter from "@/test/fixtures/library/letter.json";
import order from "@/test/fixtures/library/order.json";
import orderUnchecked from "@/test/fixtures/library/order-unchecked.json";
import libraryPreview from "@/test/fixtures/library/preview.json";
import libraryRoot from "@/test/fixtures/library/root.json";
import missingDecisions from "@/test/fixtures/missing-track/decisions.json";
import missingTrack from "@/test/fixtures/missing-track/plan.json";
import soundtrackChoice from "@/test/fixtures/soundtrack-choice/plan.json";
import strayImageDecisions from "@/test/fixtures/stray-images/decisions.json";
import strayImages from "@/test/fixtures/stray-images/plan.json";

import type {
	AlbumJob,
	AlbumSummary,
	AlbumView,
	CoverCheck,
	CoverUpload,
	DecisionsDoc,
	Draft,
	DraftEdit,
	DraftTrack,
	Family,
	GenreList,
	JobAlbum,
	JobState,
	LibraryAlbum,
	LibraryAlbumSummary,
	LibraryArtist,
	LibraryCover,
	LibraryJob,
	LibraryLetter,
	LibraryOrder,
	LibraryPreview,
	LibraryRoot,
	LibraryTrack,
	MatchRef,
	MatchRequest,
	OrderFlag,
	PlanDoc,
	PreviewAlbum,
	PreviewProblem,
	PreviewTrack,
	RefusedKey,
	SaveAccepted,
	StrayWhy,
	Suggestion,
	TagChange,
	TagNames,
	TrackRef,
	UploadedFile,
} from "./types";

// A JSON import types every string as `string` and every boolean as `boolean`,
// so the literal types of the contract are widened before the comparison.
type Loosen<T> = T extends string
	? string
	: T extends boolean
		? boolean
		: T extends readonly (infer U)[]
			? Loosen<U>[]
			: T extends object
				? { [K in keyof T]: Loosen<T[K]> }
				: T;

// A key of a union that some member has.
type KeyOf<T> = T extends unknown ? keyof T : never;
type ValueAt<T, K extends PropertyKey> = T extends unknown
	? K extends keyof T
		? T[K]
		: never
	: never;

// `satisfies` ignores keys the contract lacks, so a field the engine adds would
// pass unseen. Any key of the fixture that the contract does not name becomes
// `never` here, and the assignment below fails on it.
type NoExtra<Actual, Declared> = Actual extends readonly (infer A)[]
	? Extract<Declared, readonly unknown[]> extends readonly (infer D)[]
		? NoExtra<A, D>[]
		: never
	: Actual extends object
		? {
				[K in keyof Actual]: K extends KeyOf<Extract<Declared, object>>
					? NoExtra<Actual[K], ValueAt<Extract<Declared, object>, K>>
					: never;
			}
		: Actual;

// The library fixtures are written by hand to be the whole answer, so a key the
// contract marks optional and the fixture leaves out is an error too: every key
// is made required before the comparison.
type Whole<T> = T extends readonly (infer U)[]
	? Whole<U>[]
	: T extends object
		? { [K in keyof T]-?: Whole<T[K]> }
		: T;
type Answer<T> = Whole<Loosen<T>>;

// Where the objects of one JSON array differ in their keys, as the tags of an
// MP3 and of a FLAC do, TypeScript gives each object the others' keys as
// `key?: undefined`. JSON has no `undefined`, so those keys are dropped again.
type Json<T> = T extends readonly (infer U)[]
	? Json<U>[]
	: T extends object
		? { [K in keyof T as [T[K]] extends [undefined] ? never : K]: Json<T[K]> }
		: T;

// The same type with every interface and intersection spelled out as one
// object, so `expectTypeOf` compares what a type holds and never how it was
// declared: `A & { b }` and an interface that extends `A` come out equal.
type Plain<T> = T extends object ? { [K in keyof T]: Plain<T[K]> } : T;

type Plan = Loosen<PlanDoc>;

const plans = {
	autoClean: autoClean satisfies Plan,
	decisionHold: decisionHold satisfies Plan,
	soundtrackChoice: soundtrackChoice satisfies Plan,
	missingTrack: missingTrack satisfies Plan,
	strayImages: strayImages satisfies Plan,
};

const noExtraAutoClean: NoExtra<typeof autoClean, Plan> = autoClean;
const noExtraDecisionHold: NoExtra<typeof decisionHold, Plan> = decisionHold;
const noExtraSoundtrackChoice: NoExtra<typeof soundtrackChoice, Plan> =
	soundtrackChoice;
const noExtraMissingTrack: NoExtra<typeof missingTrack, Plan> = missingTrack;
const noExtraStrayImages: NoExtra<typeof strayImages, Plan> = strayImages;

const decisionsDoc = decisions satisfies Loosen<DecisionsDoc>;
const noExtraDecisions: NoExtra<
	typeof decisions,
	Loosen<DecisionsDoc>
> = decisions;
const missingDecisionsDoc = missingDecisions satisfies Loosen<DecisionsDoc>;
const noExtraMissingDecisions: NoExtra<
	typeof missingDecisions,
	Loosen<DecisionsDoc>
> = missingDecisions;
const strayImageDecisionsDoc =
	strayImageDecisions satisfies Loosen<DecisionsDoc>;
const noExtraStrayImageDecisions: NoExtra<
	typeof strayImageDecisions,
	Loosen<DecisionsDoc>
> = strayImageDecisions;

const root: Answer<LibraryRoot> = libraryRoot as Json<typeof libraryRoot>;
const noExtraRoot: NoExtra<
	Json<typeof libraryRoot>,
	Answer<LibraryRoot>
> = libraryRoot;
const letter: Answer<LibraryLetter> = libraryLetter as Json<
	typeof libraryLetter
>;
const noExtraLetter: NoExtra<
	Json<typeof libraryLetter>,
	Answer<LibraryLetter>
> = libraryLetter;
const artist: Answer<LibraryArtist> = libraryArtist as Json<
	typeof libraryArtist
>;
const noExtraArtist: NoExtra<
	Json<typeof libraryArtist>,
	Answer<LibraryArtist>
> = libraryArtist;
const album: Answer<LibraryAlbum> = libraryAlbum as Json<typeof libraryAlbum>;
const noExtraAlbum: NoExtra<
	Json<typeof libraryAlbum>,
	Answer<LibraryAlbum>
> = libraryAlbum;
const checkedOrder: Answer<LibraryOrder> = order as Json<typeof order>;
const noExtraCheckedOrder: NoExtra<
	Json<typeof order>,
	Answer<LibraryOrder>
> = order;
const uncheckedOrder: Answer<LibraryOrder> = orderUnchecked as Json<
	typeof orderUnchecked
>;
const noExtraUncheckedOrder: NoExtra<
	Json<typeof orderUnchecked>,
	Answer<LibraryOrder>
> = orderUnchecked;
const preview: Answer<LibraryPreview> = libraryPreview as Json<
	typeof libraryPreview
>;
const noExtraPreview: NoExtra<
	Json<typeof libraryPreview>,
	Answer<LibraryPreview>
> = libraryPreview;
const job: Answer<LibraryJob> = libraryJob as Json<typeof libraryJob>;
const noExtraJob: NoExtra<
	Json<typeof libraryJob>,
	Answer<LibraryJob>
> = libraryJob;
const upload: Answer<CoverUpload> = coverUpload as Json<typeof coverUpload>;
const noExtraUpload: NoExtra<
	Json<typeof coverUpload>,
	Answer<CoverUpload>
> = coverUpload;
const genreList: Answer<GenreList> = genres as Json<typeof genres>;
const noExtraGenreList: NoExtra<
	Json<typeof genres>,
	Answer<GenreList>
> = genres;

// `urllib.parse.quote(segment, safe="")`, which is how the server quotes a path
// segment: `encodeURIComponent` leaves these five characters alone.
function quoted(segment: string): string {
	return encodeURIComponent(segment).replace(
		/[!'()*]/g,
		(char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`,
	);
}

// Every case below is decided by `pnpm typecheck`, never by Vitest, which
// strips the types before it runs: `expectTypeOf` does nothing at run time.
describe("the library's API types", () => {
	it("gives a track everything an uploaded file has, and what a save sends back", () => {
		expectTypeOf<Plain<LibraryTrack>>().toExtend<UploadedFile>();
		expectTypeOf<Plain<DraftTrack["loaded"]>>().toEqualTypeOf<
			Plain<LibraryTrack["loaded"]>
		>();
	});

	// The server sends every key of an answer every time, so a key marked
	// optional would make the page handle an absence that never comes.
	it("marks no key of an answer optional", () => {
		expectTypeOf<Plain<LibraryRoot>>().toEqualTypeOf<
			Plain<Whole<LibraryRoot>>
		>();
		expectTypeOf<Plain<LibraryLetter>>().toEqualTypeOf<
			Plain<Whole<LibraryLetter>>
		>();
		expectTypeOf<Plain<LibraryArtist>>().toEqualTypeOf<
			Plain<Whole<LibraryArtist>>
		>();
		expectTypeOf<Plain<LibraryAlbum>>().toEqualTypeOf<
			Plain<Whole<LibraryAlbum>>
		>();
		expectTypeOf<Plain<LibraryOrder>>().toEqualTypeOf<
			Plain<Whole<LibraryOrder>>
		>();
		expectTypeOf<Plain<LibraryPreview>>().toEqualTypeOf<
			Plain<Whole<LibraryPreview>>
		>();
		expectTypeOf<Plain<LibraryJob>>().toEqualTypeOf<Plain<Whole<LibraryJob>>>();
		expectTypeOf<Plain<CoverUpload>>().toEqualTypeOf<
			Plain<Whole<CoverUpload>>
		>();
		expectTypeOf<Plain<GenreList>>().toEqualTypeOf<Plain<Whole<GenreList>>>();
	});

	it("lists an artist's albums and an album's tracks under the names the contract gives them", () => {
		expectTypeOf<Plain<LibraryArtist["albums"]>>().toEqualTypeOf<
			Plain<LibraryAlbumSummary[]>
		>();
		expectTypeOf<Plain<LibraryAlbumSummary["tracks"]>>().toEqualTypeOf<
			Plain<LibraryTrack[]>
		>();
		expectTypeOf<Plain<LibraryAlbum["tracks"]>>().toEqualTypeOf<
			Plain<LibraryTrack[]>
		>();
	});

	// The shape is spelled out here once: were `TagNames` only compared with the
	// fields that use it, a wrong `TagNames` would agree with all three.
	it("serves one map of readable tag names, under one name, to the review, the album and the artist", () => {
		expectTypeOf<Plain<TagNames>>().toEqualTypeOf<
			Plain<Record<Family, Record<string, string>>>
		>();
		expectTypeOf<Plain<AlbumView["names"]>>().toEqualTypeOf<Plain<TagNames>>();
		expectTypeOf<Plain<LibraryAlbum["names"]>>().toEqualTypeOf<
			Plain<TagNames>
		>();
		expectTypeOf<Plain<LibraryArtist["names"]>>().toEqualTypeOf<
			Plain<TagNames>
		>();
	});

	// A fixture holds one of the two, so the other is only checked here.
	it("lets an album have no cover, no match, no job and no release, a summary no cover address, and a cover no problem", () => {
		expectTypeOf<Plain<LibraryAlbum["cover"]>>().toEqualTypeOf<
			Plain<LibraryCover | null>
		>();
		expectTypeOf<Plain<LibraryCover>>().toEqualTypeOf<
			Plain<{
				url: string;
				width: number;
				height: number;
				passes: boolean;
				problem: string | null;
			}>
		>();
		expectTypeOf<Plain<LibraryAlbum["match"]>>().toEqualTypeOf<
			Plain<MatchRef | null>
		>();
		expectTypeOf<Plain<LibraryAlbumSummary["cover_url"]>>().toEqualTypeOf<
			Plain<string | null>
		>();
		expectTypeOf<Plain<LibraryAlbumSummary["match"]>>().toEqualTypeOf<
			Plain<MatchRef | null>
		>();
		expectTypeOf<Plain<MatchRef>>().toEqualTypeOf<
			Plain<{ drop: string; n: string }>
		>();
		expectTypeOf<Plain<LibraryAlbum["job"]>>().toEqualTypeOf<
			Plain<AlbumJob | null>
		>();
		expectTypeOf<Plain<AlbumJob>>().toEqualTypeOf<
			Plain<{ id: string; state: JobState }>
		>();
		expectTypeOf<Plain<LibraryAlbum["release_id"]>>().toEqualTypeOf<
			Plain<string | null>
		>();
		expectTypeOf<Plain<CoverUpload>>().toEqualTypeOf<
			Plain<CoverCheck & { cover: string }>
		>();
	});

	it("narrows an order answer on `checked` to its flags, or to a reason and whether to retry", () => {
		expectTypeOf<
			Plain<Extract<LibraryOrder, { checked: true }>>
		>().toEqualTypeOf<
			Plain<{
				checked: true;
				flags: OrderFlag[];
			}>
		>();
		expectTypeOf<
			Plain<Extract<LibraryOrder, { checked: false }>>
		>().toEqualTypeOf<
			Plain<{
				checked: false;
				reason: string;
				retry: boolean;
			}>
		>();
		expectTypeOf<Plain<OrderFlag>>().toEqualTypeOf<
			Plain<{
				a: string;
				b: string;
				a_runs: number;
				a_wants: number;
				b_runs: number;
				b_wants: number;
			}>
		>();
	});

	// One draft holds several edits, each to its own tracks, so the title of
	// track 3 and the title of track 5 travel together. Every member is there in
	// a batch too, empty or `null` where unused. `seen` is what the page loaded
	// for each key an edit names, which is how the server tells a file the owner
	// has not seen from one only re-rated. `batch` says which page sent it: the
	// server skips and refuses as a batch by the flag, not by counting albums.
	it("sends a draft as a list of edits, each naming its tracks, with swaps, a cover token, whether it is a batch, and for each track what was loaded and what was seen", () => {
		expectTypeOf<Plain<Draft>>().toEqualTypeOf<
			Plain<{
				tracks: DraftTrack[];
				edits: DraftEdit[];
				swaps: [string, string][];
				cover: string | null;
				batch: boolean;
			}>
		>();
		// A tag edit outside `edits` would reach every track of the draft.
		expectTypeOf<Extract<keyof Draft, "set" | "add" | "remove">>().toBeNever();
		expectTypeOf<Plain<DraftEdit>>().toEqualTypeOf<
			Plain<{
				tracks: TrackRef[];
				set: Record<string, string[] | null>;
				add: Record<string, string[]>;
				remove: Record<string, string[]>;
			}>
		>();
		expectTypeOf<Plain<TrackRef>>().toEqualTypeOf<
			Plain<{ album: string; path: string }>
		>();
		expectTypeOf<Plain<DraftTrack>>().toEqualTypeOf<
			Plain<{
				album: string;
				path: string;
				loaded: { size: number; mtime: number };
				seen: Record<string, string[] | null>;
			}>
		>();
	});

	it("names the answer of a save and the request of a match", () => {
		expectTypeOf<Plain<SaveAccepted>>().toEqualTypeOf<Plain<{ job: string }>>();
		expectTypeOf<Plain<MatchRequest>>().toEqualTypeOf<
			Plain<{ path: string }>
		>();
	});

	it("previews a tag that is absent on either side, a cover only where the draft has one, and a skip only where there is a reason", () => {
		expectTypeOf<Plain<LibraryPreview["albums"]>>().toEqualTypeOf<
			Plain<PreviewAlbum[]>
		>();
		expectTypeOf<Plain<PreviewAlbum["tracks"]>>().toEqualTypeOf<
			Plain<PreviewTrack[]>
		>();
		expectTypeOf<Plain<PreviewTrack["changes"]>>().toEqualTypeOf<
			Plain<TagChange[]>
		>();
		expectTypeOf<Plain<TagChange>>().toEqualTypeOf<
			Plain<{
				key: string;
				before: string[] | null;
				after: string[] | null;
			}>
		>();
		expectTypeOf<Plain<PreviewAlbum["cover"]>>().toEqualTypeOf<
			Plain<CoverCheck | null>
		>();
		expectTypeOf<Plain<PreviewAlbum["problems"]>>().toEqualTypeOf<
			Plain<PreviewProblem[]>
		>();
		expectTypeOf<Plain<PreviewProblem>>().toEqualTypeOf<
			Plain<{
				rule: string;
				detail: string;
			}>
		>();
		expectTypeOf<Plain<PreviewAlbum["refused"]>>().toEqualTypeOf<
			Plain<RefusedKey[]>
		>();
		expectTypeOf<Plain<RefusedKey>>().toEqualTypeOf<
			Plain<{ key: string; reason: string }>
		>();
		expectTypeOf<Plain<PreviewAlbum["skip"]>>().toEqualTypeOf<
			Plain<string | null>
		>();
	});

	it("moves an album of a job through five states, with an error only once it failed", () => {
		expectTypeOf<Plain<JobState>>().toEqualTypeOf<
			Plain<"waiting" | "writing" | "verifying" | "done" | "failed">
		>();
		expectTypeOf<Plain<LibraryJob["albums"]>>().toEqualTypeOf<
			Plain<JobAlbum[]>
		>();
		expectTypeOf<Plain<JobAlbum>>().toEqualTypeOf<
			Plain<{
				path: string;
				new_path: string;
				state: JobState;
				error: string | null;
			}>
		>();
	});

	it("adds the library album a match replaces to the review and to the drops listing, and suggestions to the review", () => {
		expectTypeOf<Plain<AlbumSummary["replaces"]>>().toEqualTypeOf<
			Plain<string | null>
		>();
		expectTypeOf<Plain<AlbumView["replaces"]>>().toEqualTypeOf<
			Plain<string | null>
		>();
		expectTypeOf<Plain<AlbumView["suggestions"]>>().toEqualTypeOf<
			Plain<Suggestion[]>
		>();
	});

	it("narrows a suggestion on `kind` to a genre, a soundtrack genre or a spelling", () => {
		expectTypeOf<Plain<Suggestion["kind"]>>().toEqualTypeOf<
			Plain<"genre" | "soundtrack" | "spelling">
		>();
		expectTypeOf<Plain<Extract<Suggestion, { kind: "genre" }>>>().toEqualTypeOf<
			Plain<{
				kind: "genre";
				genre: string;
				albums: number;
				of: number;
				artist: string;
			}>
		>();
		expectTypeOf<
			Plain<Extract<Suggestion, { kind: "soundtrack" }>>
		>().toEqualTypeOf<
			Plain<{
				kind: "soundtrack";
				genre: "soundtrack" | "video game music";
				albums: number;
				of: number;
				artist: string;
			}>
		>();
		expectTypeOf<
			Plain<Extract<Suggestion, { kind: "spelling" }>>
		>().toEqualTypeOf<
			Plain<{
				kind: "spelling";
				artist: string;
				lands_in: string;
				folders: { path: string; name: string }[];
			}>
		>();
	});
});

// The fixtures are written by hand and read by the page's tests and the
// server's. These cases hold them to one library, so an edit to one file that
// the others contradict fails here and not in a test that only borrowed it.
describe("the library fixtures", () => {
	it("show one album the same from its artist, its letter and the root", () => {
		const [letterName, artistName] = album.path.split("/");
		expect(root.letters).toContain(letterName);
		expect(letter.artists).toContainEqual({ name: artistName });
		const summary = artist.albums.find((entry) => entry.path === album.path);
		expect(summary?.tracks).toEqual(album.tracks);
		expect(summary?.name).toBe(album.path.split("/")[2]);
		expect(noExtraArtist.albums).toHaveLength(2);
		// The artist's panel names a tag as the album's does.
		expect(artist.names).toEqual(album.names);
		expect(noExtraAlbum.cover?.url).toBe(summary?.cover_url);
		expect([noExtraRoot.root, noExtraLetter.artists.length]).toEqual([
			"/srv/music/library",
			3,
		]);
	});

	it("address each track's audio under its album, every path segment quoted", () => {
		const urls = artist.albums.flatMap((entry) =>
			entry.tracks.map((track) => [
				track.audio_url,
				`/api/library/${[...entry.path.split("/"), "audio", ...track.path.split("/")].map(quoted).join("/")}`,
			]),
		);
		expect(urls).toHaveLength(8);
		for (const [served, expected] of urls) {
			expect(served).toBe(expected);
		}
	});

	it("mark read-only on a track only keys its own tags have, and load it at a fraction of a second", () => {
		const tracks = artist.albums.flatMap((entry) => entry.tracks);
		for (const track of tracks) {
			expect(Object.keys(track.tags)).toEqual(
				expect.arrayContaining(track.readonly),
			);
		}
		// A whole second would have hidden a `loaded.mtime` that loses its fraction.
		expect(
			tracks.filter((track) => !Number.isInteger(track.loaded.mtime)),
		).toHaveLength(7);
		// A track with none would pass the loop above with nothing compared.
		expect(tracks.filter((track) => track.readonly.length === 0)).toEqual([]);
		expect(tracks).toHaveLength(8);
	});

	it("name only tracks and albums of that library in the order answers, the preview and the job", () => {
		const paths = album.tracks.map((track) => track.path);
		expect(checkedOrder.flags.flatMap((flag) => [flag.a, flag.b])).toEqual([
			"03. 8th Commandment.mp3",
			"04. Replica.mp3",
		]);
		expect(paths).toEqual(
			expect.arrayContaining(
				noExtraCheckedOrder.flags.flatMap((flag) => [flag.a, flag.b]),
			),
		);
		expect([uncheckedOrder.checked, noExtraUncheckedOrder.retry]).toEqual([
			false,
			false,
		]);
		expect(preview.albums.map((entry) => entry.path)).toEqual([album.path]);
		expect(
			noExtraPreview.albums.flatMap((entry) =>
				entry.tracks.map((track) => track.path),
			),
		).toEqual(paths);
		expect(job.albums.map((entry) => entry.path)).toEqual(
			expect.arrayContaining(artist.albums.map((entry) => entry.path)),
		);
		// One album in each state, and an error on the failed one alone.
		expect(noExtraJob.albums.map((entry) => entry.state).sort()).toEqual([
			"done",
			"failed",
			"verifying",
			"waiting",
			"writing",
		]);
		expect(
			job.albums.filter((entry) => entry.error !== null).map((e) => e.state),
		).toEqual(["failed"]);
	});

	it("list the genres sorted, the two custom genres among them, and an upload that passes with no problem", () => {
		expect(genreList.genres).toEqual([...genreList.genres].sort());
		expect(noExtraGenreList.genres).toEqual(
			expect.arrayContaining(["soundtrack", "video game music"]),
		);
		expect([upload.passes, noExtraUpload.problem]).toEqual([true, null]);
	});
});

describe("the API types against the engine's fixtures", () => {
	it("holds one album in each plan, and the decision keyed by its source", () => {
		expect(Object.values(plans).map((plan) => plan.albums.length)).toEqual([
			1, 1, 1, 1, 1,
		]);
		expect([
			noExtraAutoClean,
			noExtraDecisionHold,
			noExtraSoundtrackChoice,
			noExtraMissingTrack,
			noExtraStrayImages,
		]).toHaveLength(5);
		expect(Object.keys(decisionsDoc.albums)).toEqual([
			decisionHold.albums[0]?.source,
		]);
		expect(noExtraDecisions.job).toBe(decisionHold.job);
		expect(Object.keys(missingDecisionsDoc.albums)).toEqual([
			missingTrack.albums[0]?.source,
		]);
		expect(noExtraMissingDecisions.job).toBe(missingTrack.job);
		expect(Object.keys(strayImageDecisionsDoc.albums)).toEqual([
			strayImages.albums[0]?.source,
		]);
		expect(noExtraStrayImageDecisions.job).toBe(strayImages.job);
	});

	// The generated fixture is only a check of the contract where the engine
	// really wrote each answer: a reason it stops producing leaves `StrayWhy`
	// unchecked against it.
	it("carries every reason the engine gives a stray, from a real identify", () => {
		const reasons: StrayWhy[] = [
			"guessed",
			"copy",
			"lost",
			"won",
			"owner",
			"no guess",
		];
		expect(
			new Set(strayImages.albums[0]?.strays.map((stray) => stray.why)),
		).toEqual(new Set(reasons));
		expect(Object.values(noExtraStrayImageDecisions.albums)[0]?.strays).toEqual(
			{ "COVERS/IMG_0002.jpg": "booklet-01.jpg" },
		);
	});

	it("holds the album with an unreadable track on a missing hold that names it, from a real identify", () => {
		expect(
			missingTrack.albums[0]?.holds.filter((hold) => hold.kind === "missing"),
		).toEqual([
			{
				kind: "missing",
				detail: 'track 2, "Two": 02 two.mp3 could be it, but it cannot be read',
			},
		]);
	});
});
