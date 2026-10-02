import { Check, CircleAlert, Clock, LoaderCircle } from "lucide-react";
import { useId } from "react";

import type { JobAlbum, LibraryPreview } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./BatchPreview.module.css";
import { AlbumChanges, RefusedKeys } from "./ReviewChanges";

/** Whether Apply may be pressed: some album changes and none that does has a problem. */
export function canApply(preview: LibraryPreview) {
	const changing = preview.albums.filter((album) => album.skip === null);
	return (
		changing.length > 0 &&
		changing.every((album) => album.problems.length === 0)
	);
}

/** Every album a draft over several touches: the tracks that change, and the albums left out with their reasons. */
export function BatchPreview({
	preview,
	titleOf,
	onApply,
}: {
	preview: LibraryPreview;
	titleOf: (path: string) => string;
	onApply: () => void;
}) {
	const { t } = useTranslate();
	const heading = useId();
	const nothing = preview.albums.every((album) => album.skip !== null);

	return (
		<section aria-labelledby={heading} className={styles.batch}>
			<h3 id={heading}>{t("library.review")}</h3>

			{nothing && <p>{t("library.nothing")}</p>}

			<ul className={styles.albums}>
				{preview.albums.map((album) => (
					<li key={album.path} className={styles.album}>
						<h4 className={styles.name}>{titleOf(album.path)}</h4>
						{album.skip === null ? (
							<AlbumChanges preview={album} />
						) : (
							<>
								<p className={styles.skip}>{album.skip}</p>
								<RefusedKeys refused={album.refused} />
							</>
						)}
					</li>
				))}
			</ul>

			<button type="button" disabled={!canApply(preview)} onClick={onApply}>
				{t("library.apply")}
			</button>
		</section>
	);
}

const ended = (album: JobAlbum) =>
	album.state === "done" || album.state === "failed";

const ICONS = {
	waiting: Clock,
	writing: LoaderCircle,
	verifying: LoaderCircle,
	done: Check,
	failed: CircleAlert,
};

/** Where one album of a job stands, for the album's own row. */
export function JobMark({ album }: { album: JobAlbum }) {
	const { t } = useTranslate();
	const Icon = ICONS[album.state];
	return (
		<span className={styles.mark} data-state={album.state}>
			<Icon size={14} aria-hidden="true" />
			<span>{t(`library.job.${album.state}`)}</span>
		</span>
	);
}

/** How far the job is, in one line: each album says its own state on its row. */
export function BatchProgress({ albums }: { albums: JobAlbum[] }) {
	const { t } = useTranslate();
	const done = albums.filter((album) => album.state === "done").length;
	const failed = albums.filter((album) => album.state === "failed").length;
	const counts = { done, of: albums.length, failed };
	return (
		<div role="status" className={styles.progress}>
			<span>
				{albums.every(ended)
					? t("library.batchEnded", counts)
					: t("library.batchRunning", counts)}
			</span>
			<progress
				className={styles.bar}
				max={albums.length}
				value={done + failed}
				aria-label={t("library.saving")}
			/>
		</div>
	);
}
