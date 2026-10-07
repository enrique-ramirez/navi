// The JSON the server sends and the page sends back. Python builds its answers
// from these names. `PlanEntry` mirrors one album of the engine's `plan.json`,
// and `types.test.ts` checks it against the fixtures under tests/fixtures/agitha.

/** Family -> raw key -> readable name; a key not listed shows as itself. */
export type TagNames = Record<Family, Record<string, string>>;

/** A tag family, as `mapping.py` names them. */
export type Family = "id3" | "vorbis" | "mp4" | "asf";

/** The soundtrack choice. */
export type GameChoice = "video game music" | "soundtrack" | "neither";

/** How sure the identifier is; `error` is an album the engine crashed on. */
export type PlanStatus =
	| "certain"
	| "auto"
	| "review"
	| "unidentified"
	| "error";

/** `held` waits on a hold, `auto` has changes and none, `unchanged` has neither. */
export type PlanState = "held" | "auto" | "unchanged";

/**
 * What a hold is about. Approve is stopped by `decision`, `error` and
 * `collision`; the rest inform.
 */
export type HoldKind =
	| "decision"
	| "error"
	| "collision"
	| "validation"
	| "status"
	| "missing"
	| "repointed"
	| "reopened";

export interface Hold {
	kind: HoldKind;
	/** A sentence for the owner; empty for `decision` and `reopened`. */
	detail: string;
}

/**
 * Tag key -> values, keys of the file's own family (`TIT2`, `TXXX:MOOD`,
 * `title`, `©wrt`). A binary frame shows as text (`APIC:... (N bytes)`, or a
 * Python `repr(...)`), never as bytes, so every value is a string.
 */
export type TagMap = Record<string, string[]>;

export interface Candidate {
	release_id: string;
	title: string;
	artist: string;
	date: string;
	country: string;
	format: string;
	/** Tracks per medium; an entry is `null` where MusicBrainz gave no count. */
	track_counts: (number | null)[];
	/** Whether the release's track counts equal the folder's. */
	matches_counts: boolean;
	/** Seconds by which the release's length differs from the folder's; `null` where the track counts do not match. */
	duration_diff: number | null;
	/** Whether musiclib fetched the release; `false` where the search listed too few tracks, and the rest is the search's. */
	checked: boolean;
	artist_agrees: boolean;
	/** Tracks whose title or length does not fit the release; `null` where the counts do not match. */
	failing_tracks: number | null;
	/** Each of those tracks with what to compare; absent from a preview made before the engine listed them. */
	failing?: FailingTrack[] | null;
	/** MusicBrainz release status (`Official`, `Promotion`, `Bootleg`...), `null` where unknown. */
	status: string | null;
	/** Cover Art Archive URL, 250 px. */
	thumbnail: string;
}

/** A file that does not fit its track of a release, and the two things that decide it. */
export interface FailingTrack {
	/** `<medium>-<position>`, as a planned file is named. */
	position: string;
	/** The track's title on MusicBrainz, and the file's own. */
	title: string;
	file_title: string;
	title_agrees: boolean;
	/** Seconds: the file's, and MusicBrainz's, `null` for a track nobody has timed. */
	length: number;
	wants: number | null;
}

export interface PlanFile {
	/** Where the file is now, relative to the job's root. */
	source: string;
	/** Where it will be, relative to the library root. */
	destination: string;
	/** `<disc>-<track>`, the key of `fields` and of an accept's `edits`. */
	position: string;
	before: TagMap;
	after: TagMap;
}

/** One value (`value`), or one whole tag (`value: null`), the engine removes. */
export interface Residue {
	file: string;
	key: string;
	value: string | null;
	/** The engine rule that removed it, shown as the reason. */
	rule: string;
}

export interface ImageDigest {
	length: number;
	sha256: string;
}

