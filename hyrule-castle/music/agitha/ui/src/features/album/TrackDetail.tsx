import { factsOf, familyOf, trackTitle } from "@/domain/album/albumTags";
import type { DiffRow } from "@/domain/album/diff";
import { formatKbps, formatLength, formatSize } from "@/domain/album/format";
import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { describeEncoding } from "./describeEncoding";
import { FactsList } from "./FactsList";
import type { Pending } from "./pending";
import { TagDiff } from "./TagDiff";
import styles from "./TrackDetail.module.css";

export function TrackDetail({
	view,
	pending,
	position,
	rows,
}: {
	view: AlbumView;
	pending: Pending;
	position: string;
	rows: DiffRow[];
}) {
	const { t } = useTranslate();
	const file = view.preview?.files.find((each) => each.position === position);
	const facts = factsOf(view, position);
	if (!file) return null;
	const title = trackTitle(view, file);

	return (
		<section className={styles.detail} aria-labelledby="track-title">
			<h3 id="track-title" className={styles.title}>
				{title}
			</h3>

			<div className={styles.group}>
				<h4 className={styles.label}>{t("track.ownTags")}</h4>
				<TagDiff
					view={view}
					pending={pending}
					rows={rows}
					scope={position}
					family={familyOf(view, file)}
					label={t("track.ownTagsOf", { title })}
				/>
			</div>

			{facts && (
				<div className={styles.group}>
					<h4 className={styles.label}>{t("file.title")}</h4>
					<FactsList
						facts={[
							{
								name: t("file.format"),
								value: `${describeEncoding(facts, t)} · ${t(
									facts.channels === 1 ? "file.channel" : "file.channels",
									{ n: facts.channels },
								)}`,
							},
							{ name: t("file.bitrate"), value: formatKbps(facts.bitrate) },
							{ name: t("file.length"), value: formatLength(facts.length) },
							{ name: t("file.size"), value: formatSize(facts.size) },
							{ name: t("file.pathNow"), value: facts.path_now, path: true },
							{
								name: t("file.pathAfter"),
								value: facts.path_after,
								path: true,
							},
						]}
					/>
				</div>
			)}
		</section>
	);
}
