import { ImageUp, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { useTranslate } from "@/shared/i18n/useTranslate";
import { droppedFile } from "@/shared/ui/droppedFile";
import { Parasol } from "@/shared/ui/Parasol";
import styles from "./CoverPicker.module.css";

export interface ShownCover {
	url: string;
	width: number;
	height: number;
	problem?: string | null;
}

export function CoverPicker({
	title,
	next,
	now,
	sides = true,
	nextAlt,
	noNext,
	noNow,
	pickLabel,
	disabled = false,
	undo,
	keep,
	onFile,
}: {
	title: string;
	next: ShownCover | null;
	now: ShownCover | null;
	/** False where the two are one cover, so there is nothing to tell apart. */
	sides?: boolean;
	nextAlt?: string;
	noNext: string;
	noNow: string;
	pickLabel: string;
	disabled?: boolean;
	undo?: { label: string; run: () => void } | null;
	keep?: { label: string; run: () => Promise<string | null> } | null;
	/** Takes the image; answers the sentence to show where it was refused, else `null`. */
	onFile: (file: File | null | undefined) => Promise<string | null>;
}) {
	const { t } = useTranslate();
	const [chosenSide, setSide] = useState<"next" | "now">("next");
	const [error, setError] = useState<string | null>(null);
	const [over, setOver] = useState(false);

	const side = sides ? chosenSide : "next";
	const shown = side === "now" ? now : next;

	async function settle(taking: Promise<string | null>) {
		setError(null);
		const refusal = await taking;
		if (refusal !== null) setError(refusal);
		else setSide("next");
	}

	async function take(file: File | null | undefined) {
		if (disabled) return;
		await settle(onFile(file));
	}

	return (
		<figure className={styles.card}>
			<label
				className={styles.drop}
				data-over={over || undefined}
				data-disabled={disabled || undefined}
				onDragOver={(event) => {
					event.preventDefault();
					setOver(true);
				}}
				onDragLeave={() => setOver(false)}
				onDrop={(event) => {
					event.preventDefault();
					setOver(false);
					void take(droppedFile(event.dataTransfer));
				}}
			>
				{shown ? (
					<img
						src={shown.url}
						alt={
							side === "next" && nextAlt !== undefined
								? nextAlt
								: t("album.cover", { title })
						}
						className={styles.image}
					/>
				) : (
					<div className={styles.placeholder}>
						<Parasol size={64} />
						<span>{side === "now" ? noNow : noNext}</span>
					</div>
				)}
				{!disabled && (
					<span className={styles.overlay}>
						<ImageUp size={20} aria-hidden="true" />
						{t("cover.replace")}
					</span>
				)}
				<input
					type="file"
					accept="image/*"
					className="visually-hidden"
					aria-label={pickLabel}
					disabled={disabled}
					onChange={(event) => {
						void take(event.target.files?.[0]);
						event.target.value = "";
					}}
				/>
			</label>

			<figcaption className={styles.caption}>
				{sides ? (
					<fieldset className={styles.toggle}>
						<legend className="visually-hidden">{t("cover.title")}</legend>
						<button
							type="button"
							aria-pressed={side === "next"}
							onClick={() => setSide("next")}
						>
							{t("cover.next")}
						</button>
						<button
							type="button"
							aria-pressed={side === "now"}
							onClick={() => setSide("now")}
						>
							{t("cover.now")}
						</button>
					</fieldset>
				) : (
					<span />
				)}
				<span className={styles.size}>
					{shown && (
						<span>
							{t("duplicate.by", { w: shown.width, h: shown.height })}
						</span>
					)}
					{side === "next" && undo && (
						<>
							{" · "}
							<button type="button" className={styles.link} onClick={undo.run}>
								{undo.label}
							</button>
						</>
					)}
					{side === "now" && now && keep && !disabled && (
						<>
							{" · "}
							<button
								type="button"
								className={styles.link}
								onClick={() => void settle(keep.run())}
							>
								{keep.label}
							</button>
						</>
					)}
				</span>
			</figcaption>

			{shown?.problem && (
				<p role="status" className={styles.warning}>
					<TriangleAlert size={14} aria-hidden="true" />
					{t("cover.fails", { problem: shown.problem })}
				</p>
			)}
			{error && (
				<p role="alert" className={styles.warning}>
					{error}
				</p>
			)}
		</figure>
	);
}
