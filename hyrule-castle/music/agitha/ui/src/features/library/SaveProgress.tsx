import type { Saving } from "@/domain/library/libraryQuery";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./SaveProgress.module.css";

export function SaveProgress({ state }: { state: Saving }) {
	const { t } = useTranslate();
	return (
		<p role="status" className={styles.progress}>
			<span>{t("library.saving")}</span>{" "}
			<span>{t(`library.job.${state}`)}</span>
		</p>
	);
}
