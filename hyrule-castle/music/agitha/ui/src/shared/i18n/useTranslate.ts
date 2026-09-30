import { useCallback } from "react";

import type { Phrase } from "./en";
import { phrase, useLocale } from "./locale";

export type Values = Record<string, string | number>;

const PLACEHOLDER = /\{(\w+)\}/g;

export function useTranslate() {
	const { active } = useLocale();

	// `active` is not read inside: a new function per language re-renders the callers.
	// biome-ignore lint/correctness/useExhaustiveDependencies: see above
	const t = useCallback(
		(key: Phrase, values: Values = {}) =>
			phrase(key).replace(PLACEHOLDER, (whole, name: string) =>
				name in values ? String(values[name]) : whole,
			),
		[active],
	);

	return { t };
}
