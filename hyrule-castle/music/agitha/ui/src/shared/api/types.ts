// The JSON the server sends and the page sends back. Python builds its answers
// from these names. `PlanEntry` mirrors one album of the engine's `plan.json`,
// and `types.test.ts` checks it against the fixtures under tests/fixtures/agitha.

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
	/** Seconds by which the release's length differs from the folder's. */
	duration_diff: number;
	/** Cover Art Archive URL, 250 px. */
	thumbnail: string;
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
export type AlbumAction = "discard" | "retry" | "move" | "approve";

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
	step: 1 | 2 | 3 | 4 | null;
	/** The file that failed at that step. */
	file: string | null;
	busy: boolean;
	/** `null` until identify has written a plan. */
	preview: PlanEntry | null;
	/** One per track of the preview, in plan order; empty with no preview. */
	files: FileFacts[];
	/** Family -> raw key -> readable name; a key not listed shows as itself. */
	names: Record<Family, Record<string, string>>;
	/** `/srv/music/library/` plus the destination; `null` with no destination. */
	library_path: string | null;
	/** Paths of the album folder as it will land, relative to it, files only. */
	tree: string[];
	extras_to: ExtraTarget[];
	/** The last decision agitha wrote for this album, or `null`. */
	decision: Decision | null;
	cover: AlbumCover | null;
	duplicate: Comparison | null;
	approvable: Approvable;
}

/** `POST .../decision`; the server keys it as `decisions.json` does. */
export type DecisionRequest = Decision;

export interface ApproveRequest {
	/** Required where `duplicate` is set. */
	keep?: CopySide;
}

/** The answer of approve, move and keep-the-new-one. */
export interface MoveResponse {
	state: AlbumState;
	/** The album's path in the library, or its finished folder in the inbox where it did not move. */
	path: string | null;
	error: string | null;
	/** The step of criterion 49, 1 to 4, that failed (1 is recording the checksums). */
	step: 1 | 2 | 3 | 4 | null;
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
