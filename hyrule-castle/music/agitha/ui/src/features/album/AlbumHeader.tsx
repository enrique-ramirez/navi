import { useId, useState } from "react";

import { type AlbumValues, albumTags } from "@/domain/album/albumTags";
import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Parasol } from "@/shared/ui/Parasol";
import styles from "./AlbumHeader.module.css";

function Values({ values }: { values: AlbumValues }) {
	const { t } = useTranslate();
	const rows: [string, string][] = [
		[t("album.field.title"), values.title],
		[t("album.field.artist"), values.artist],
		[t("album.field.year"), values.year],
		[t("album.field.genre"), values.genres.join(" / ")],
	];
	return (
		<dl className={styles.original}>
			{rows.map(([name, value]) => (
				<div key={name}>
					<dt>{name}</dt>
					<dd>{value === "" ? "—" : value}</dd>
				</div>
			))}
		</dl>
	);
}

export function AlbumHeader({ view }: { view: AlbumView }) {
	const { t } = useTranslate();
	const [showOriginal, setShowOriginal] = useState(false);
	const regionId = useId();
	const tags = albumTags(view);
	const title = tags.title || view.name;

	return (
		<header className={styles.header}>
			<div className={styles.cover}>
				{view.cover ? (
					<img src={view.cover.url} alt={t("album.cover", { title })} />
				) : (
					<div className={styles.placeholder}>
						<Parasol size={72} />
					</div>
				)}
			</div>
			<div className={styles.text}>
				<h1 className={styles.title}>{title}</h1>
				<p className={styles.artist}>{tags.artist}</p>
				<p className={styles.year}>{tags.year}</p>
				<ul className={styles.genres} aria-label={t("album.genres")}>
					{tags.genres.map((genre) => (
						<li key={genre} className={styles.chip}>
							{genre}
						</li>
					))}
				</ul>
				<button
					type="button"
					className={styles.toggle}
					aria-expanded={showOriginal}
					aria-controls={regionId}
					onClick={() => setShowOriginal(!showOriginal)}
				>
					{t(showOriginal ? "album.hideOriginal" : "album.showOriginal")}
				</button>
				{showOriginal && (
					<section
						id={regionId}
						className={styles.originalRegion}
						aria-label={t("album.original")}
					>
						<Values values={tags.before} />
					</section>
				)}
			</div>
		</header>
	);
}
