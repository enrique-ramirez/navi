import { useSyncExternalStore } from "react";

import {
	readStoredState,
	writeStoredState,
} from "@/shared/hooks/useStoredState";
import { en, type Phrase } from "./en";

export type Locale = "en" | "es";

const AVAILABLE: readonly Locale[] = ["en", "es"];
const CHOICE_KEY = "agitha.locale";

export interface LocaleState {
	/** The language phrases are read from: English until Spanish has loaded. */
	readonly active: Locale;
	/** The owner's pick, or null while the browser's order decides. */
	readonly chosen: Locale | null;
	readonly available: readonly Locale[];
}

let state: LocaleState = { active: "en", chosen: null, available: AVAILABLE };
let spanish: Partial<Record<Phrase, string>> = {};
let started = false;
const listeners = new Set<() => void>();

const publish = (next: Partial<LocaleState>) => {
	state = { ...state, ...next };
	document.documentElement.lang = state.active;
	for (const listener of listeners) listener();
};

const isLocale = (value: unknown): value is Locale =>
	AVAILABLE.some((locale) => locale === value);

function fromBrowser(): Locale {
	const asked = navigator.languages?.length
		? navigator.languages
		: [navigator.language];
	for (const tag of asked) {
		const language = tag.toLowerCase().split("-")[0];
		if (isLocale(language)) return language;
	}
	return "en";
}

let latest = 0;

async function adopt(locale: Locale) {
	const mine = ++latest;
	if (locale === "en") {
		spanish = {};
		publish({ active: "en" });
		return;
	}
	try {
		const response = await fetch("/locales/es.json");
		if (!response.ok) throw new Error(String(response.status));
		const body = (await response.json()) as Partial<Record<Phrase, string>>;
		if (mine !== latest) return;
		spanish = body;
		publish({ active: "es" });
	} catch (error) {
		console.error("Spanish catalogue did not load", error);
		if (mine === latest) publish({ active: "en" });
	}
}

function start() {
	if (started) return;
	started = true;
	const stored = readStoredState<unknown>(CHOICE_KEY, null);
	const chosen = isLocale(stored) ? stored : null;
	publish({ chosen });
	void adopt(chosen ?? fromBrowser());
}

function subscribe(listener: () => void) {
	listeners.add(listener);
	start();
	return () => {
		listeners.delete(listener);
	};
}

const snapshot = () => state;

export function setLocale(locale: Locale | null): void {
	writeStoredState(CHOICE_KEY, locale);
	publish({ chosen: locale });
	void adopt(locale ?? fromBrowser());
}

export function useLocale() {
	const current = useSyncExternalStore(subscribe, snapshot);
	return { ...current, choose: setLocale };
}

export const phrase = (key: Phrase): string =>
	state.active === "es" ? (spanish[key] ?? en[key]) : en[key];
