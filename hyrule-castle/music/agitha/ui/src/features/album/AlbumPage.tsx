import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { Info } from "lucide-react";
import { useState } from "react";

import { albumQuery } from "@/domain/album/albumQuery";
import { familyOf } from "@/domain/album/albumTags";
import { diffOf } from "@/domain/album/diff";
import type { AlbumView, GameChoice } from "@/shared/api/types";
import type { Phrase } from "@/shared/i18n/en";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./AlbumPage.module.css";
import { AlbumSide } from "./AlbumSide";
import { Duplicate } from "./Duplicate";
import { MatchPicker } from "./MatchPicker";
import { type Pending, usePending } from "./pending";
import { ReviewBar } from "./ReviewBar";
import { TagDiff } from "./TagDiff";
import { TrackDetail } from "./TrackDetail";
import { TrackList } from "./TrackList";

export function AlbumPage() {
	const { t } = useTranslate();
	const { drop = "", n = "" } = useParams({ strict: false });
	const { data: view, isError } = useQuery(albumQuery(drop, n));

	return (
		<main className={styles.page}>
			{isError && !view && <p role="alert">{t("page.failed")}</p>}
			{!view && !isError && <p>{t("page.loading")}</p>}
			{view && <AlbumBody view={view} />}
		</main>
	);
}

const CHOICES: { value: GameChoice; label: Phrase }[] = [
	{ value: "video game music", label: "actions.gameMusic" },
	{ value: "soundtrack", label: "actions.soundtrack.choice" },
	{ value: "neither", label: "actions.neither" },
];

function Soundtrack({ pending }: { pending: Pending }) {
	const { t } = useTranslate();
	const draft = pending.draft;
	return (
		<fieldset className={styles.soundtrack}>
			<legend className={styles.label}>{t("actions.soundtrack")}</legend>
			<div className={styles.choices}>
				{CHOICES.map(({ value, label }) => (
					<label key={value} className={styles.choice}>
						<input
							type="radio"
							name="soundtrack"
							checked={draft.action === "accept" && draft.game === value}
							onChange={() => pending.setGame(value)}
						/>
						{t(label)}
					</label>
				))}
			</div>
		</fieldset>
	);
}

function Holds({ view }: { view: AlbumView }) {
	const { t } = useTranslate();
	const holds = view.preview?.holds ?? [];
	if (holds.length === 0) return null;
	return (
		<ul className={styles.holds} aria-label={t("landing.holds")}>
			{holds.map((hold) => (
				<li key={`${hold.kind}: ${hold.detail}`}>
					<Info size={16} aria-hidden="true" />
					<span>
						<strong>{t(`hold.${hold.kind}`)}</strong>
						{hold.detail && `: ${hold.detail}`}
					</span>
				</li>
			))}
		</ul>
	);
}

function AlbumBody({ view }: { view: AlbumView }) {
	const { t } = useTranslate();
	const pending = usePending(view);
	const [selected, setSelected] = useState<string | null>(null);

	const files = view.preview?.files ?? [];
	const position = selected ?? files[0]?.position ?? null;
	const edits = pending.draft.action === "accept" ? pending.draft.edits : {};
	const diff = diffOf(view, edits);
	const family = files[0] ? familyOf(view, files[0]) : "id3";
	const changes = Object.fromEntries(
		Object.entries(diff.tracks).map(([at, rows]) => [
			at,
			rows.filter((row) => row.change !== "same" && row.locked === null).length,
		]),
	);

	return (
		<>
			<ReviewBar view={view} pending={pending} />
			<Holds view={view} />
			{view.duplicate && view.state === "ready" && (
				<Duplicate view={view} pending={pending} />
			)}

			{view.preview && (
				<>
					<section className={styles.album} aria-labelledby="album-tags">
						<AlbumSide view={view} pending={pending} />
						<div className={styles.main}>
							<MatchPicker view={view} pending={pending} />
							{view.preview.game_choice && <Soundtrack pending={pending} />}
							<div className={styles.group}>
								<h2 id="album-tags" className={styles.label}>
									{t("page.albumTags", { n: files.length })}
								</h2>
								<TagDiff
									view={view}
									pending={pending}
									rows={diff.album}
									scope="all"
									family={family}
									label={t("page.albumTags", { n: files.length })}
								/>
							</div>
						</div>
					</section>

					<section className={styles.tracks} aria-labelledby="tracks-title">
						<div className={styles.trackList}>
							<h2 id="tracks-title" className={styles.label}>
								{t("tracks.title")}
							</h2>
							<TrackList
								view={view}
								selected={position}
								onSelect={setSelected}
								changes={changes}
							/>
						</div>
						{position !== null && (
							<TrackDetail
								view={view}
								pending={pending}
								position={position}
								rows={diff.tracks[position] ?? []}
							/>
						)}
					</section>
				</>
			)}
		</>
	);
}
