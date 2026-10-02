import { type PanelTrack, rawKeyOf } from "@/domain/library/shared";
import type { TagNames } from "@/shared/api/types";

export const lastSegment = (path: string) => path.split("/").pop() ?? path;

/** The values a track holds under a tag, named as `names` reads it or by its raw key. */
export function tagOf(track: PanelTrack, key: string, names: TagNames) {
	const raw = rawKeyOf(track, key, names);
	return (raw === null ? undefined : track.tags[raw]) ?? [];
}
