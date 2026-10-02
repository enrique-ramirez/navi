import { getJson } from "./getJson";
import type {
	CoverUpload,
	Draft,
	GenreList,
	LibraryAlbum,
	LibraryArtist,
	LibraryJob,
	LibraryLetter,
	LibraryOrder,
	LibraryPreview,
	LibraryRoot,
	MatchRef,
	SaveAccepted,
} from "./types";

const segment = encodeURIComponent;

export const fetchLibraryRoot = () => getJson<LibraryRoot>("/api/library");

export const fetchLibraryLetter = (letter: string) =>
	getJson<LibraryLetter>(`/api/library/${segment(letter)}`);

export const fetchLibraryArtist = (letter: string, artist: string) =>
	getJson<LibraryArtist>(`/api/library/${segment(letter)}/${segment(artist)}`);

export const fetchLibraryAlbum = (
	letter: string,
	artist: string,
	album: string,
) =>
	getJson<LibraryAlbum>(
		`/api/library/${segment(letter)}/${segment(artist)}/${segment(album)}`,
	);

export const fetchLibraryOrder = (
	letter: string,
	artist: string,
	album: string,
) =>
	getJson<LibraryOrder>(
		`/api/library/${segment(letter)}/${segment(artist)}/${segment(album)}/order`,
	);

export const fetchGenres = () => getJson<GenreList>("/api/genres");

/** A route's refusal: its status and the sentence it served, `null` where it served none. */
export class Refused extends Error {
	constructor(
		readonly status: number,
		readonly sentence: string | null,
	) {
		super(sentence ?? String(status));
	}
}

/** A 404 here means the server knows no such job, which `Refused` carries for the page to tell from a failed ask. */
export async function fetchLibraryJob(id: string): Promise<LibraryJob> {
	const response = await fetch(`/api/library/jobs/${segment(id)}`);
	if (!response.ok) throw new Refused(response.status, null);
	return response.json();
}

async function postJson<Body>(url: string, body: unknown): Promise<Body> {
	const response = await fetch(url, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify(body),
	});
	const answer = await response.json().catch(() => null);
	if (!response.ok) throw new Refused(response.status, answer?.error ?? null);
	return answer as Body;
}

export const postPreview = (draft: Draft) =>
	postJson<LibraryPreview>("/api/library/preview", draft);

export const postSave = (draft: Draft) =>
	postJson<SaveAccepted>("/api/library/save", draft);

/** The image itself is the body; the server names the refusal of a non-image or a wrong type. */
export async function putLibraryCover(file: File): Promise<CoverUpload> {
	const response = await fetch("/api/library/covers", {
		method: "PUT",
		headers: { "Content-Type": file.type },
		body: file,
	});
	const answer = await response.json().catch(() => null);
	if (!response.ok) throw new Refused(response.status, answer?.error ?? null);
	return answer as CoverUpload;
}

/** The drop album a library album is matched in: a new one, or the one already open. */
export const postMatch = (path: string) =>
	postJson<MatchRef>("/api/library/match", { path });
