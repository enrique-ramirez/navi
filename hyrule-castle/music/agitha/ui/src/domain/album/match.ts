import type { Candidate } from "@/shared/api/types";

/** How well a candidate fits the folder, from musiclib's own ranking checks. */
export type Level = "strong" | "possible" | "weak" | "unchecked";

// Seconds the release's total length may differ from the folder's and still count as a fit.
const CLOSE_LENGTH = 15;

export function levelOf(candidate: Candidate): Level {
	// A plan written before `checked` existed shows an unchecked release as one with no title.
	if (candidate.checked === false || candidate.title === null)
		return "unchecked";
	if (!candidate.matches_counts) return "weak";
	const lengthFits =
		candidate.duration_diff !== null &&
		Math.abs(candidate.duration_diff) <= CLOSE_LENGTH;
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

/** Best fit first; musiclib's ranking breaks ties, and the list arrives in it. */
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
