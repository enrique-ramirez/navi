import type { AlbumView } from "@/shared/api/types";
import { albumStatePhrase } from "@/shared/i18n/albumState";
import type { useTranslate } from "@/shared/i18n/useTranslate";

type Translate = ReturnType<typeof useTranslate>["t"];

// The server's `reason` sentence is for logs and never shown.
export function approveReason(view: AlbumView, t: Translate): string | null {
	const { code, hold, ok } = view.approvable;
	if (ok) return null;
	switch (code) {
		case "not-accepted":
			return t("approve.notAccepted");
		case "held":
			return hold?.detail
				? t("approve.held", {
						kind: t(`hold.${hold.kind}`),
						detail: hold.detail,
					})
				: t("approve.heldBare", { kind: hold ? t(`hold.${hold.kind}`) : "" });
		case "in-library":
			return t("state.inLibrary");
		default:
			return t(albumStatePhrase[view.state]);
	}
}
