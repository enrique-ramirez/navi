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

/** Each album the job writes, with its state and, where it failed, why. */
export function BatchProgress({
	albums,
	titleOf,
}: {
	albums: JobAlbum[];
	titleOf: (path: string) => string;
}) {
	const { t } = useTranslate();
	return (
		<ul className={styles.albums}>
			{albums.map((album) => (
				<li key={album.path} className={styles.album}>
					<span className={styles.name}>{titleOf(album.path)}</span>{" "}
					<span>{t(`library.job.${album.state}`)}</span>
					{album.error && <p className={styles.skip}>{album.error}</p>}
				</li>
			))}
		</ul>
	);
}