/** What plan.json's `inputs` records so `apply` rebuilds the same plan. */
export interface PlanInputs {
	release_id: string;
	chosen: boolean;
	status: PlanStatus;
	owner_input: { soundtracks: Record<string, GameChoice> };
	/** The accept's edits, as laid. */
	edits: Edits;
	edition?: string;
	original?: { folder: string; found: boolean };
	created?: string[];
	/** The owner cover, relative to the job, and its SHA-256. */
	owner_cover?: { path: string; sha256: string };
	/** False when identify ran with `--no-composer`; absent in a plan written before the key existed. */
	composer?: boolean;
	/** The owner's stray answers (path -> name, `null` deletes) and each kept stray's SHA-256; absent with neither. */
	strays?: {
		answers: Record<string, string | null>;
		sha256: Record<string, string>;
	};
	/** When agitha started the job, `YYYY-MM-DDTHH:MM`; absent where it passed no `--added`. */
	added?: string;
}

export type StrayKind = "image" | "pdf" | "text";

/** `copy`, `lost` and `won` name the other file in `against`. */
export type StrayWhy =
	| "guessed"
	| "copy"
	| "lost"
	| "won"
	| "owner"
	| "no guess";

/** What becomes of a stray: kept under a name, deleted, or `null` for undecided. */
export type StrayAnswer = { keep: string } | { delete: true } | null;

/** A file outside the tracks and the cover that identify found in the album folder. */
export interface Stray {
	/** Relative to the album folder. */
	path: string;
	kind: StrayKind;
	answer: StrayAnswer;
	why: StrayWhy;
	/** The other file where `why` is `copy`, `lost` or `won`, else `null`. */
	against: string | null;
	/** `[width, height]`; `null` where it is not an image or cannot be read. */
	size: [number, number] | null;
}

/** One album of a `plan.json`, the preview. */
export interface PlanEntry {
	/** The album folder relative to the job's root, `drop/album/<name>`. */
	source: string;
	status: PlanStatus;
	state: PlanState;
	holds: Hold[];
	/** The decision this entry was planned under, or `null` when there was none. */
	decision: "accept" | "repoint" | "skip" | null;
	release_id: string | null;
	/** Relative to the library root; `null` when nothing could be planned. */
	destination: string | null;
	/** Whether the soundtrack choice is on offer. */
	game_choice: boolean;
	/** The choice made; `not game music` is the earlier spelling of `soundtrack`. */
	game: GameChoice | "not game music" | null;
	candidates: Candidate[];
	files: PlanFile[];
	/** Position -> neutral (Picard-named) field -> values, as they will be written. */
	fields: Record<string, Record<string, string[]>>;
	/** Images to write, by file name. */
	images: Record<string, ImageDigest>;
	residue: Residue[];
	/** Album-relative paths deleted. */
	deletions: string[];
	/** Paths that go to /srv/music/extras. */
	extras: string[];
	/** Paths that stay in the album folder as they are. */
	kept: string[];
	/** Files the engine settled or left undecided; absent from a plan written before strays were planned. */
	strays?: Stray[];
	/** One line per change apply will make. */
	changes: string[];
	/** Position -> neutral or raw key -> values (`null` removes the tag). */
	owner_edits: Edits;
	/** `null` on an album with no plan. */
	inputs: PlanInputs | null;
	plan_digest: string | null;
}

/** `plan.json`. */
export interface PlanDoc {
	job: string;
	/** The absolute inbox folder the plan is rooted at, `/srv/music/inbox/<drop>/<n>`. */
	root: string;
	/** Absent when the job has no `decisions.json`. */
	decisions_sha256?: string | null;
	albums: PlanEntry[];
}

/**
 * Position -> tag -> values. A key is a neutral field name (`genre`) or a raw
 * key of the file's family (`TXXX:MOOD`); `null` removes the tag.
 */
export type Edits = Record<string, Record<string, string[] | null>>;

export interface AcceptDecision {
	action: "accept";
	release_id: string;
	edits: Edits;
	game: GameChoice | null;
	/** The owner cover, relative to the job (`owner/cover.<ext>`), or `null`; the key may be absent. */
	cover?: string | null;
	/** Stray path -> the name to keep it under, or `null` to delete it; a path left out keeps agitha's answer, and the key may be absent. */
	strays?: Record<string, string | null>;
}

