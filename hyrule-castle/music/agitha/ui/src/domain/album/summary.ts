import type { AlbumView } from "@/shared/api/types";
import { uploadedValues } from "./albumTags";

export interface Summary {
	tracks: number;
	discs: number;
	/** Seconds. */
	length: number;
	/** Bytes. */
	size: number;
	format: string;
	lossless: boolean;
	/** Bits per second. */
	bitrate: { min: number; max: number };
	/** Hz. */
	sampleRate: number | null;
	bitDepth: number | null;
	channels: number | null;
}

const one = <T>(values: T[]) =>
	values.every((value) => value === values[0]) ? (values[0] ?? null) : null;

function audioOf(view: AlbumView) {
	if (view.files.length > 0)
		return view.files.map((file) => ({
			...file,
			disc: file.position.split("-")[0] ?? "",
		}));
	return (view.uploaded ?? []).map((file) => ({
		...file,
		disc: uploadedValues(file).disc,
	}));
}

export function summaryOf(view: AlbumView): Summary | null {
	const files = audioOf(view);
	if (files.length === 0) return null;
	const bitrates = files.map((file) => file.bitrate);
	return {
		tracks: files.length,
		discs: new Set(files.map((file) => file.disc)).size,
		length: files.reduce((sum, file) => sum + file.length, 0),
		size: files.reduce((sum, file) => sum + file.size, 0),
		format: [...new Set(files.map((file) => file.format))].join(" + "),
		lossless: files.every((file) => file.lossless),
		bitrate: { min: Math.min(...bitrates), max: Math.max(...bitrates) },
		sampleRate: one(files.map((file) => file.sample_rate)),
		bitDepth: one(files.map((file) => file.bit_depth)),
		channels: one(files.map((file) => file.channels)),
	};
}
