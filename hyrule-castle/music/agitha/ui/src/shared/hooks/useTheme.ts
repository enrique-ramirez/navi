import { useEffect } from "react";

import { useMediaQuery } from "./useMediaQuery";
import { useStoredState } from "./useStoredState";

export type Theme = "light" | "dark";

export function useTheme() {
	const [chosen, choose] = useStoredState<Theme | null>("agitha.theme", null);
	const prefersLight = useMediaQuery("(prefers-color-scheme: light)");
	const theme: Theme = chosen ?? (prefersLight ? "light" : "dark");

	useEffect(() => {
		document.documentElement.dataset.theme = theme;
	}, [theme]);

	const toggle = () => choose(theme === "dark" ? "light" : "dark");

	return { theme, chosen, choose, toggle };
}
