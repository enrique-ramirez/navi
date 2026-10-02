import type { AlbumView, Edits, Family } from "@/shared/api/types";
import { albumArtistKeyOf, familyOf, genreKeyOf } from "./albumTags";

export const GENRE = "genre";
export const ALBUM_ARTIST = "albumartist";

// Genres and the album artist are edited under the neutral names `genre` and
// `albumartist`, whatever the family calls them: the engine moves the artist's
// folder for the neutral name only. A neutral map takes each file key to its name.
export type Neutral = Record<string, string>;

export const neutralFor = (family: Family): Neutral => ({
	[genreKeyOf(family)]: GENRE,
	[albumArtistKeyOf(family)]: ALBUM_ARTIST,
});

function ownAlbumArtistKey(view: AlbumView, position: string): string {
	const file = view.preview?.files.find((each) => each.position === position);
	return file ? albumArtistKeyOf(familyOf(view, file)) : ALBUM_ARTIST;
}

// The album artist is set under the neutral name alone: a raw key beside it is laid after it and used as
// typed. Setting it takes the position's own key out of the edits, absent and not `null`. A removal goes
// under the own key alone: a neutral field with no value stops identify.
export function withEdit(
	edits: Edits,
	view: AlbumView,
	positions: string[],
	key: string,
	values: string[] | null,
): Edits {
	const next: Edits = { ...edits };
	for (const position of positions) {
		if (key !== ALBUM_ARTIST) {
			next[position] = { ...next[position], [key]: values };
			continue;
		}
		const own = ownAlbumArtistKey(view, position);
		const {
			[ALBUM_ARTIST]: _neutral,
			[own]: _own,
			...rest
		} = next[position] ?? {};
		next[position] =
			values === null
				? { ...rest, [own]: null }
				: { ...rest, [ALBUM_ARTIST]: values };
	}
	return next;
}

export function withoutEdit(
	edits: Edits,
	view: AlbumView,
	positions: string[],
	key: string,
): Edits {
	const next: Edits = { ...edits };
	for (const position of positions) {
		const { [key]: _gone, ...left } = next[position] ?? {};
		const own = ownAlbumArtistKey(view, position);
		const rest =
			key === ALBUM_ARTIST
				? Object.fromEntries(Object.entries(left).filter(([k]) => k !== own))
				: left;
		if (Object.keys(rest).length > 0) next[position] = rest;
		else delete next[position];
	}
	return next;
}
