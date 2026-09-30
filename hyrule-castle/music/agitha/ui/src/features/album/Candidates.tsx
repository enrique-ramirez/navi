import { useState } from "react";

import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./Candidates.module.css";
import type { Pending } from "./pending";

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
// A bare MBID, or the URL of one release. A release group's URL names no one release.
const BARE = new RegExp(`^${UUID}$`, "i");
const RELEASE_URL = new RegExp(
	`^https?://(www\\.|beta\\.)?musicbrainz\\.org/release/${UUID}([/?#].*)?$`,
	"i",
);

export function Candidates({
	view,
	pending,
}: {
	view: AlbumView;
	pending: Pending;
}) {
	const { t } = useTranslate();
	const [pasted, setPasted] = useState("");
	const [refused, setRefused] = useState(false);
	const chosen =
		pending.draft.action === "accept" ? pending.draft.release_id : null;

	function use() {
		const release = pasted.trim();
		if (BARE.test(release) || RELEASE_URL.test(release)) {
			setRefused(false);
			pending.setRepoint(release);
		} else {
			setRefused(true);
		}
	}

	return (
		<section className={styles.candidates} aria-labelledby="candidates-title">
			<h2 id="candidates-title">{t("candidates.title")}</h2>
			<ul className={styles.list} aria-label={t("candidates.title")}>
				{(view.preview?.candidates ?? []).map((candidate) => {
					const isChosen = candidate.release_id === chosen;
					return (
						<li
							key={candidate.release_id}
							className={isChosen ? styles.chosen : styles.item}
							aria-current={isChosen ? "true" : undefined}
						>
							<img
								src={candidate.thumbnail}
								alt={t("candidates.thumbnail", { title: candidate.title })}
								width={64}
								height={64}
							/>
							<div className={styles.facts}>
								<strong>{candidate.title}</strong>{" "}
								<span>{candidate.artist}</span> <span>{candidate.date}</span>{" "}
								<span>{candidate.country}</span> <span>{candidate.format}</span>{" "}
								<span>
									{candidate.track_counts
										.map((count) => count ?? "?")
										.join(" + ")}
								</span>
							</div>{" "}
							{isChosen ? (
								<span className={styles.mark}>{t("candidates.chosen")}</span>
							) : (
								<button
									type="button"
									className={styles.button}
									onClick={() => pending.setCandidate(candidate.release_id)}
								>
									{t("candidates.choose", { title: candidate.title })}
								</button>
							)}
						</li>
					);
				})}
			</ul>
			<div className={styles.paste}>
				<label htmlFor="candidates-paste">{t("candidates.paste")}</label>
				<input
					id="candidates-paste"
					type="text"
					value={pasted}
					onChange={(event) => setPasted(event.target.value)}
				/>
				<button type="button" className={styles.button} onClick={use}>
					{t("candidates.use")}
				</button>
			</div>
			{refused && <p role="alert">{t("candidates.notRelease")}</p>}
		</section>
	);
}
