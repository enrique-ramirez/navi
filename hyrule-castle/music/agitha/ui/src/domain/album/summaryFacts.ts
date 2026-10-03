import {
	formatKbps,
	formatKilohertz,
	formatSize,
	formatTotalLength,
} from "@/domain/album/format";
import type { Summary } from "@/domain/album/summary";
import type { useTranslate } from "@/shared/i18n/useTranslate";
import type { Fact } from "@/shared/ui/FactsList";

type Translate = ReturnType<typeof useTranslate>["t"];

export const describeQuality = (
	summary: Pick<Summary, "format" | "lossless" | "bitDepth">,
	t: Translate,
) =>
	`${summary.format} · ${t(summary.lossless ? "file.lossless" : "file.lossy")}${
		summary.bitDepth ? ` · ${t("file.bitDepth", { n: summary.bitDepth })}` : ""
	}`;

export function summaryFacts(summary: Summary, t: Translate): Fact[] {
	return [
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
		{ name: t("file.format"), value: describeQuality(summary, t) },
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
	];
}
