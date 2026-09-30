const BYTES = /\((\d+) bytes\)\s*$/;

/** The byte count a binary frame's value carries, or `undefined`. */
export const bytesOf = (value: string) => BYTES.exec(value)?.[1];

export type Locked = "id" | "rating" | "binary";

// The tags the owner cannot change: the six MusicBrainz IDs (they come from the release),
// ratings (the library's rule) and binary frames.
export function lockedKind(key: string, values: string[]): Locked | null {
	const compact = key.toLowerCase().replace(/[^a-z0-9]/g, "");
	if (
		compact.includes("musicbrainz") &&
		(compact.endsWith("id") || key.startsWith("UFID:"))
	)
		return "id";
	if (key.startsWith("POPM") || compact.includes("rating")) return "rating";
	if (
		/^(APIC|covr|METADATA_BLOCK_PICTURE|WM\/Picture|GEOB|PRIV)/.test(key) ||
		values.some((value) => BYTES.test(value))
	)
		return "binary";
	return null;
}
