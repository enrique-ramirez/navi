import type { AlbumView, Edits, Suggestion } from "@/shared/api/types";

/** A suggestion is the same one wherever it sits in the list: its kind and what it names. */
export const suggestionKey = (suggestion: Suggestion) =>
	suggestion.kind === "spelling"
		? `spelling\u0000${suggestion.folders.map((folder) => folder.path).join("\u0001")}`
		: `${suggestion.kind}\u0000${suggestion.genre}`;

export const suggestionName = (suggestion: Suggestion) =>
	suggestion.kind === "spelling" ? suggestion.artist : suggestion.genre;

/** The genres a track will carry: the owner's edit if there is one, else the plan's. */
export const genresOnTrack = (
	view: AlbumView,
	edits: Edits,
	position: string,
) => edits[position]?.genre ?? view.preview?.fields[position]?.genre ?? [];

/** What Add writes on a track: its genres with this one last, once. */
export const withGenre = (genres: string[], genre: string) => [
	...genres.filter((each) => each !== genre),
	genre,
];

/** Whether every track already carries the suggested genre, so there is nothing to add. */
export function genreIsEverywhere(
	view: AlbumView,
	edits: Edits,
	genre: string,
): boolean {
	const files = view.preview?.files ?? [];
	return (
		files.length > 0 &&
		files.every((file) =>
			genresOnTrack(view, edits, file.position).includes(genre),
		)
	);
}
