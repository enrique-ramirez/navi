import type { AlbumState } from "@/shared/api/types";
import type { Phrase } from "./en";

// The catalogue phrase for each state an album can show.
export const albumStatePhrase: Record<AlbumState, Phrase> = {
	queued: "state.queued",
	identifying: "state.identifying",
	ready: "state.ready",
	"identify failed": "state.failed",
	"identify interrupted": "state.interrupted",
	applying: "state.applying",
	"written, not moved": "state.writtenNotMoved",
	"in the library": "state.inLibrary",
	"apply failed": "state.applyFailed",
	incomplete: "drop.incomplete",
	discarded: "state.discarded",
};
