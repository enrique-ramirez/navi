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
import { Landing } from "./Landing";
import type { Pending } from "./pending";

// The album as it will be written, and the facts every one of its files shares.
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

	const facts: [string, string][] = summary
		? [
				[
					t("summary.tracks"),
					summary.discs > 1
						? t("summary.tracksOnDiscs", {
								n: summary.tracks,
								discs: summary.discs,
							})
						: String(summary.tracks),
				],
				[t("summary.length"), formatTotalLength(summary.length)],
				[
					t("file.format"),
					`${summary.format} · ${t(summary.lossless ? "file.lossless" : "file.lossy")}${
						summary.bitDepth
							? ` · ${t("file.bitDepth", { n: summary.bitDepth })}`
							: ""
					}`,
				],
				[
					t("file.bitrate"),
					summary.bitrate.min === summary.bitrate.max
						? formatKbps(summary.bitrate.min)
						: `${formatKbps(summary.bitrate.min)} – ${formatKbps(summary.bitrate.max)}`,
				],
				[
					t("summary.sampleRate"),
					summary.sampleRate === null
						? t("summary.mixed")
						: formatKilohertz(summary.sampleRate),
				],
				[t("summary.size"), formatSize(summary.size)],
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
				<dl className={styles.facts}>
					{facts.map(([name, value]) => (
						<div key={name}>
							<dt>{name}</dt>
							<dd>{value}</dd>
						</div>
					))}
				</dl>
			)}

			<div className={styles.wide}>
				<Landing view={view} />
			</div>
		</aside>
	);
}
