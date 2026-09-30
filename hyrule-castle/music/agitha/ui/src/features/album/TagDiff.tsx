import { Lock, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useId, useState } from "react";

import type { DiffRow, Side } from "@/domain/album/diff";
import { editKeyOf } from "@/domain/album/diff";
import { bytesOf, lockedKind } from "@/domain/album/tagModel";
import type { AlbumView, Family } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import type { Pending } from "./pending";
import styles from "./TagDiff.module.css";

const SEPARATOR = "; ";

type Translate = ReturnType<typeof useTranslate>["t"];

function text(side: Side, key: string, t: Translate): string {
	if (side === null) return "";
	if (side === "differs") return t("tags.differsAcross");
	return side
		.map((value) => {
			const size = bytesOf(value);
			return size
				? t("tags.binary", { kind: key.split(":")[0] ?? key, size })
				: value;
		})
		.join(SEPARATOR);
}

const split = (line: string) =>
	line
		.split(";")
		.map((value) => value.trim())
		.filter((value) => value !== "");

function ValueInput({
	row,
	label,
	onCommit,
}: {
	row: DiffRow;
	label: string;
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
					? t("tags.differsAcross")
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

export function TagDiff({
	view,
	pending,
	rows,
	scope,
	family,
	label,
}: {
	view: AlbumView;
	pending: Pending;
	rows: DiffRow[];
	scope: string | "all";
	family: Family;
	label: string;
}) {
	const { t } = useTranslate();
	const uid = useId();
	const [adding, setAdding] = useState("");
	const [addError, setAddError] = useState<string | null>(null);
	const names = view.names[family] ?? {};
	const nameOf = (key: string) => names[key] ?? key;
	const editable = pending.draft.action === "accept";

	const reasons = {
		id: t("editor.fromRelease"),
		rating: t("editor.rating"),
		binary: t("editor.binary"),
		added: t("editor.added"),
	};

	function set(row: DiffRow, values: string[] | null) {
		const key = editKeyOf(view, row.key);
		const planned = view.preview?.files.find(
			(file) => scope === "all" || file.position === scope,
		)?.after[row.key];
		const same =
			values !== null &&
			planned !== undefined &&
			values.join("\u0000") === planned.join("\u0000");
		if (same) pending.removeEdit(scope, key);
		else
			pending.setEdit(scope, key, values && values.length > 0 ? values : null);
	}

	function add() {
		const key = adding.trim();
		if (!key) return;
		if (lockedKind(key, [])) {
			setAddError(t("editor.lockedKey", { key }));
			return;
		}
		setAddError(null);
		setAdding("");
		if (!rows.some((row) => row.key === key))
			pending.setEdit(scope, editKeyOf(view, key), [""]);
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
								{t("tags.none")}
							</td>
						</tr>
					)}
					{rows.map((row) => {
						const name = nameOf(row.key);
						const nowText = text(row.now, row.key, t);
						return (
							<tr
								key={row.key}
								data-change={row.change}
								data-edited={row.edited || undefined}
								data-locked={row.locked !== null || undefined}
							>
								<th scope="row" title={row.key}>
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
											{text(row.next, row.key, t) || "—"}
										</span>
									) : row.next === null && !row.edited ? (
										<span className={styles.removed}>
											{nowText}
											<span className={styles.reason}>
												{row.removedBy.length > 0
													? t("tags.removed", {
															rule: row.removedBy.join(", "),
														})
													: t("tags.removedValue")}
											</span>
										</span>
									) : editable ? (
										<ValueInput
											row={row}
											label={t("tags.newValue", { tag: name })}
											onCommit={(values) => set(row, values)}
										/>
									) : (
										text(row.next, row.key, t)
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
												onClick={() =>
													pending.removeEdit(scope, editKeyOf(view, row.key))
												}
											>
												<RotateCcw size={14} aria-hidden="true" />
											</button>
										) : row.next !== null ? (
											<button
												type="button"
												className={styles.icon}
												title={t("tags.remove", { tag: name })}
												aria-label={t("tags.remove", { tag: name })}
												onClick={() => set(row, null)}
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
													onClick={() => set(row, row.now as string[])}
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
						{t("editor.tagKey")}
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
			{addError && (
				<p role="alert" className={styles.error}>
					{addError}
				</p>
			)}
		</div>
	);
}
