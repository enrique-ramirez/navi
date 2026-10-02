import { ArrowRight } from "lucide-react";
import { useId } from "react";

import { formatValues } from "@/domain/album/format";
import type { CoverCheck, PreviewAlbum, RefusedKey } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./ReviewChanges.module.css";

const sideOf = (values: string[] | null) =>
	values === null ? "—" : formatValues(values);

/** The tags the server refused, each with its reason. */
export function RefusedKeys({ refused }: { refused: RefusedKey[] }) {
	const { t } = useTranslate();
	if (refused.length === 0) return null;
	return (
		<ul className={styles.refused}>
			{refused.map((each) => (
				<li key={each.key}>
					{t("library.refusedKey", { key: each.key, reason: each.reason })}
				</li>
			))}
		</ul>
	);
}

/**
 * What a preview of one album changes: where it moves, its cover, each changed
 * track, and the problems and refused tags. An album page's review and a
 * batch's review both show this.
 */
export function AlbumChanges({
	preview,
	was,
	covers,
}: {
	preview: PreviewAlbum;
	/** The cover the album has now, `null` where it has none. */
	was?: CoverCheck | null;
	/** Where the two covers can be shown from, each left out where there is no image to show. */
	covers?: { was?: string | null; next?: string | null };
}) {
	const { t } = useTranslate();
	return (
		<div className={styles.album}>
			{preview.path !== preview.new_path && (
				<p className={styles.move}>
					<span>{preview.path}</span> → <span>{preview.new_path}</span>
				</p>
			)}

			{preview.cover && (
				<div className={styles.cover}>
					{(covers?.was || covers?.next) && (
						<div className={styles.covers}>
							{covers.was && was && (
								<CoverThumb src={covers.was} alt={t("library.coverNow")} />
							)}
							{covers.was && was && covers.next && (
								<ArrowRight size={18} aria-hidden="true" />
							)}
							{covers.next && (
								<CoverThumb src={covers.next} alt={t("library.coverNext")} />
							)}
						</div>
					)}
					<p>
						{was
							? t("library.reviewCoverFrom", {
									from: t("duplicate.by", { w: was.width, h: was.height }),
									to: t("duplicate.by", {
										w: preview.cover.width,
										h: preview.cover.height,
									}),
								})
							: t("library.reviewCover", {
									to: t("duplicate.by", {
										w: preview.cover.width,
										h: preview.cover.height,
									}),
								})}
					</p>
					{!preview.cover.passes && (
						<p className={styles.coverWarning}>
							{t("cover.fails", { problem: preview.cover.problem ?? "" })}
						</p>
					)}
				</div>
			)}

			{preview.tracks.map((track) => (
				<fieldset
					key={track.path}
					aria-label={track.path}
					className={styles.track}
				>
					<legend className={styles.path}>{track.path}</legend>
					{track.new_path !== track.path && (
						<p className={styles.move}>→ {track.new_path}</p>
					)}
					<ul className={styles.changes}>
						{track.changes.map((change) => (
							<li key={change.key} className={styles.change}>
								<span className={styles.key}>{change.key}</span>
								<span className={styles.before}>{sideOf(change.before)}</span>
								<span aria-hidden="true">→</span>
								<span className={styles.after}>{sideOf(change.after)}</span>
							</li>
						))}
					</ul>
				</fieldset>
			))}

			{preview.problems.length > 0 && (
				<ul className={styles.problems}>
					{preview.problems.map((problem) => (
						<li key={`${problem.rule}: ${problem.detail}`}>
							{t("library.problem", {
								rule: problem.rule,
								detail: problem.detail,
							})}
						</li>
					))}
				</ul>
			)}

			<RefusedKeys refused={preview.refused} />
		</div>
	);
}

// The sizes are in the sentence under the two; each image is named by which cover it is.
function CoverThumb({ src, alt }: { src: string; alt: string }) {
	return (
		<figure className={styles.thumb}>
			<img src={src} alt="" />
			<figcaption>{alt}</figcaption>
		</figure>
	);
}

export function ReviewChanges({
	preview,
	was,
	covers,
	onSave,
}: {
	preview: PreviewAlbum;
	/** The cover the album has now, `null` where it has none. */
	was?: CoverCheck | null;
	/** As on `AlbumChanges`. */
	covers?: { was?: string | null; next?: string | null };
	onSave: () => void;
}) {
	const { t } = useTranslate();
	const heading = useId();
	const nothing = preview.tracks.length === 0 && preview.cover === null;

	return (
		<section aria-labelledby={heading} className={styles.review}>
			<h3 id={heading} className={styles.title}>
				{t("library.review")}
			</h3>

			<AlbumChanges preview={preview} was={was} covers={covers} />

			{nothing && <p>{t("library.nothing")}</p>}

			<button
				type="button"
				className={styles.save}
				disabled={nothing || preview.problems.length > 0}
				onClick={onSave}
			>
				{t("library.save")}
			</button>
		</section>
	);
}
