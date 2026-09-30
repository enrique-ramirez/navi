import {
	formatKbps,
	formatKilohertz,
	formatSize,
	formatTotalLength,
} from "@/domain/album/format";
import type { Copy } from "@/shared/api/types";
import type { useTranslate } from "@/shared/i18n/useTranslate";

type Translate = ReturnType<typeof useTranslate>["t"];

const kbpsRange = (copy: Copy) =>
	copy.bitrate_min === copy.bitrate_max
		? formatKbps(copy.bitrate)
		: `${formatKbps(copy.bitrate)} (${formatKbps(copy.bitrate_min)} – ${formatKbps(copy.bitrate_max)})`;
const release = (copy: Copy) =>
	[copy.album, copy.date, copy.country, copy.label, copy.catalog]
		.filter(Boolean)
		.join(" · ") || "—";

export function copyFacts(t: Translate): [string, (copy: Copy) => string][] {
	return [
		[t("duplicate.release"), release],
		[
			t("duplicate.mbRelease"),
			(copy) => copy.release_id ?? t("duplicate.none"),
		],
		[t("file.format"), (copy) => copy.format],
		[
			t("duplicate.lossless"),
			(copy) => t(copy.lossless ? "file.lossless" : "file.lossy"),
		],
		// A FLAC re-tagged by Mutagen reports the tagger as its vendor, which says nothing of the encoder.
		[
			t("duplicate.encoder"),
			(copy) =>
				copy.encoder && !/^mutagen\b/i.test(copy.encoder)
					? copy.encoder
					: t("duplicate.none"),
		],
		[
			t("duplicate.bitDepth"),
			(copy) =>
				copy.bit_depth === null
					? t("duplicate.none")
					: t("file.bitDepth", { n: copy.bit_depth }),
		],
		[t("duplicate.sampleRate"), (copy) => formatKilohertz(copy.sample_rate)],
		[t("duplicate.bitrate"), kbpsRange],
		[
			t("duplicate.files"),
			(copy) =>
				copy.discs > 1
					? t("summary.tracksOnDiscs", { n: copy.files, discs: copy.discs })
					: String(copy.files),
		],
		[t("duplicate.length"), (copy) => formatTotalLength(copy.length)],
		[t("duplicate.size"), (copy) => formatSize(copy.size)],
		[t("duplicate.tags"), (copy) => String(Math.round(copy.tag_count))],
		[t("duplicate.folder"), (copy) => copy.folder],
	];
}
