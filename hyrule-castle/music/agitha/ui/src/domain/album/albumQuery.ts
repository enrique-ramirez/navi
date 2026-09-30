import { fetchAlbum } from "@/shared/api/album";
import type { AlbumState, AlbumView } from "@/shared/api/types";

const RUNNING: AlbumState[] = ["queued", "identifying", "applying"];

export const isRunning = (state: AlbumState) => RUNNING.includes(state);

export const albumKey = (view: { drop: string; n: string }) => [
	"album",
	view.drop,
	view.n,
];

export function albumQuery(drop: string, n: string) {
	return {
		queryKey: albumKey({ drop, n }),
		queryFn: () => fetchAlbum(drop, n),
		refetchInterval: (query: { state: { data?: AlbumView } }) =>
			query.state.data && isRunning(query.state.data.state) ? 2000 : false,
	};
}
