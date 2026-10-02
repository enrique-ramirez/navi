import type { AlbumView } from "@/shared/api/types";

/** A match replaces the library's album, so there is no second copy to choose between. */
export const hasKeepChoice = (view: AlbumView) =>
	view.duplicate !== null && !view.replaces;
