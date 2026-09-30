import { Play, Square } from "lucide-react";

import { factsOf, trackTitle } from "@/domain/album/albumTags";
import { formatLength } from "@/domain/album/format";
import { mimeOf, usePlayer } from "@/domain/player/usePlayer";
import type { AlbumView, FileFacts } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./TrackList.module.css";

interface Props {
	view: AlbumView;
	selected: string | null;
	onSelect: (position: string) => void;
	changes: Record<string, number>;
}

function numberOf(position: string, multiDisc: boolean) {
	const [disc = "", track = ""] = position.split("-");
	const padded = track.padStart(2, "0");
	return multiDisc ? `${disc}-${padded}` : padded;
}

function PlayButton({
	facts,
	title,
	position,
	player,
}: {
	facts: FileFacts | undefined;
	title: string;
	position: string;
	player: ReturnType<typeof usePlayer>;
}) {
	const { t } = useTranslate();
	if (!facts) return null;
	const mime = mimeOf(facts.format);
	if (!player.canPlay(mime)) {
		const reason = t("track.cantPlay", { format: facts.format });
		return (
			<>
				<button
					type="button"
					className={styles.play}
					disabled
					aria-label={reason}
				>
					<Play size={16} aria-hidden="true" />
				</button>
				<span className={styles.reason} aria-hidden="true">
					{reason}
				</span>
			</>
		);
	}
	const isPlaying = player.playing === position;
	return (
		<button
			type="button"
			className={styles.play}
			aria-label={t(isPlaying ? "track.stop" : "track.play", { title })}
			onClick={(event) => {
				event.stopPropagation();
				if (isPlaying) player.stop();
				else player.play(position, facts.audio_url, mime);
			}}
		>
			{isPlaying ? (
				<Square size={16} aria-hidden="true" />
			) : (
				<Play size={16} aria-hidden="true" />
			)}
		</button>
	);
}

export function TrackList({ view, selected, onSelect, changes }: Props) {
	const { t } = useTranslate();
	const player = usePlayer();
	const files = view.preview?.files ?? [];
	const discs = new Set(files.map((file) => file.position.split("-")[0]));

	return (
		<table className={styles.table} aria-label={t("tracks.title")}>
			<thead>
				<tr>
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
				{files.map((file) => {
					const facts = factsOf(view, file.position);
					const title = trackTitle(view, file);
					return (
						// The title button takes the keyboard; its click bubbles here, so a mouse click anywhere on the row selects it too.
						<tr
							key={file.position}
							aria-selected={selected === file.position}
							className={selected === file.position ? styles.selected : ""}
							onClick={() => onSelect(file.position)}
						>
							<td className={styles.number}>
								<PlayButton
									facts={facts}
									title={title}
									position={file.position}
									player={player}
								/>
							</td>
							<td className={styles.number}>
								{numberOf(file.position, discs.size > 1)}
							</td>
							<td>
								<button type="button" className={styles.name}>
									<span className={styles.title}>{title}</span>
									{facts && (
										<span className={styles.file}>{facts.path_now}</span>
									)}
								</button>
							</td>
							<td className={`${styles.number} ${styles.right}`}>
								{(changes[file.position] ?? 0) > 0 && (
									<span
										className={styles.changes}
										title={t("tracks.changes", {
											n: changes[file.position] ?? 0,
										})}
									>
										<span className="visually-hidden">
											{t("tracks.changes", { n: changes[file.position] ?? 0 })}
										</span>
									</span>
								)}
								{facts ? formatLength(facts.length) : ""}
							</td>
						</tr>
					);
				})}
			</tbody>
		</table>
	);
}
