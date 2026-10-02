import type { DiffRow } from "@/domain/album/diff";
import { editKeyOf } from "@/domain/album/diff";
import { lockedKind } from "@/domain/album/tagModel";
import type { AlbumView, Family } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { TagTable } from "@/shared/ui/TagTable";
import type { Pending } from "./pending";

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
	const names = view.names[family] ?? {};

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

	function add(key: string) {
		if (lockedKind(key, [])) return t("editor.lockedKey", { key });
		if (!rows.some((row) => row.key === key))
			pending.setEdit(scope, editKeyOf(view, key), [""]);
		return null;
	}

	return (
		<TagTable
			rows={rows}
			label={label}
			editable={pending.draft.action === "accept"}
			nameOf={(key) => names[key] ?? key}
			onSet={set}
			onUndo={(row) => pending.removeEdit(scope, editKeyOf(view, row.key))}
			onAdd={add}
		/>
	);
}