export interface RepointDecision {
	action: "repoint";
	/** A MusicBrainz release URL or MBID. */
	release: string;
}

export type Decision = AcceptDecision | RepointDecision;

/** `decisions.json`; the key of `albums` is the entry's `source`. */
export interface DecisionsDoc {
	job: string;
	albums: Record<string, Decision>;
}

export type DropState = "uploading" | "incomplete" | "extracting" | "ready";

export type AlbumState =
	| "queued"
	| "identifying"
	| "ready"
	| "identify failed"
	| "identify interrupted"
	| "applying"
	| "written, not moved"
	| "in the library"
	| "apply failed"
	| "incomplete"
	/** The answer of a discard, or of Keep the one in the library, after which the album is gone; never listed. */
	| "discarded";

/** What the list offers for an album or drop; the server derives it from state and `busy`. */
export type AlbumAction =
	| "discard"
	| "retry"
	| "reidentify"
	| "move"
	| "approve";

/** `file` is a loose non-audio file at the top level of a drop; the page lists it as ignored and does not send it, the server accepts it. */
export type ItemKind = "folder" | "archive" | "file";

export interface DropFile {
	/** Path inside the item, `/`-separated. */
	path: string;
	size: number;
}

export interface DropItem {
	name: string;
	kind: ItemKind;
	files: DropFile[];
}

/** An item or file left out of every album, and why. */
export interface Ignored {
	item: string;
	path: string;
	/** `no audio files` for an item with none; otherwise a short reason. */
	reason: string;
}

/** An archive the server refused; its files were not kept. */
export interface Refused {
	item: string;
	reason: string;
	/** The entry that caused it, where there is one. */
	entry: string | null;
}

export interface AlbumSummary {
	/** `01`, `02`, ... within the drop. */
	n: string;
	/** The staged folder's name. */
	name: string;
	state: AlbumState;
	/** From the preview; `null` until identify has written one. */
	title: string | null;
	artist: string | null;
	year: string | null;
	/** Relative to the library root; `null` until planned. */
	destination: string | null;
	/** The `n` of another album of this drop planning the same destination. */
	duplicate_of: string | null;
	/** The last 20 lines of the failed musiclib run; empty when none failed. */
	stderr: string;
	/** A sentence for the owner, or `null`. */
	error: string | null;
	/** Whether a musiclib process is queued or running for it (no Discard). */
	busy: boolean;
	/** Retry and Discard after a failed identify, Move and Discard once written, Approve where `approvable.ok`; none while busy or in the library. */
	actions: AlbumAction[];
	/** The library album this one is a match for, relative to the library root; `null` where it is not a match. */
	replaces: string | null;
}

export interface Drop {
	/** `YYYYMMDD-HHMMSS`, with `-2`, `-3` where taken. */
	id: string;
	state: DropState;
	/** ISO 8601 start time. */
	started: string;
	/** What was dropped, as the page sent it. */
	items: DropItem[];
	ignored: Ignored[];
	refused: Refused[];
	albums: AlbumSummary[];
	/** A sentence when extraction or staging failed and the drop reads `incomplete` (recorded in `drop.json`); `null` otherwise. */
	error: string | null;
	/** `["discard"]`, or `[]` while a musiclib process runs for one of its albums. */
	actions: AlbumAction[];
	/** Files and bytes received so far, while `uploading`. */
	received: { files: number; bytes: number };
}

/** `GET /api/drops` answers `Drop[]`. */
export type DropList = Drop[];

export interface CreateDropRequest {
	items: DropItem[];
}

export interface CreateDropResponse {
	drop: string;
}

/**
 * A 4xx body. `free` and `needed` (bytes) come with the refusal for too
 * little disk space and are absent otherwise.
 */
export interface ErrorBody {
	error: string;
	free?: number;
	needed?: number;
}

