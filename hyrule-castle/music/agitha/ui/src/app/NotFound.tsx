import { useTranslate } from "@/shared/i18n/useTranslate";

export function NotFound() {
	const { t } = useTranslate();
	return (
		<main>
			<p>{t("app.notFound")}</p>
		</main>
	);
}
