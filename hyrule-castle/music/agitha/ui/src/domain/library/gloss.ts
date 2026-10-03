import type { Phrase } from "@/shared/i18n/en";

// ID3 frames the engine gives no readable name, so the panel would show four letters and nothing else.
const FRAMES: Record<string, Phrase> = {
	APIC: "gloss.APIC",
	POPM: "gloss.POPM",
	TSOA: "gloss.TSOA",
	TSOT: "gloss.TSOT",
	TSSE: "gloss.TSSE",
	TENC: "gloss.TENC",
	TLEN: "gloss.TLEN",
	TCOP: "gloss.TCOP",
	TLAN: "gloss.TLAN",
	TSRC: "gloss.TSRC",
	TKEY: "gloss.TKEY",
	TIT1: "gloss.TIT1",
	TIT3: "gloss.TIT3",
	TPE4: "gloss.TPE4",
	TOPE: "gloss.TOPE",
	TOAL: "gloss.TOAL",
	TDRL: "gloss.TDRL",
	TDTG: "gloss.TDTG",
	MCDI: "gloss.MCDI",
	PRIV: "gloss.PRIV",
	GEOB: "gloss.GEOB",
	PCNT: "gloss.PCNT",
	WXXX: "gloss.WXXX",
	COMM: "gloss.COMM",
	USLT: "gloss.USLT",
};

export function glossOf(key: string): Phrase | null {
	const frame = /^[A-Z0-9]{4}(?=$|:)/.exec(key)?.[0];
	return (frame && FRAMES[frame]) || null;
}
