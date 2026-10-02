import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./Replaces.module.css";

export function Replaces({ path }: { path: string }) {
	const { t } = useTranslate();
	return <p className={styles.replaces}>{t("replaces.line", { path })}</p>;
}
