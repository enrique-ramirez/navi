import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Alert } from "@/shared/ui/Alert";
import styles from "./Outcome.module.css";

export function Outcome({ view }: { view: AlbumView }) {
	const { t } = useTranslate();
	const { state } = view;
	if (state === "in the library") {
		return (
			<div role="status" className={styles.status}>
				<span>{t("state.inLibrary")}</span>
				{view.library_path && (
					<code className={styles.path}>{view.library_path}</code>
				)}
			</div>
		);
	}
	const failed =
		state === "apply failed" ||
		state === "identify failed" ||
		state === "identify interrupted";
	if (!failed && state !== "written, not moved") return null;
	return (
		<Alert>
			{view.error && <p>{view.error}</p>}
			{view.step !== null && view.file !== null && (
				<p>{t("album.stepFailed", { step: view.step, file: view.file })}</p>
			)}
			{view.stderr !== "" && <pre className={styles.stderr}>{view.stderr}</pre>}
		</Alert>
	);
}
