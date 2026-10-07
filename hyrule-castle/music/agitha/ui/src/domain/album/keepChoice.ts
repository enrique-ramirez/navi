import type { AlbumView } from "@/shared/api/types";

/** A match replaces the library's album, so there is no second copy to choose between. */
export const hasKeepChoice = (view: AlbumView) =>
	view.duplicate !== null && !view.replaces;

/** The choice is still open: nothing was kept yet, so Approve waits for it. */
export const awaitsKeepChoice = (view: AlbumView) =>
	hasKeepChoice(view) && view.keep !== "new";
