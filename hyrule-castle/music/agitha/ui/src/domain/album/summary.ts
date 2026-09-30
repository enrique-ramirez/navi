import type { AlbumView } from "@/shared/api/types";

/** What the album's files have in common, or the range they span. */
export interface Summary {
	tracks: number;
	discs: number;
	/** Seconds. */
	length: number;
	/** Bytes. */
	size: number;
	/** The one format, or every format joined where they differ. */
	format: string;
	lossless: boolean;
	/** Bits per second; `min` equals `max` where every file agrees. */
	bitrate: { min: number; max: number };
	/** Hz; `null` where the files differ. */
	sampleRate: number | null;
	bitDepth: number | null;
	channels: number | null;
}

const one = <T>(values: T[]) =>
	values.every((value) => value === values[0]) ? (values[0] ?? null) : null;

export function summaryOf(view: AlbumView): Summary | null {
	const files = view.files;
	if (files.length === 0) return null;
	const bitrates = files.map((file) => file.bitrate);
	return {
		tracks: files.length,
		discs: new Set(files.map((file) => file.position.split("-")[0])).size,
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
