import { Link } from "@tanstack/react-router";
import { Moon, Sun } from "lucide-react";

import { useTheme } from "@/shared/hooks/useTheme";
import { useLocale } from "@/shared/i18n/locale";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Parasol } from "@/shared/ui/Parasol";
import styles from "./TopBar.module.css";

export function TopBar() {
	const { t } = useTranslate();
	const { theme, toggle } = useTheme();
	const { active, choose } = useLocale();
	const other = active === "en" ? "es" : "en";

	return (
		<header className={styles.bar}>
			<h1 className={styles.brand}>
				<Link to="/" className={styles.home}>
					<Parasol size={28} />
					<span>{t("app.title")}</span>
				</Link>
			</h1>
			<div className={styles.spacer} />
			<button type="button" className={styles.button} onClick={toggle}>
				{theme === "dark" ? (
					<Sun size={16} aria-hidden="true" />
				) : (
					<Moon size={16} aria-hidden="true" />
				)}
				<span className="visually-hidden">
					{t(theme === "dark" ? "nav.theme.light" : "nav.theme.dark")}
				</span>
			</button>
			<button
				type="button"
				className={styles.button}
				lang={other}
				onClick={() => choose(other)}
			>
				{t(other === "es" ? "nav.language.es" : "nav.language.en")}
			</button>
		</header>
	);
}
