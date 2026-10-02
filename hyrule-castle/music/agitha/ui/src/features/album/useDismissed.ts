import type { AlbumView } from "@/shared/api/types";
import { notify, useAlbumStore } from "./pending";

/**
 * Keys dismissed on one preview, kept with the album's draft so they outlast
 * the page; a new digest starts over.
 */
export function useDismissed(view: AlbumView) {
	const store = useAlbumStore(view);
	const digest = view.preview?.plan_digest ?? null;
	const keys = store.dismissed.digest === digest ? store.dismissed.keys : [];
	return {
		has: (key: string) => keys.includes(key),
		dismiss: (key: string) => {
			store.dismissed = { digest, keys: [...keys, key] };
			notify(store);
		},
	};
}
