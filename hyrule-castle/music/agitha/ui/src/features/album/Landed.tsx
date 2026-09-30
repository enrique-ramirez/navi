import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, CircleCheck, House } from "lucide-react";

import { albumTags } from "@/domain/album/albumTags";
import { dropsKey, fetchDrops } from "@/shared/api/drops";
import type { AlbumState, AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./Landed.module.css";

// The states an album of the drop can still be reviewed or finished in.
const OPEN: AlbumState[] = [
	"queued",
	"identifying",
	"ready",
	"identify failed",
	"identify interrupted",
	"written, not moved",
	"apply failed",
];

// What the page becomes once the album is in the library: where it went, and where to go next.
export function Landed({ view }: { view: AlbumView }) {
	const { t } = useTranslate();
	const { data: drops = [] } = useQuery({
		queryKey: dropsKey,
		queryFn: fetchDrops,
	});
	const tags = albumTags(view);
	const title = tags.title || view.name;
	const next = drops
		.find((drop) => drop.id === view.drop)
		?.albums.find((album) => album.n !== view.n && OPEN.includes(album.state));

	return (
		<section className={styles.landed} aria-labelledby="landed-title">
			<CircleCheck size={48} className={styles.icon} aria-hidden="true" />
			<h2 id="landed-title" className={styles.title}>
				{t("landed.title", { title })}
			</h2>
			{tags.artist && <p className={styles.artist}>{tags.artist}</p>}
			{view.library_path && (
				<p className={styles.path}>
					<span>{t("landed.at")}</span>
					<code>{view.library_path}</code>
				</p>
			)}
			<div className={styles.actions}>
				{next && (
					<Link
						to="/drops/$drop/albums/$n"
						params={{ drop: view.drop, n: next.n }}
						className={styles.primary}
					>
						{t("landed.next", { title: next.title ?? next.name })}
						<ArrowRight size={16} aria-hidden="true" />
					</Link>
				)}
				<Link to="/" className={next ? styles.secondary : styles.primary}>
					<House size={16} aria-hidden="true" />
					{t("landed.home")}
				</Link>
			</div>
		</section>
	);
}
