import type { Candidate, FailingTrack } from "@/shared/api/types";

export type Level = "strong" | "possible" | "weak" | "unchecked";

const CLOSE_LENGTH_SECONDS = 15;

export function levelOf(candidate: Candidate): Level {
	// A plan written before `checked` existed shows an unchecked release as one with no title.
	if (candidate.checked === false || candidate.title === null)
		return "unchecked";
	if (!candidate.matches_counts) return "weak";
	const lengthFits =
		candidate.duration_diff !== null &&
		Math.abs(candidate.duration_diff) <= CLOSE_LENGTH_SECONDS;
	const tracksFit = (candidate.failing_tracks ?? 0) === 0;
	return lengthFits && tracksFit && candidate.artist_agrees !== false
		? "strong"
		: "possible";
}

const ORDER: Record<Level, number> = {
	strong: 0,
	possible: 1,
	weak: 2,
	unchecked: 3,
};

// Ties keep musiclib's ranking, which is the order the list arrives in.
export function byLevel(candidates: Candidate[]): Candidate[] {
	return candidates
		.map((candidate, rank) => ({ candidate, rank }))
		.sort(
			(a, b) =>
				ORDER[levelOf(a.candidate)] - ORDER[levelOf(b.candidate)] ||
				a.rank - b.rank,
		)
		.map(({ candidate }) => candidate);
}

export const trackTotal = (candidate: Candidate) =>
	candidate.track_counts.every((count) => count !== null)
		? candidate.track_counts.reduce<number>(
				(sum, count) => sum + (count ?? 0),
				0,
			)
		: null;

export const releaseUrl = (releaseId: string) =>
	`https://musicbrainz.org/release/${releaseId}`;

/** The track a failing file is, as the track list numbers it: `09`, or `2-09` on an album of several discs. */
export function failingNumber(position: string, multiDisc: boolean) {
	const [disc = "", track = ""] = position.split("-");
	return multiDisc ? `${disc}-${track}` : track;
}

/** The lengths of a failing track where they are what is off: more than a second apart. */
export const lengthsApart = (track: FailingTrack) =>
	track.wants !== null && Math.abs(track.length - track.wants) > 1;
