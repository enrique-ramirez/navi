/** Where the address points: each segment is there only if the address goes that deep. */
export interface Place {
	letter?: string;
	artist?: string;
	album?: string;
}

/** The folders the tree has open. */
export interface Shown {
	letter?: string;
	artist?: string;
}

/**
 * The folders the tree opens for an address. It follows the address, but only
 * to a folder that has answered: until then it keeps what it showed.
 */
export function shownFor(
	url: Place,
	shown: Shown,
	pending: { letter: boolean; artist: boolean },
): Shown {
	const letter =
		url.letter === undefined || !pending.letter ? url.letter : shown.letter;
	if (url.artist === undefined) return { letter };
	if (letter === url.letter && !pending.artist)
		return { letter, artist: url.artist };
	return { letter, artist: letter === shown.letter ? shown.artist : undefined };
}

/** Whether `path` is the deepest place the address names. */
export function isHere(url: Place, ...path: string[]) {
	const here = [url.letter, url.artist, url.album].filter(
		(part) => part !== undefined,
	);
	return path.length === here.length && path.every((p, i) => p === here[i]);
}
