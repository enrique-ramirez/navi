export function formatLength(seconds: number): string {
	const whole = Math.floor(seconds);
	const rest = String(whole % 60).padStart(2, "0");
	return `${Math.floor(whole / 60)}:${rest}`;
}

export function formatTotalLength(seconds: number): string {
	const whole = Math.floor(seconds);
	const hours = Math.floor(whole / 3600);
	const minutes = Math.floor((whole % 3600) / 60);
	const rest = String(whole % 60).padStart(2, "0");
	return hours > 0
		? `${hours}:${String(minutes).padStart(2, "0")}:${rest}`
		: `${minutes}:${rest}`;
}

// Decimal units, as `du --si` and Jean show them.
export function formatSize(bytes: number): string {
	if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
	if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
	if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(1)} kB`;
	return `${bytes} B`;
}

export const formatKilohertz = (hertz: number) =>
	`${Number((hertz / 1000).toFixed(1))} kHz`;

export const formatKbps = (bitsPerSecond: number) =>
	`${Math.round(bitsPerSecond / 1000)} kbps`;

export const formatValues = (values: string[]) => values.join("; ");
