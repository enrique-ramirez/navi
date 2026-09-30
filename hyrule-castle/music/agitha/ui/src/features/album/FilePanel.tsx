import { factsOf } from "@/domain/album/albumTags";
import {
	formatKbps,
	formatKilohertz,
	formatLength,
	formatSize,
} from "@/domain/album/format";
import type { AlbumView, FileFacts } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./FilePanel.module.css";

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
	].join(", ");
}

export function FilePanel({
	view,
	position,
}: {
	view: AlbumView;
	position: string;
}) {
	const { t } = useTranslate();
	const facts = factsOf(view, position);

	return (
		<section className={styles.panel} aria-labelledby="file-title">
			<h2 id="file-title">{t("file.title")}</h2>
			{facts ? (
				<dl className={styles.facts}>
					<dt>{t("file.format")}</dt>
					<dd>{describeFormat(facts, t)}</dd>
					<dt>{t("file.bitrate")}</dt>
					<dd>{formatKbps(facts.bitrate)}</dd>
					<dt>{t("file.length")}</dt>
					<dd>{formatLength(facts.length)}</dd>
					<dt>{t("file.size")}</dt>
					<dd>{formatSize(facts.size)}</dd>
					<dt>{t("file.pathNow")}</dt>
					<dd className={styles.path}>{facts.path_now}</dd>
					<dt>{t("file.pathAfter")}</dt>
					<dd className={styles.path}>{facts.path_after}</dd>
				</dl>
			) : (
				<p>{t("file.none")}</p>
			)}
		</section>
	);
}