export interface FileFacts {
	position: string;
	/** Album-relative source path as dropped. */
	path_now: string;
	/** Path inside the library once the album lands. */
	path_after: string;
	/** `FLAC`, `MP3`, `MP4`, `Ogg Vorbis`, `WMA`. */
	format: string;
	family: Family;
	lossless: boolean;
	/** Bits per second. */
	bitrate: number;
	/** Hz. */
	sample_rate: number;
	/** `null` for a lossy format. */
	bit_depth: number | null;
	channels: number;
	/** Seconds. */
	length: number;
	/** Bytes. */
	size: number;
	/** `/api/drops/<drop>/albums/<n>/audio/<path>`. */
	audio_url: string;
}

/** One track of the album folder as uploaded, whatever the plan made of it. */
export interface UploadedFile {
	/** Album-relative path as uploaded, `/`-separated. */
	path: string;
	family: Family;
	/** The file's tags now, raw keys of its family, binary frames as text like `before`. */
	tags: TagMap;
	/** `FLAC`, `MP3`, `MP4`, `Ogg Vorbis`, `WMA`. */
	format: string;
	/** FLAC, or ALAC in MP4. */
	lossless: boolean;
	/** Bits per second. */
	bitrate: number;
	/** Hz. */
	sample_rate: number;
	/** `null` for a lossy format. */
	bit_depth: number | null;
	channels: number;
	/** Seconds. */
	length: number;
	/** Bytes. */
	size: number;
	/** `/api/drops/<drop>/albums/<n>/audio/<path>`. */
	audio_url: string;
}

export interface CoverInfo {
	url: string;
	width: number;
	height: number;
}

/** The result of the cover test (ratio 0.9 to 1.1, shorter side 500 px). */
export interface CoverCheck {
	width: number;
	height: number;
	passes: boolean;
	/** How it fails, one sentence; `null` where it passes. */
	problem: string | null;
}

export interface AlbumCover extends CoverCheck {
	url: string;
}

/** One side of a duplicate comparison. */
export interface Copy {
	/** The folder, absolute. */
	folder: string;
	format: string;
	lossless: boolean;
	bit_depth: number | null;
	sample_rate: number;
	/** Average, bits per second. */
	bitrate: number;
	files: number;
	/** Seconds. */
	length: number;
	/** Bytes. */
	size: number;
	cover: CoverInfo | null;
	/** From `release_id` through `media`: the first track's tags, `date` as written. */
	release_id: string | null;
	album: string | null;
	album_artist: string | null;
	date: string | null;
	label: string | null;
	catalog: string | null;
	country: string | null;
	media: string | null;
	/** Distinct disc numbers the tags give, else disc folders; 1 for a single disc. */
	discs: number;
	/** Lowest file bitrate, bits per second. */
	bitrate_min: number;
	/** Highest file bitrate, bits per second. */
	bitrate_max: number;
	/** What made the files where one says: MP3 LAME header (`LAME 3.99.1+ -b 320`), FLAC/Ogg vendor, MP4 `©too`. */
	encoder: string | null;
	/** Distinct tag keys per file, on average. */
	tag_count: number;
}

/** The two copies' tracks, paired by disc and track number where every file has both, else in path order. */
export interface TrackComparison {
	paired: number;
	/** Pairs whose lengths differ by more than the engine's tolerance. */
	length_differs: number;
	only_new: number;
	only_library: number;
	/** The largest length difference among the pairs, seconds; 0 with none paired. */
	max_length_diff: number;
}

export type CopySide = "new" | "library";

export interface Comparison {
	new: Copy;
	library: Copy;
	recommended: CopySide;
	/** The rule that decided, or `the copy in the library` where none differed. */
	rule: string;
	/** The rule as a code; the page translates from the codes, the sentence is for logs and tests. */
	rule_code:
		| "more-files"
		| "lossless"
		| "bit-depth"
		| "sample-rate"
		| "bitrate"
		| "library";
	tracks: TrackComparison;
}

