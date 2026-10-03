import { Play, Square } from "lucide-react";
import type { ReactNode } from "react";

import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./TrackRows.module.css";

export interface TrackRow {
	id: string;
	/** As shown: `05`, or `2-05` on an album of several discs. */
	number: string;
	title: string;
	artist?: string;
	/** The file's name or path; `null` where the file is not known. */
	file: string | null;
	/** As shown, `3:41`; empty where the file is not known. */
	length: string;
	/** `mime` is empty for a format no browser is told how to play. */
	audio: { format: string; url: string; mime: string } | null;
	changes: number;
	note?: ReactNode;
}

export interface Checks {
	checked: (id: string) => boolean;
	disabled: boolean;
	onToggle: (id: string) => void;
	onToggleAll: () => void;
	labelAll: string;
	labelOf: (row: TrackRow) => string;
}

export interface Player {
	playing: string | null;
	canPlay: (mime: string) => boolean;
	play: (id: string, url: string, mime: string) => void;
	stop: () => void;
}

function PlayButton({ row, player }: { row: TrackRow; player: Player }) {
	const { t } = useTranslate();
	if (!row.audio) return null;
	const mime = row.audio.mime;
	const url = row.audio.url;
	if (!player.canPlay(mime)) {
		const reason = t("track.cantPlay", { format: row.audio.format });
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
	const isPlaying = player.playing === row.id;
	return (
		<button
			type="button"
			className={styles.play}
			aria-label={t(isPlaying ? "track.stop" : "track.play", {
				title: row.title,
			})}
			onClick={(event) => {
				event.stopPropagation();
				if (isPlaying) player.stop();
				else player.play(row.id, url, mime);
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

export function TrackRows({
	rows,
	player,
	selected,
	onSelect,
	checks,
}: {
	rows: TrackRow[];
	player: Player;
	selected: string | null;
	onSelect: (id: string) => void;
	checks?: Checks;
}) {
	const { t } = useTranslate();

	return (
		<table className={styles.table} aria-label={t("tracks.title")}>
			<thead>
				<tr>
					{checks && (
						<th scope="col" className={styles.check}>
							<input
								type="checkbox"
								aria-label={checks.labelAll}
								checked={
									rows.length > 0 && rows.every((row) => checks.checked(row.id))
								}
								disabled={checks.disabled}
								onChange={checks.onToggleAll}
							/>
						</th>
					)}
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
				{rows.map((row) => (
					<tr
						key={row.id}
						aria-selected={selected === row.id}
						className={selected === row.id ? styles.selected : ""}
						onClick={() => onSelect(row.id)}
					>
						{checks && (
							<td className={styles.check}>
								<input
									type="checkbox"
									aria-label={checks.labelOf(row)}
									checked={checks.checked(row.id)}
									disabled={checks.disabled}
									onClick={(event) => event.stopPropagation()}
									onChange={() => checks.onToggle(row.id)}
								/>
							</td>
						)}
						<td className={styles.number}>
							<PlayButton row={row} player={player} />
						</td>
						<td className={styles.number}>{row.number}</td>
						<td>
							<button type="button" className={styles.name}>
								<span className={styles.title}>{row.title}</span>
								{row.artist && (
									<span className={styles.artist}>{row.artist}</span>
								)}
								{row.file !== null && (
									<span className={styles.file}>{row.file}</span>
								)}
							</button>
							{row.note}
						</td>
						<td className={`${styles.number} ${styles.right}`}>
							{row.changes > 0 && (
								<span
									className={styles.changes}
									title={t("tracks.changes", { n: row.changes })}
								>
									<span className="visually-hidden">
										{t("tracks.changes", { n: row.changes })}
									</span>
								</span>
							)}
							{row.length}
						</td>
					</tr>
				))}
			</tbody>
		</table>
	);
}
