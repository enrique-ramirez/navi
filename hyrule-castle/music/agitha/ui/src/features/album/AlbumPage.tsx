import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { useState } from "react";

import { albumQuery } from "@/domain/album/albumQuery";
import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { AlbumActions } from "./AlbumActions";
import { AlbumHeader } from "./AlbumHeader";
import styles from "./AlbumPage.module.css";
import { Candidates } from "./Candidates";
import { CoverDrop } from "./CoverDrop";
import { Duplicate } from "./Duplicate";
import { FilePanel } from "./FilePanel";
import { Landing } from "./Landing";
import { usePending } from "./pending";
import { TagEditor } from "./TagEditor";
import { TagTable } from "./TagTable";
import { TrackList } from "./TrackList";

export function AlbumPage() {
	const { t } = useTranslate();
	const { drop = "", n = "" } = useParams({ strict: false });
	const { data: view, isError } = useQuery(albumQuery(drop, n));

	return (
		<main className={styles.page}>
			<h2 className={styles.where}>{t("page.where", { drop, n })}</h2>
			{isError && !view && <p role="alert">{t("page.failed")}</p>}
			{!view && !isError && <p>{t("page.loading")}</p>}
			{view && <AlbumBody view={view} />}
		</main>
	);
}

function AlbumBody({ view }: { view: AlbumView }) {
	const { t } = useTranslate();
	const pending = usePending(view);
	const [selected, setSelected] = useState<string | null>(null);
	const [scope, setScope] = useState<"track" | "all">("track");

	const position = selected ?? view.preview?.files[0]?.position ?? null;
	const target = scope === "all" || position === null ? "all" : position;

	return (
		<>
			<AlbumHeader view={view} />
			<Candidates view={view} pending={pending} />
			<CoverDrop view={view} pending={pending} />
			{/* Once the album is written, moved or failed, the outcome and its actions come from AlbumActions. */}
			{view.duplicate && view.state === "ready" ? (
				<Duplicate view={view} pending={pending} />
			) : (
				<AlbumActions view={view} pending={pending} />
			)}
			<TrackList view={view} selected={position} onSelect={setSelected} />
			<div className={styles.columns}>
				<Landing view={view} />
				{position !== null && <FilePanel view={view} position={position} />}
			</div>
			<section aria-labelledby="tags-heading">
				<h2 id="tags-heading">{t("page.tags")}</h2>
				<div className={styles.scope}>
					<button
						type="button"
						aria-pressed={scope === "track"}
						onClick={() => setScope("track")}
					>
						{t("page.scopeTrack")}
					</button>
					<button
						type="button"
						aria-pressed={scope === "all"}
						onClick={() => setScope("all")}
					>
						{t("page.scopeAll")}
					</button>
				</div>
				<TagTable view={view} position={target} />
				<TagEditor view={view} position={target} pending={pending} />
			</section>
		</>
	);
}