export interface Approvable {
	ok: boolean;
	/** Names the hold or state that stops it; `null` where `ok`. */
	reason: string | null;
	/** Why not, as a code; the page translates from the codes, the sentence is for logs and tests. `null` where `ok`. */
	code: "not-accepted" | "held" | "in-library" | "busy" | "not-ready" | null;
	/** The blocking hold when `code` is `held`, otherwise `null`. */
	hold: Hold | null;
}

/** An extra file and where it will be in /srv/music/extras. */
export interface ExtraTarget {
	source: string;
	path: string;
}

/** `GET /api/drops/<drop>/albums/<n>`. */
export interface AlbumView {
	drop: string;
	n: string;
	name: string;
	state: AlbumState;
	stderr: string;
	error: string | null;
	/** The failed step, as on `MoveResponse`, kept on the album so a reload shows it. */
	step: 1 | 2 | 3 | 4 | 5 | null;
	/** The file that failed at that step. */
	file: string | null;
	busy: boolean;
	/** `null` until identify has written a plan. */
	preview: PlanEntry | null;
	/** One per track of the preview, in plan order; empty with no preview. */
	files: FileFacts[];
	/** Every track of the album folder as uploaded, in musiclib's order (disc folder, then path); empty once it has left the inbox. */
	uploaded: UploadedFile[];
	/** Family -> raw key -> readable name; a key not listed shows as itself. */
	names: TagNames;
	/** `/srv/music/library/` plus the destination; `null` with no destination. */
	library_path: string | null;
	/** Paths of the album folder as it will land, relative to it, files only. */
	tree: string[];
	extras_to: ExtraTarget[];
	/** The last decision agitha wrote for this album, or `null`. */
	decision: Decision | null;
	/** The cover the plan writes, served at `.../cover`; `null` where it writes none. */
	cover: AlbumCover | null;
	/** The cover the files have now, served at `.../cover/now`: the first track's embedded picture, else the folder's image. */
	cover_now: AlbumCover | null;
	duplicate: Comparison | null;
	approvable: Approvable;
	/** The library album this one is a match for, relative to the library root; `null` where it is not a match. */
	replaces: string | null;
	/** Tags and folders the plan could take from the rest of the library; empty with none. */
	suggestions: Suggestion[];
	/** The copy Keep recorded while `duplicate` is set: `new`, or `null` while the choice is open. */
	keep: CopySide | null;
}

/** An artist's other albums carry one genre, and this album's tags give another or none. */
export interface GenreSuggestion {
	kind: "genre";
	genre: string;
	/** Albums of the artist that carry `genre`. */
	albums: number;
	/** Albums of the artist in the library. */
	of: number;
	artist: string;
}

/** As a genre suggestion, for the two soundtrack genres. */
export interface SoundtrackSuggestion {
	kind: "soundtrack";
	genre: "soundtrack" | "video game music";
	albums: number;
	of: number;
	artist: string;
}

/** The planned artist folder is spelled unlike one the library already has. */
export interface SpellingSuggestion {
	kind: "spelling";
	/** The planned artist name. */
	artist: string;
	/** The planned `Letter/Artist` folder. */
	lands_in: string;
	/** Existing `Letter/Artist` folders it may be meant for. */
	folders: { path: string; name: string }[];
}

export type Suggestion =
	| GenreSuggestion
	| SoundtrackSuggestion
	| SpellingSuggestion;

/** `POST .../decision`; the server keys it as `decisions.json` does. */
export type DecisionRequest = Decision;

export interface ApproveRequest {
	/** Required where `duplicate` is set and Keep recorded nothing. */
	keep?: CopySide;
}

/** `POST .../keep`: the copy to keep, or `null` to choose again. Keeping the library's copy goes through approve. */
export interface KeepRequest {
	keep: "new" | null;
}

/** The answer of approve, move and keep-the-new-one. */
export interface MoveResponse {
	state: AlbumState;
	/** The album's path in the library, or its finished folder in the inbox where it did not move. */
	path: string | null;
	error: string | null;
	/** The step of the move, 1 to 5, that failed (1 is recording the checksums). */
	step: 1 | 2 | 3 | 4 | 5 | null;
	/** The file that failed at that step. */
	file: string | null;
}

