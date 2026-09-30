import { useSyncExternalStore } from "react";

const MIME: Record<string, string> = {
	MP3: "audio/mpeg",
	FLAC: "audio/flac",
	MP4: "audio/mp4",
	"Ogg Vorbis": "audio/ogg",
	WMA: "audio/x-ms-wma",
};

export const mimeOf = (format: string) => MIME[format] ?? "";

let audio: HTMLAudioElement | null = null;
let playing: string | null = null;
const listeners = new Set<() => void>();

const publish = (next: string | null) => {
	playing = next;
	for (const listener of listeners) listener();
};

function element(): HTMLAudioElement {
	if (!audio) {
		audio = new Audio();
		audio.addEventListener("ended", () => publish(null));
	}
	return audio;
}

function canPlay(mime: string) {
	return element().canPlayType(mime) !== "";
}

function play(position: string, url: string, mime: string) {
	const player = element();
	if (!canPlay(mime)) return;
	if (playing !== null) player.pause();
	player.src = url;
	publish(position);
	player.play().catch(() => {
		if (playing === position) publish(null);
	});
}

function stop() {
	if (playing === null) return;
	element().pause();
	publish(null);
}

function subscribe(listener: () => void) {
	listeners.add(listener);
	return () => {
		listeners.delete(listener);
	};
}

export function usePlayer() {
	const current = useSyncExternalStore(subscribe, () => playing);
	return { playing: current, play, stop, canPlay };
}
