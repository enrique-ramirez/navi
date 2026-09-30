import { albumTags } from "@/domain/album/albumTags";
import {
	formatKbps,
	formatKilohertz,
	formatSize,
	formatTotalLength,
} from "@/domain/album/format";
import { summaryOf } from "@/domain/album/summary";
import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./AlbumSide.module.css";
import { CoverCard } from "./CoverCard";
import { type Fact, FactsList } from "./FactsList";
import { Landing } from "./Landing";
import type { Pending } from "./pending";

export function AlbumSide({
	view,
	pending,
}: {
	view: AlbumView;
	pending: Pending;
}) {
	const { t } = useTranslate();
	const tags = albumTags(view);
	const title = tags.title || view.name;
	const summary = summaryOf(view);

	const facts: Fact[] = summary
		? [
				{
					name: t("summary.tracks"),
					value:
						summary.discs > 1
							? t("summary.tracksOnDiscs", {
									n: summary.tracks,
									discs: summary.discs,
								})
							: String(summary.tracks),
				},
				{
					name: t("summary.length"),
					value: formatTotalLength(summary.length),
				},
				{
					name: t("file.format"),
					value: `${summary.format} · ${t(summary.lossless ? "file.lossless" : "file.lossy")}${
						summary.bitDepth
							? ` · ${t("file.bitDepth", { n: summary.bitDepth })}`
							: ""
					}`,
				},
				{
					name: t("file.bitrate"),
					value:
						summary.bitrate.min === summary.bitrate.max
							? formatKbps(summary.bitrate.min)
							: `${formatKbps(summary.bitrate.min)} – ${formatKbps(summary.bitrate.max)}`,
				},
				{
					name: t("summary.sampleRate"),
					value:
						summary.sampleRate === null
							? t("summary.mixed")
							: formatKilohertz(summary.sampleRate),
				},
				{ name: t("summary.size"), value: formatSize(summary.size) },
			]
		: [];

	return (
		<aside className={styles.side} aria-label={t("summary.title")}>
			<CoverCard view={view} pending={pending} title={title} />

			<div className={styles.heading}>
				<h2 className={styles.title}>{title}</h2>
				{tags.artist && <p className={styles.artist}>{tags.artist}</p>}
				{(tags.year || tags.genres.length > 0) && (
					<p className={styles.meta}>
						{[tags.year, tags.genres.join(", ")].filter(Boolean).join(" · ")}
					</p>
				)}
			</div>

			{facts.length > 0 && (
				<div className={styles.wide}>
					<FactsList facts={facts} compact />
				</div>
			)}

			<div className={styles.wide}>
				<Landing view={view} />
			</div>
		</aside>
	);
}
