import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./Confirm.module.css";

// Asks before something that cannot be undone. Cancel has the focus, so Enter
// alone never confirms; Escape and a click outside cancel.
export function Confirm({
	message,
	confirmLabel,
	onConfirm,
	onCancel,
}: {
	message: string;
	confirmLabel: string;
	onConfirm: () => void;
	onCancel: () => void;
}) {
	const { t } = useTranslate();
	const cancel = useRef<HTMLButtonElement>(null);

	useEffect(() => {
		const opener = document.activeElement as HTMLElement | null;
		cancel.current?.focus();
		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") onCancel();
		};
		document.addEventListener("keydown", onKey);
		return () => {
			document.removeEventListener("keydown", onKey);
			opener?.focus();
		};
	}, [onCancel]);

	return createPortal(
		// biome-ignore lint/a11y/noStaticElementInteractions: the backdrop's click is a pointer shortcut for Cancel, which stays reachable by keyboard.
		// biome-ignore lint/a11y/useKeyWithClickEvents: Escape, handled above, is the keyboard way out.
		<div
			className={styles.backdrop}
			onClick={(event) => {
				if (event.target === event.currentTarget) onCancel();
			}}
		>
			<div
				role="alertdialog"
				aria-modal="true"
				aria-labelledby="confirm-message"
				className={styles.dialog}
			>
				<p id="confirm-message">{message}</p>
				<div className={styles.buttons}>
					<button
						ref={cancel}
						type="button"
						className={styles.cancel}
						onClick={onCancel}
					>
						{t("confirm.cancel")}
					</button>
					<button type="button" className={styles.confirm} onClick={onConfirm}>
						{confirmLabel}
					</button>
				</div>
			</div>
		</div>,
		document.body,
	);
}
