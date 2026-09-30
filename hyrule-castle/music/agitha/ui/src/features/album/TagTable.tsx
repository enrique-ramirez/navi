import { familyOf } from "@/domain/album/albumTags";
import type { AlbumView, PlanFile } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./TagTable.module.css";

const BYTES = /\((\d+) bytes\)\s*$/;

interface Row {
	key: string;
	before: string;
	after: string;
	binary: { before: boolean; after: boolean };
	/** The rules that removed the tag from this file, when its `after` lacks it. */
	removedBy: string[];
	differs: { before: boolean; after: boolean };
	changed: boolean;
}

const isBinary = (key: string, value: string) =>
	key.startsWith("APIC:") || BYTES.test(value);

const joined = (values: string[] | undefined) => (values ?? []).join(" / ");

function rowsFor(view: AlbumView, files: PlanFile[], all: boolean): Row[] {
	const residue = view.preview?.residue ?? [];
	const keys: string[] = [];
	for (const file of files)
		for (const key of [...Object.keys(file.after), ...Object.keys(file.before)])
			if (!keys.includes(key)) keys.push(key);

	return keys.map((key) => {
		const befores = files.map((file) => file.before[key]);
		const afters = files.map((file) => file.after[key]);
		const differs = (side: (string[] | undefined)[]) =>
			all && new Set(side.map(joined)).size > 1;
		const removedBy = all
			? []
			: residue
					.filter(
						(entry) =>
							entry.file === files[0]?.source &&
							entry.key === key &&
							!(afters[0]?.length ?? 0),
					)
					.map((entry) => entry.rule);
		const before = joined(befores[0]);
		const after = joined(afters[0]);
		return {
			key,
			before,
			after,
			binary: {
				before: (befores[0] ?? []).some((value) => isBinary(key, value)),
				after: (afters[0] ?? []).some((value) => isBinary(key, value)),
			},
			removedBy,
			differs: { before: differs(befores), after: differs(afters) },
			changed: files.some(
				(file) => joined(file.before[key]) !== joined(file.after[key]),
			),
		};
	});
}

export function TagTable({
	view,
	position,
}: {
	view: AlbumView;
	position: string | "all";
}) {
	const { t } = useTranslate();
	const all = position === "all";
	const every = view.preview?.files ?? [];
	const files = all
		? every
		: every.filter((file) => file.position === position);
	const family = files[0] ? familyOf(view, files[0]) : "id3";
	const names = view.names[family];
	const rows = rowsFor(view, files, all);

	function shown(
		row: Row,
		side: "before" | "after",
		file: PlanFile | undefined,
	) {
		if (row.differs[side]) return t("tags.differs");
		if (row.binary[side]) {
			const values = (file?.[side][row.key] ?? []).map((value) => {
				const size = BYTES.exec(value)?.[1] ?? "0";
				return t("tags.binary", { kind: row.key.split(":")[0] ?? "", size });
			});
			return values.join(" / ");
		}
		return row[side];
	}

	return (
		<div className={styles.wrapper}>
			<table className={styles.table} aria-label={t("tags.title")}>
				<thead>
					<tr>
						<th scope="col">{t("tags.tag")}</th>
						<th scope="col">{t("tags.before")}</th>
						<th scope="col">{t("tags.after")}</th>
					</tr>
				</thead>
				<tbody>
					{rows.map((row) => (
						<tr key={row.key} className={row.changed ? styles.changed : ""}>
							<th scope="row" title={row.key}>
								{names[row.key] ?? row.key}
							</th>
							<td>{shown(row, "before", files[0])}</td>
							<td>
								{row.removedBy.length > 0
									? t("tags.removed", { rule: row.removedBy.join(", ") })
									: shown(row, "after", files[0])}
								{row.changed && (
									<span className="visually-hidden"> {t("tags.changed")}</span>
								)}
							</td>
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
}
