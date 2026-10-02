/** Where the address points: each segment is there only if the address goes that deep. */
export interface Place {
	letter?: string;
	artist?: string;
	album?: string;
}

const partsOf = (place: Place) =>
	[place.letter, place.artist, place.album].filter(
		(part) => part !== undefined,
	);

/** The place as a library-relative path, empty for the library itself. */
export const pathOf = (place: Place) => partsOf(place).join("/");

/** The folders that must be open for the place to show in the tree: its letter and its artist. */
export function ancestorsOf(place: Place): string[] {
	if (place.letter === undefined) return [];
	if (place.artist === undefined) return [place.letter];
	return [place.letter, `${place.letter}/${place.artist}`];
}

/** Whether `path` is the deepest place the address names. */
export function isHere(url: Place, ...path: string[]) {
	const here = partsOf(url);
	return path.length === here.length && path.every((p, i) => p === here[i]);
}
