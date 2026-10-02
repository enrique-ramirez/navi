import {
	fetchGenres,
	fetchLibraryAlbum,
	fetchLibraryArtist,
	fetchLibraryJob,
	fetchLibraryLetter,
	fetchLibraryOrder,
	fetchLibraryRoot,
	Refused,
} from "@/shared/api/library";
import type { JobState, LibraryJob } from "@/shared/api/types";

// The artist route reads every track's tags and the tree asks it on each album page, so a listing is
// kept for a while and not asked again on focus. Each flow that changes the library invalidates what it changed.
const kept = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export const libraryRootQuery = () => ({
	queryKey: ["library"],
	queryFn: fetchLibraryRoot,
	...kept,
});

// An absent segment gives a query that never runs, so a caller can ask
// for the folder of a place that has not got that deep.
export const libraryLetterQuery = (letter: string | undefined) => ({
	queryKey: ["library", letter],
	queryFn: () => fetchLibraryLetter(letter ?? ""),
	enabled: letter !== undefined,
	...kept,
});

export const libraryArtistQuery = (
	letter: string | undefined,
	artist: string | undefined,
) => ({
	queryKey: ["library", letter, artist],
	queryFn: () => fetchLibraryArtist(letter ?? "", artist ?? ""),
	enabled: letter !== undefined && artist !== undefined,
	...kept,
});

export const libraryAlbumKey = (
	letter: string,
	artist: string,
	album: string,
) => ["library", letter, artist, album];

export const libraryAlbumQuery = (
	letter: string,
	artist: string,
	album: string,
) => ({
	queryKey: libraryAlbumKey(letter, artist, album),
	queryFn: () => fetchLibraryAlbum(letter, artist, album),
	...kept,
});

/** The track-order check, asked only once the album has answered: the page does not wait on it. */
export const libraryOrderQuery = (
	letter: string,
	artist: string,
	album: string,
	albumAnswered: boolean,
) => ({
	queryKey: [...libraryAlbumKey(letter, artist, album), "order"],
	queryFn: () => fetchLibraryOrder(letter, artist, album),
	enabled: albumAnswered,
	retry: false,
});

export const genresQuery = () => ({
	queryKey: ["genres"],
	queryFn: fetchGenres,
	staleTime: Number.POSITIVE_INFINITY,
	refetchOnWindowFocus: false,
});

export type Saving = Exclude<JobState, "done" | "failed">;

export const isSaving = (state: JobState): state is Saving =>
	state !== "done" && state !== "failed";

/** Whether the job route answered that it knows no such job. */
export const isGone = (error: unknown) =>
	error instanceof Refused && error.status === 404;

/**
 * The job of a save, asked again every 2 s until every album it lists is done
 * or has failed, or the server says it knows no such job. The polling is the
 * retry, so a failed ask is not repeated on top of it.
 */
export const libraryJobQuery = (id: string | null) => ({
	queryKey: ["libraryJob", id],
	queryFn: () => fetchLibraryJob(id ?? ""),
	enabled: id !== null,
	retry: false,
	refetchInterval: (query: {
		state: { data?: LibraryJob; error: unknown };
	}) => {
		if (isGone(query.state.error)) return false;
		const albums = query.state.data?.albums ?? [];
		return albums.length === 0 || albums.some((each) => isSaving(each.state))
			? 2000
			: false;
	},
});
