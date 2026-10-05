import { formatLength } from "@/domain/album/format";
import { lengthsApart } from "@/domain/album/match";
import type { AlbumView, FailingTrack } from "@/shared/api/types";
import type { useTranslate } from "@/shared/i18n/useTranslate";

type Translate = ReturnType<typeof useTranslate>["t"];

/** The files that do not fit the release the preview was planned for, by position. */
export function failingOf(view: AlbumView): Map<string, FailingTrack> {
	const planned = view.preview?.candidates.find(
		(candidate) => candidate.release_id === view.preview?.release_id,
	);
	return new Map(
		(planned?.failing ?? []).map((track) => [track.position, track]),
	);
}

/** Why a file does not fit its track, as the two things a person would compare: the title, the length, or both. */
export function failingWords(track: FailingTrack, t: Translate): string {
	const parts: string[] = [];
	if (!track.title_agrees)
		parts.push(
			t("match.failing.title", { here: track.file_title, there: track.title }),
		);
	if (lengthsApart(track))
		parts.push(
			t("match.failing.length", {
				here: formatLength(track.length),
				there: formatLength(track.wants ?? 0),
			}),
		);
	return parts.join("; ") || t("match.failing.other");
}
