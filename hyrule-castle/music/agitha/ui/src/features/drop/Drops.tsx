import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { isRunning } from "@/domain/album/albumQuery";
import { post } from "@/shared/api/album";
import type {
	AlbumAction,
	AlbumSummary,
	Drop,
	DropList,
} from "@/shared/api/types";
import { albumStatePhrase } from "@/shared/i18n/albumState";
import type { Phrase } from "@/shared/i18n/en";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./Drops.module.css";

const DROP_STATE: Record<Drop["state"], Phrase | null> = {
	uploading: "state.uploading",
	incomplete: "drop.incomplete",
	extracting: "state.extracting",
	ready: null,
};

// The buttons an album row can offer, each named by the server's action and posted to its own path.
const ROW_ACTIONS: { action: AlbumAction; label: Phrase }[] = [
	{ action: "retry", label: "action.retry" },
	{ action: "move", label: "action.moveIntoLibrary" },
	{ action: "discard", label: "action.discard" },
];

// Asked again every 2 s while anything is uploading, extracting or being run by musiclib.
function refetchInterval(query: { state: { data?: DropList } }) {
	const drops = query.state.data ?? [];
	const running = drops.some(
		(drop) =>
			drop.state === "uploading" ||
			drop.state === "extracting" ||
			drop.albums.some((album) => isRunning(album.state)),
	);
	return running ? 2000 : false;
}

async function fetchDrops(): Promise<DropList> {
	const response = await fetch("/api/drops");
	if (!response.ok) throw new Error(String(response.status));
	return response.json();
}

function AlbumRow({
	drop,
	album,
	onPost,
}: {
	drop: Drop;
	album: AlbumSummary;
	onPost: (path: string) => void;
}) {
	const { t } = useTranslate();
	const base = `${encodeURIComponent(drop.id)}/albums/${album.n}`;
	const title = album.title ?? album.name;
	return (
		<li className={styles.album}>
			<div className={styles.head}>
				<span className={styles.name}>{album.name}</span>
				{album.title && (
					<span>
						{album.title}
						{album.artist ? ` — ${album.artist}` : ""}
					</span>
				)}
				<span className={styles.state}>{t(albumStatePhrase[album.state])}</span>
			</div>
			{album.duplicate_of && (
				<p className={styles.note}>
					{t("album.sameFolder", { n: album.duplicate_of })}
				</p>
			)}
			{album.error && <p className={styles.note}>{album.error}</p>}
			{album.stderr !== "" && (
				<pre className={styles.stderr}>{album.stderr}</pre>
			)}
			<div className={styles.buttons}>
				<Link
					to={`/drops/${drop.id}/albums/${album.n}`}
					className={styles.link}
					aria-label={`${t("action.open")} ${title}`}
				>
					{t("action.open")}
				</Link>
				{ROW_ACTIONS.filter(({ action }) => album.actions.includes(action)).map(
					({ action, label }) => (
						<button
							key={action}
							type="button"
							className={styles.button}
							aria-label={`${t(label)} ${title}`}
							onClick={() => onPost(`${base}/${action}`)}
						>
							{t(label)}
						</button>
					),
				)}
			</div>
		</li>
	);
}

export function Drops() {
	const { t } = useTranslate();
	const client = useQueryClient();
	const [error, setError] = useState<string | null>(null);
	const { data: drops = [] } = useQuery({
		queryKey: ["drops"],
		queryFn: fetchDrops,
		refetchInterval,
	});

	// Posts to an album or drop, then asks the list again: it only changes on the server's answer.
	async function act(path: string) {
		setError(null);
		const answer = await post(`/api/drops/${path}`, {});
		if (!answer.ok) setError(answer.error);
		await client.invalidateQueries({ queryKey: ["drops"] });
	}

	return (
		<section className={styles.drops}>
			{error && <p role="alert">{error}</p>}
			{drops.map((drop) => {
				const stateName = DROP_STATE[drop.state];
				return (
					<section key={drop.id} className={styles.drop}>
						<div className={styles.dropHead}>
							<h2>{drop.id}</h2>
							{stateName && (
								<span className={styles.state}>{t(stateName)}</span>
							)}
							{drop.actions.includes("discard") && (
								<button
									type="button"
									className={styles.button}
									aria-label={`${t("action.discard")} ${drop.id}`}
									onClick={() =>
										void act(`${encodeURIComponent(drop.id)}/discard`)
									}
								>
									{t("action.discard")}
								</button>
							)}
						</div>
						{drop.error && <p className={styles.note}>{drop.error}</p>}
						{drop.refused.length > 0 && (
							<ul className={styles.plain}>
								{drop.refused.map((refused) => (
									<li key={`${refused.item}/${refused.entry}`}>
										<span>{refused.item}</span> <span>{refused.reason}</span>
										{refused.entry && <code> {refused.entry}</code>}
									</li>
								))}
							</ul>
						)}
						{drop.ignored.length > 0 && (
							<ul className={styles.plain}>
								{drop.ignored.map((each) => (
									<li key={`${each.item}/${each.path}`}>
										<span>
											{each.path ? `${each.item}/${each.path}` : each.item}
										</span>{" "}
										<span className={styles.note}>
											{each.reason === "no audio files"
												? t("drop.noAudio")
												: each.reason}
										</span>
									</li>
								))}
							</ul>
						)}
						{drop.albums.length > 0 && (
							<ul className={styles.albums}>
								{drop.albums.map((album) => (
									<AlbumRow
										key={album.n}
										drop={drop}
										album={album}
										onPost={(path) => void act(path)}
									/>
								))}
							</ul>
						)}
					</section>
				);
			})}
		</section>
	);
}
