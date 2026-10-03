import type { ReactNode } from "react";

import { useTranslate } from "@/shared/i18n/useTranslate";
import { type Fact, FactsList } from "./FactsList";
import styles from "./SideSummary.module.css";

export function SideSummary({
	cover,
	title,
	titleIsHeading = true,
	artist,
	year,
	genres,
	facts,
	children,
}: {
	cover: ReactNode;
	title: string;
	/** False where the page around it already heads itself with the title. */
	titleIsHeading?: boolean;
	artist: string;
	year: string;
	genres: string[];
	facts: Fact[];
	children?: ReactNode;
}) {
	const { t } = useTranslate();
	return (
		<aside className={styles.side} aria-label={t("summary.title")}>
			{cover}

			<div className={styles.heading}>
				{titleIsHeading ? (
					<h2 className={styles.title}>{title}</h2>
				) : (
					<p className={styles.title}>{title}</p>
				)}
				{artist && <p className={styles.artist}>{artist}</p>}
				{(year || genres.length > 0) && (
					<p className={styles.meta}>
						{[year, genres.join(", ")].filter(Boolean).join(" · ")}
					</p>
				)}
			</div>

			{facts.length > 0 && (
				<div className={styles.wide}>
					<FactsList facts={facts} compact />
				</div>
			)}

			{children && <div className={styles.wide}>{children}</div>}
		</aside>
	);
}
