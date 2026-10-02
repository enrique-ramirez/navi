import { BYTES, bytesOf, type Locked } from "@/shared/ui/tagRow";

export { bytesOf, type Locked };

/** Keys of embedded pictures, which show in the cover card rather than as rows. */
export const PICTURE = /^(APIC|covr|METADATA_BLOCK_PICTURE|WM\/Picture)/;

// The tags the owner cannot change: the six MusicBrainz IDs (they come from the release),
// ratings (the library's rule), binary frames, and ADDED, which the import stamps.
export function lockedKind(key: string, values: string[]): Locked | null {
	const compact = key.toLowerCase().replace(/[^a-z0-9]/g, "");
	if (
		compact.includes("musicbrainz") &&
		(compact.endsWith("id") || key.startsWith("UFID:"))
	)
		return "id";
	if (key.startsWith("POPM") || compact.includes("rating")) return "rating";
	if (/(^|:)added$/i.test(key)) return "added";
	if (
		PICTURE.test(key) ||
		/^(GEOB|PRIV)/.test(key) ||
		values.some((value) => BYTES.test(value))
	)
		return "binary";
	return null;
}
