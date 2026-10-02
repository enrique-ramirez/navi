import { useTranslate } from "@/shared/i18n/useTranslate";
import { Alert } from "@/shared/ui/Alert";
import { Confirm } from "@/shared/ui/Confirm";
import type { useDraftFlow } from "./useDraftFlow";

/** What a draft flow says after its buttons: a failure, Reload where the page went stale, and the leave check. */
export function FlowNotices({
	flow,
	failed,
	onReload,
}: {
	flow: ReturnType<typeof useDraftFlow>;
	/** The page's own queries failed, besides the preview. */
	failed: boolean;
	onReload: () => void;
}) {
	const { t } = useTranslate();
	return (
		<>
			{/* The page's own sentence is for where the server served none. */}
			{(failed || flow.previewFailed) && !flow.message && (
				<p role="alert">{t("library.failed")}</p>
			)}
			{flow.message && <Alert>{flow.message}</Alert>}
			{flow.stale && (
				<button type="button" onClick={onReload}>
					{t("library.reload")}
				</button>
			)}

			{flow.blocker.status === "blocked" && (
				<Confirm
					message={t("library.leave")}
					confirmLabel={t("library.leaveConfirm")}
					onCancel={flow.blocker.reset}
					onConfirm={flow.blocker.proceed}
				/>
			)}
		</>
	);
}