export type ApproveResponse = MoveResponse;

/**
 * `PUT .../cover` answers the cover test of what was sent, and `path`, the
 * job-relative path it was stored under (`owner/cover-<sha8>.<ext>`), which the
 * decision then names in `cover`.
 */
export type CoverUploadResponse = CoverCheck & { path: string };

/** `GET /api/library`. */
export interface LibraryRoot {
	root: string;
	/** Whether the library root could be listed. */
	readable: boolean;
	letters: string[];
}

/** `GET /api/library/<letter>`. */
export interface LibraryLetter {
	artists: LibraryFolder[];
}

export interface LibraryFolder {
	name: string;
	empty: boolean;
}

/** `DELETE /api/library/<letter>/<artist>[/<album>]`: every folder removed, relative to the library root. */
export interface FolderRemoved {
	removed: string[];
}

/** `GET /api/library/<letter>/<artist>`. */
export interface LibraryArtist {
	albums: LibraryAlbumSummary[];
	/** As on `AlbumView`. */
	names: TagNames;
}

/** An album of an artist's page; every track comes with it, so the page can edit the artist at once. */
export interface LibraryAlbumSummary {
	/** Relative to the library root, `/`-separated: `S/Sonata Arctica/(1999) Ecliptica`. */
	path: string;
	/** The album folder's name. */
	name: string;
	empty: boolean;
	year: string;
	title: string;
	/** `.../cover`; `null` with no cover. */
	cover_url: string | null;
	match: MatchRef | null;
	tracks: LibraryTrack[];
}

/** A track of an album in the library. */
export interface LibraryTrack extends UploadedFile {
	/** What the file was when the page read it, sent back with a save to detect a change since. */
	loaded: {
		/** Bytes. */
		size: number;
		/** `st_mtime`: seconds, a float. */
		mtime: number;
	};
	disc: number;
	number: number;
	/** Raw keys of the file's family that may not be edited. */
	readonly: string[];
}

/** `GET /api/library/<letter>/<artist>/<album>`. */
export interface LibraryAlbum {
	/** Relative to the library root, `/`-separated. */
	path: string;
	release_id: string | null;
	cover: LibraryCover | null;
	tracks: LibraryTrack[];
	/** Album-relative paths of files that would not open. */
	unreadable: string[];
	/** Family -> raw key -> readable name, as on `AlbumView`. */
	names: TagNames;
	/** The drop album that is a match for this one; `null` where there is none. */
	match: MatchRef | null;
	/** The save running or last run on this album; `null` where none. */
	job: AlbumJob | null;
}

/** The cover of a library album, served at `.../cover`. */
export interface LibraryCover extends CoverCheck {
	url: string;
}

/** The drop album that is a match for a library album. */
export interface MatchRef {
	drop: string;
	n: string;
}

/** `GET .../order`: two tracks whose lengths fit each other's place in the release, or why it was not checked. */
export type LibraryOrder =
	| { checked: true; flags: OrderFlag[] }
	| {
			checked: false;
			/** The sentence to show. */
			reason: string;
			/** Whether asking again may help: only where MusicBrainz did not answer. */
			retry: boolean;
	  };

/** Two tracks that are probably in each other's place. `a` and `b` are album-relative paths; the numbers are seconds. */
export interface OrderFlag {
	a: string;
	b: string;
	/** How long `a` runs. */
	a_runs: number;
	/** How long the release says the track in `a`'s place runs. */
	a_wants: number;
	b_runs: number;
	b_wants: number;
}

/** `PUT /api/library/covers`. */
export interface CoverUpload extends CoverCheck {
	/** Names the stored image in a `Draft`. */
	cover: string;
}

