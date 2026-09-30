import { factsOf, familyOf, trackTitle } from "@/domain/album/albumTags";
import type { DiffRow } from "@/domain/album/diff";
import {
	formatKbps,
	formatKilohertz,
	formatLength,
	formatSize,
} from "@/domain/album/format";
import type { AlbumView, FileFacts } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import type { Pending } from "./pending";
import { TagDiff } from "./TagDiff";
import styles from "./TrackDetail.module.css";

type Translate = ReturnType<typeof useTranslate>["t"];

function describeFormat(facts: FileFacts, t: Translate) {
	return [
		facts.format,
		t(facts.lossless ? "file.lossless" : "file.lossy"),
		...(facts.bit_depth === null
			? []
			: [t("file.bitDepth", { n: facts.bit_depth })]),
		formatKilohertz(facts.sample_rate),
		t(facts.channels === 1 ? "file.channel" : "file.channels", {
			n: facts.channels,
		}),
	].join(" · ");
}

// One track: the tags only it has, and its file.
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
					<dl className={styles.facts}>
						<div>
							<dt>{t("file.format")}</dt>
							<dd>{describeFormat(facts, t)}</dd>
						</div>
						<div>
							<dt>{t("file.bitrate")}</dt>
							<dd>{formatKbps(facts.bitrate)}</dd>
						</div>
						<div>
							<dt>{t("file.length")}</dt>
							<dd>{formatLength(facts.length)}</dd>
						</div>
						<div>
							<dt>{t("file.size")}</dt>
							<dd>{formatSize(facts.size)}</dd>
						</div>
						<div>
							<dt>{t("file.pathNow")}</dt>
							<dd className={styles.path}>{facts.path_now}</dd>
						</div>
						<div>
							<dt>{t("file.pathAfter")}</dt>
							<dd className={styles.path}>{facts.path_after}</dd>
						</div>
					</dl>
				</div>
			)}
		</section>
	);
}
