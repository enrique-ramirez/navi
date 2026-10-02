import { Play, Square } from "lucide-react";

import { formatLength, formatValues } from "@/domain/album/format";
import { type PanelTrack, rawKeyOf } from "@/domain/library/shared";
import { mimeOf, usePlayer } from "@/domain/player/usePlayer";
import type { OrderFlag, TagNames } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { RowOrder } from "./TrackOrder";
import styles from "./TrackTable.module.css";

export const lastSegment = (path: string) => path.split("/").pop() ?? path;

export function tagOf(track: PanelTrack, key: string, names: TagNames) {
	const raw = rawKeyOf(track, key, names);
	return (raw === null ? undefined : track.tags[raw]) ?? [];
}

function PlayButton({ track, title }: { track: PanelTrack; title: string }) {
	const { t } = useTranslate();
	const player = usePlayer();
	const mime = mimeOf(track.format);
	const id = `${track.album}/${track.path}`;
	if (!player.canPlay(mime)) {
		const reason = t("track.cantPlay", { format: track.format });
		return (
			<button
				type="button"
				className={styles.play}
				disabled
				aria-label={reason}
			>
				<Play size={16} aria-hidden="true" />
			</button>
		);
	}
	const isPlaying = player.playing === id;
	return (
		<button
			type="button"
			className={styles.play}
			aria-label={t(isPlaying ? "track.stop" : "track.play", { title })}
			onClick={() =>
				isPlaying ? player.stop() : player.play(id, track.audio_url, mime)
			}
		>
			{isPlaying ? (
				<Square size={16} aria-hidden="true" />
			) : (
				<Play size={16} aria-hidden="true" />
			)}
		</button>
	);
}

export function TrackTable({
	tracks,
	names,
	unselected,
	readOnly,
	flags,
	swaps,
	onSwap,
	onToggle,
	onToggleAll,
}: {
	tracks: PanelTrack[];
	names: TagNames;
	unselected: string[];
	readOnly: boolean;
	/** The pairs the order check flags. */
	flags: OrderFlag[];
	/** The pairs the draft swaps. */
	swaps: [string, string][];
	onSwap: (pair: [string, string]) => void;
	onToggle: (path: string) => void;
	onToggleAll: () => void;
}) {
	const { t } = useTranslate();
	const all = unselected.length === 0;
	const discs = new Set(tracks.map((track) => track.disc));
	const numberOf = (track: PanelTrack) => {
		const number = String(track.number).padStart(2, "0");
		return discs.size > 1 ? `${track.disc}-${number}` : number;
	};
	const labelOf = (path: string) => {
		const found = tracks.find((track) => track.path === path);
		return found ? numberOf(found) : path;
	};
	// A pair goes to the draft in album order, whichever way round it was named.
	const inAlbumOrder = ([a, b]: [string, string]): [string, string] =>
		tracks.findIndex((track) => track.path === a) <=
		tracks.findIndex((track) => track.path === b)
			? [a, b]
			: [b, a];

	return (
		<div className={styles.scroll}>
			<table className={styles.tracks} aria-label={t("tracks.title")}>
				<thead>
					<tr>
						<th scope="col">
							<input
								type="checkbox"
								aria-label={t("library.selectAll")}
								checked={all}
								disabled={readOnly}
								onChange={onToggleAll}
							/>
						</th>
						<th scope="col">
							<span className="visually-hidden">{t("tracks.player")}</span>
						</th>
						<th scope="col">{t("tracks.number")}</th>
						<th scope="col">{t("tracks.name")}</th>
						<th scope="col" className={styles.right}>
							{t("tracks.length")}
						</th>
					</tr>
				</thead>
				<tbody>
					{tracks.map((track) => {
						const name =
							tagOf(track, "Title", names)[0] || lastSegment(track.path);
						return (
							<tr key={track.path}>
								<td>
									<input
										type="checkbox"
										aria-label={t("library.select", { title: name })}
										checked={!unselected.includes(track.path)}
										disabled={readOnly}
										onChange={() => onToggle(track.path)}
									/>
								</td>
								<td>
									<PlayButton track={track} title={name} />
								</td>
								<td className={styles.number}>{numberOf(track)}</td>
								<td>
									<span className={styles.name}>{name}</span>
									<span className={styles.artist}>
										{formatValues(tagOf(track, "Artist", names))}
									</span>
									<span className={styles.file}>{lastSegment(track.path)}</span>
									<RowOrder
										path={track.path}
										flags={flags}
										swaps={swaps}
										labelOf={labelOf}
										readOnly={readOnly}
										onSwap={(pair) => onSwap(inAlbumOrder(pair))}
									/>
								</td>
								<td className={`${styles.number} ${styles.right}`}>
									{formatLength(track.length)}
								</td>
							</tr>
						);
					})}
				</tbody>
			</table>
		</div>
	);
}