/** `POST /api/library/preview` and `/save`; every member is sent, empty or `null` where unused. */
export interface Draft {
	/** Every track an edit, a swap or the cover touches, once each. */
	tracks: DraftTrack[];
	/** Applied in order. */
	edits: DraftEdit[];
	/** Pairs of track paths that trade places; only with one album. */
	swaps: [string, string][];
	/** A `CoverUpload.cover` token; only with one album. */
	cover: string | null;
	/** The artist page sends `true`, the album page `false`: the server skips and refuses as a batch by this flag, not by counting albums. */
	batch: boolean;
}

/** One change to the tags of the tracks it names. */
export interface DraftEdit {
	/** Each must be in `Draft.tracks`. */
	tracks: TrackRef[];
	/** Tag -> the values it ends with, or `null` to remove it. A tag is named as `names` reads it, else by its raw key. */
	set: Record<string, string[] | null>;
	/** Tag -> values appended where the track lacks them. */
	add: Record<string, string[]>;
	/** Tag -> values taken from the tracks that carry them. */
	remove: Record<string, string[]>;
}

export interface TrackRef {
	/** Library-relative album path. */
	album: string;
	/** Album-relative track path. */
	path: string;
}

export interface DraftTrack {
	/** Library-relative album path. */
	album: string;
	/** Album-relative track path. */
	path: string;
	loaded: LibraryTrack["loaded"];
	/** For each key the draft names, the values the page showed; `null` where the track had none. Tells a changed file from one only re-rated. */
	seen: Record<string, string[] | null>;
}

/** The answer of `POST /api/library/preview`. */
export interface LibraryPreview {
	albums: PreviewAlbum[];
}

export interface PreviewAlbum {
	path: string;
	/** Equals `path` where nothing moves. */
	new_path: string;
	/** Only the tracks that change. */
	tracks: PreviewTrack[];
	/** `null` for a draft with no new cover. */
	cover: CoverCheck | null;
	problems: PreviewProblem[];
	/** Tags the draft names that may not be edited. */
	refused: RefusedKey[];
	/** Why the album is left out of a batch; `null` where it is saved. */
	skip: string | null;
}

export interface PreviewTrack {
	path: string;
	/** Equals `path` where nothing moves. */
	new_path: string;
	changes: TagChange[];
}

/** `key` is the readable name where there is one, else the raw key. */
export interface TagChange {
	key: string;
	/** `null` for a tag that is absent. */
	before: string[] | null;
	after: string[] | null;
}

export interface PreviewProblem {
	rule: string;
	/** A path where the rule is about one; `detail` of a collision is the path taken. */
	detail: string;
}

/** A tag key the draft names and the album refuses to change. */
export interface RefusedKey {
	key: string;
	reason: string;
}

/** `202` of `POST /api/library/save`: the id to poll at `/api/library/jobs/<id>`. */
export interface SaveAccepted {
	job: string;
}

/** `GET /api/library/jobs/<id>`. */
export interface LibraryJob {
	albums: JobAlbum[];
}

export type JobState = "waiting" | "writing" | "verifying" | "done" | "failed";

export interface JobAlbum {
	path: string;
	new_path: string;
	state: JobState;
	/** A sentence where `state` is `failed`; `null` otherwise. */
	error: string | null;
}

/** An album's job as `LibraryAlbum` carries it. */
export interface AlbumJob {
	id: string;
	state: JobState;
}

/** `POST /api/library/delete`. */
export interface AlbumDeleted {
	deleted: string;
	/** Why its extras could not be deleted, where they could not; `null` otherwise. */
	note: string | null;
}

/** `POST /api/library/match`. */
export interface MatchRequest {
	/** Library-relative album path. */
	path: string;
}

/** `GET /api/genres`. */
export interface GenreList {
	genres: string[];
}

/** An artist as MusicBrainz's search lists one; the last three are empty where it says nothing. */
export interface FoundArtist {
	id: string;
	name: string;
	disambiguation: string;
	type: string;
	country: string;
}

export interface ArtistList {
	/** False where MusicBrainz did not answer, and the list is empty for that alone. */
	answered: boolean;
	artists: FoundArtist[];
}
