import { formatKilohertz } from "@/domain/album/format";
import type { useTranslate } from "@/shared/i18n/useTranslate";

type Translate = ReturnType<typeof useTranslate>["t"];

export function describeEncoding(
	file: {
		format: string;
		lossless: boolean;
		bit_depth: number | null;
		sample_rate: number;
	},
	t: Translate,
) {
	return [
		file.format,
		t(file.lossless ? "file.lossless" : "file.lossy"),
		...(file.bit_depth === null
			? []
			: [t("file.bitDepth", { n: file.bit_depth })]),
		formatKilohertz(file.sample_rate),
	].join(" · ");
}
