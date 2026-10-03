import { Lock, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./TagTable.module.css";
import { bytesOf, formatValues, type Side, type TagRow } from "./tagRow";

type Translate = ReturnType<typeof useTranslate>["t"];

function text(side: Side, key: string, t: Translate): string {
	if (side === null) return "";
	if (side === "differs") return t("tags.differsAcross");
	return formatValues(
		side.map((value) => {
			const size = bytesOf(value);
			return size
				? t("tags.binary", { kind: key.split(":")[0] ?? key, size })
				: value;
		}),
	);
}

const split = (line: string) =>
	line
		.split(";")
		.map((value) => value.trim())
		.filter((value) => value !== "");

function ValueInput({
	row,
	label,
	differs,
	onCommit,
}: {
	row: TagRow;
	label: string;
	differs: string;
	onCommit: (values: string[]) => void;
}) {
	const { t } = useTranslate();
	const shown = row.next === "differs" ? "" : text(row.next, row.key, t);
	const [draft, setDraft] = useState(shown);
	useEffect(() => setDraft(shown), [shown]);

	const commit = () => {
		if (draft === shown) return;
		onCommit(split(draft));
	};

	return (
		<input
			className={styles.input}
			aria-label={label}
			value={draft}
			placeholder={
				row.next === "differs"
					? differs
					: row.next === null
						? t("tags.removedValue")
						: undefined
			}
			onChange={(event) => setDraft(event.target.value)}
			onBlur={commit}
			onKeyDown={(event) => {
				if (event.key === "Enter") {
					event.preventDefault();
					commit();
				} else if (event.key === "Escape") {
					setDraft(shown);
				}
			}}
		/>
	);
}

export function TagTable({
	rows,
	label,
	editable,
	nameOf,
	titleOf = (key) => key,
	empty,
	error = null,
	addLabel,
	describe,
	onSet,
	onUndo,
	onAdd,
}: {
	rows: TagRow[];
	label: string;
	editable: boolean;
	nameOf: (key: string) => string;
	titleOf?: (key: string) => string;
	empty?: string;
	/** The name of the field a new tag's key is typed into, where a page has two tables. */
	addLabel?: string;
	/** What a side says where the files differ on the tag; the table's own words where it answers nothing. */
	describe?: (row: TagRow, side: "now" | "next") => string | undefined;
	error?: string | null;
	/** The row's tag gets these values; `null` removes it. */
	onSet: (row: TagRow, values: string[] | null) => void;
	onUndo: (row: TagRow) => void;
	/** A row for the key typed; answers the sentence to show where the key is refused, else `null`. */
	onAdd: (key: string) => string | null;
}) {
	const { t } = useTranslate();
	const uid = useId();
	const [adding, setAdding] = useState("");
	const [addError, setAddError] = useState<string | null>(null);

	const reasons = {
		id: t("editor.fromRelease"),
		rating: t("editor.rating"),
		binary: t("editor.binary"),
		added: t("editor.added"),
		fixed: t("editor.fixed"),
	};

	function add() {
		const key = adding.trim();
		if (!key) return;
		const refusal = onAdd(key);
		setAddError(refusal);
		if (refusal === null) setAdding("");
	}

	return (
		<div className={styles.wrapper}>
			<table className={styles.table} aria-label={label}>
				<colgroup>
					<col className={styles.nameCol} />
					<col />
					<col />
					<col className={styles.actionCol} />
				</colgroup>
				<thead>
					<tr>
						<th scope="col">{t("tags.tag")}</th>
						<th scope="col">{t("tags.now")}</th>
						<th scope="col">{t("tags.next")}</th>
						<th scope="col">
							<span className="visually-hidden">{t("tags.actions")}</span>
						</th>
					</tr>
				</thead>
				<tbody>
					{rows.length === 0 && (
						<tr>
							<td colSpan={4} className={styles.empty}>
								{empty ?? t("tags.none")}
							</td>
						</tr>
					)}
					{rows.map((row) => {
						const name = nameOf(row.key);
						const differs = (side: "now" | "next") =>
							describe?.(row, side) ?? t("tags.differsAcross");
						const sideText = (side: "now" | "next") =>
							row[side] === "differs"
								? differs(side)
								: text(row[side], row.key, t);
						const nowText = sideText("now");
						const removedText =
							row.removedBy.length > 0
								? t("tags.removed", { rule: row.removedBy.join(", ") })
								: t("tags.removedValue");
						return (
							<tr
								key={row.key}
								data-change={row.change}
								data-edited={row.edited || undefined}
								data-locked={row.locked !== null || undefined}
							>
								<th scope="row" title={titleOf(row.key)}>
									{name}
									{row.edited && (
										<span className={styles.editedDot} title={t("tags.edited")}>
											<span className="visually-hidden">
												{t("tags.edited")}
											</span>
										</span>
									)}
								</th>
								<td
									className={styles.now}
									data-differs={row.now === "differs" || undefined}
								>
									{row.now === null ? (
										<span className={styles.absent}>—</span>
									) : (
										nowText
									)}
								</td>
								<td className={styles.next}>
									{row.locked !== null ? (
										<span className={styles.locked} title={reasons[row.locked]}>
											<Lock size={12} aria-hidden="true" />
											{sideText("next") || "—"}
										</span>
									) : row.next === null && !row.edited && !editable ? (
										<span className={styles.removed}>
											{nowText}
											<span className={styles.reason}>{removedText}</span>
										</span>
									) : editable ? (
										<>
											<ValueInput
												row={row}
												label={t("tags.newValue", { tag: name })}
												differs={differs("next")}
												onCommit={(values) => onSet(row, values)}
											/>
											{row.next === null && !row.edited && (
												<span className={styles.reason}>{removedText}</span>
											)}
										</>
									) : (
										sideText("next")
									)}
									{row.change !== "same" && (
										<span className="visually-hidden">
											{" "}
											{t(`tags.change.${row.change}`)}
										</span>
									)}
								</td>
								<td className={styles.action}>
									{row.locked === null &&
										editable &&
										(row.edited ? (
											<button
												type="button"
												className={styles.icon}
												title={t("tags.undoEdit", { tag: name })}
												aria-label={t("tags.undoEdit", { tag: name })}
												onClick={() => onUndo(row)}
											>
												<RotateCcw size={14} aria-hidden="true" />
											</button>
										) : row.next !== null ? (
											<button
												type="button"
												className={styles.icon}
												title={t("tags.remove", { tag: name })}
												aria-label={t("tags.remove", { tag: name })}
												onClick={() => onSet(row, null)}
											>
												<Trash2 size={14} aria-hidden="true" />
											</button>
										) : (
											Array.isArray(row.now) && (
												<button
													type="button"
													className={styles.keep}
													title={t("tags.keepTitle", { tag: name })}
													aria-label={t("tags.keepTitle", { tag: name })}
													onClick={() => onSet(row, row.now as string[])}
												>
													{t("tags.keep")}
												</button>
											)
										))}
								</td>
							</tr>
						);
					})}
				</tbody>
			</table>

			{editable && (
				<div className={styles.add}>
					<label htmlFor={`${uid}-add`} className="visually-hidden">
						{addLabel ?? t("editor.tagKey")}
					</label>
					<input
						id={`${uid}-add`}
						className={styles.input}
						placeholder={t("tags.addPlaceholder")}
						value={adding}
						onChange={(event) => setAdding(event.target.value)}
						onKeyDown={(event) => {
							if (event.key === "Enter") {
								event.preventDefault();
								add();
							}
						}}
					/>
					<button type="button" className={styles.button} onClick={add}>
						<Plus size={14} aria-hidden="true" />
						{t("editor.addTag")}
					</button>
				</div>
			)}
			{(addError ?? error) && (
				<p role="alert" className={styles.error}>
					{addError ?? error}
				</p>
			)}
		</div>
	);
}
