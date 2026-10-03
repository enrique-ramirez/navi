import { Plus, X } from "lucide-react";
import { useId, useState } from "react";

import { lockedKind } from "@/domain/album/tagModel";
import { glossOf } from "@/domain/library/gloss";
import {
	applyEdits,
	carries,
	changedTags,
	displayKey,
	GENRE,
	isFormatsOwnKey,
	isTrack,
	type PanelTrack,
	panelRows,
	rawKeyOf,
} from "@/domain/library/shared";
import type { DraftEdit, TagNames, TrackRef } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./Panel.module.css";
import { TagField } from "./TagField";

const FIELDS = [
	{ mode: "set", label: "editor.setTag", hint: "editor.setPlaceholder" },
	{ mode: "add", label: "editor.addValue", hint: "editor.addPlaceholder" },
] as const;

export function Panel({
	tracks,
	selected,
	names,
	edits,
	genres,
	locked = [],
	readOnly = false,
	shows = () => true,
	onEdit,
}: {
	tracks: PanelTrack[];
	selected: TrackRef[];
	names: TagNames;
	edits: DraftEdit[];
	genres: string[];
	locked?: string[];
	shows?: (key: string) => boolean;
	/** The tags and their values stay on show with nothing to change them by. */
	readOnly?: boolean;
	onEdit: (edit: DraftEdit) => void;
}) {
	const { t } = useTranslate();
	const uid = useId();
	const [key, setKey] = useState("");
	const [value, setValue] = useState("");
	const [refusal, setRefusal] = useState<string | null>(null);

	const chosen = tracks.filter((track) =>
		selected.some((ref) => isTrack(track, ref)),
	);
	const now = applyEdits(chosen, edits, names);
	const changed = changedTags(chosen, edits, names);
	const rows = panelRows(chosen, now, changed, names).filter((row) =>
		shows(row.key),
	);

	function report(
		change: Partial<Pick<DraftEdit, "set" | "add" | "remove">>,
		tracksOf: TrackRef[] = selected,
	) {
		onEdit({ tracks: [...tracksOf], set: {}, add: {}, remove: {}, ...change });
	}

	// A tag with no readable name is one format's own, which the server refuses over tracks of more than one: its edits name the tracks that carry it.
	function reach(key: string): TrackRef[] {
		if (!isFormatsOwnKey(key, names)) return selected;
		return chosen
			.filter(
				(track) =>
					carries(track, key, names) ||
					carries(
						now.find((each) => isTrack(each, track)) ?? track,
						key,
						names,
					),
			)
			.map(({ album, path }) => ({ album, path }));
	}

	// A genre field takes a name on the list only.
	function refuseGenre(tag: string, text: string) {
		if (tag !== GENRE || genres.includes(text)) return false;
		setRefusal(t("editor.notGenre", { genre: text }));
		return true;
	}

	function commit(
		tag: string,
		text: string,
		change: (text: string) => Parameters<typeof report>[0],
	) {
		if (text === "" || refuseGenre(tag, text)) return false;
		setRefusal(null);
		report(change(text), reach(tag));
		return true;
	}

	function addByKey() {
		const typed = key.trim();
		const text = value.trim();
		if (typed === "" || text === "") return;

		const reached = chosen.flatMap((track) => {
			const raw = rawKeyOf(track, typed, names);
			return raw === null ? [] : [{ track, raw }];
		});
		const tags = reached.map(({ track, raw }) => displayKey(track, raw, names));
		const refused =
			reached.length === 0 ||
			lockedKind(typed, []) !== null ||
			reached.some(
				({ track, raw }) =>
					track.readonly.includes(raw) || lockedKind(raw, []) !== null,
			) ||
			tags.some((tag) => locked.includes(tag));
		if (refused) {
			setRefusal(t("editor.lockedKey", { key: typed }));
			return;
		}
		// Each format reads such a key its own way, and the server refuses the edit over tracks of more than one.
		if (
			new Set(chosen.map((track) => track.family)).size > 1 &&
			isFormatsOwnKey(typed, names)
		) {
			setRefusal(t("editor.oneFormat", { key: typed }));
			return;
		}
		if (tags.some((tag) => refuseGenre(tag, text))) return;

		setRefusal(null);
		// A tag no selected track carries is set; where some carry it the value is added after theirs.
		const carried = now.some((track) => carries(track, typed, names));
		report(
			carried ? { add: { [typed]: [text] } } : { set: { [typed]: [text] } },
		);
		setKey("");
		setValue("");
	}

	return (
		<div className={styles.panel}>
			{rows.map((row, at) => {
				const fixed = readOnly || row.readonly || locked.includes(row.key);
				const gloss = glossOf(row.key);
				return (
					<fieldset
						key={row.key}
						className={styles.row}
						aria-labelledby={`${uid}-${at}`}
						data-changed={changed.has(row.key) || undefined}
					>
						<span className={styles.name}>
							<span id={`${uid}-${at}`}>{row.key}</span>
							{gloss && <span className={styles.gloss}> ({t(gloss)})</span>}
						</span>
						{changed.has(row.key) && (
							<span className={styles.mark}>{t("tags.changed")}</span>
						)}
						<ul className={styles.values}>
							{row.values.map(({ value: each, count }) => (
								<li key={each} className={styles.value}>
									<span>{each}</span>
									{count < row.of && (
										<>
											{" "}
											<span className={styles.count}>
												{count}/{row.of}
											</span>
										</>
									)}
									{!fixed && (
										<button
											type="button"
											className={styles.icon}
											aria-label={t("editor.removeValueFrom", {
												value: each,
												tag: row.key,
											})}
											onClick={() => {
												setRefusal(null);
												report(
													{ remove: { [row.key]: [each] } },
													reach(row.key),
												);
											}}
										>
											<X size={12} aria-hidden="true" />
										</button>
									)}
								</li>
							))}
						</ul>
						{fixed ? (
							locked.includes(row.key) && (
								<span className={styles.hint}>{t("editor.lockedHere")}</span>
							)
						) : (
							<div className={styles.controls}>
								{FIELDS.map(({ mode, label, hint }) => (
									<TagField
										key={mode}
										label={t(label, { tag: row.key })}
										placeholder={t(hint)}
										suggestions={row.key === GENRE ? genres : undefined}
										onCommit={(text) =>
											commit(row.key, text, (each) => ({
												[mode]: { [row.key]: [each] },
											}))
										}
									/>
								))}
								{row.values.length > 0 && (
									<button
										type="button"
										className={styles.button}
										aria-label={t("editor.remove", { tag: row.key })}
										onClick={() => {
											setRefusal(null);
											report({ set: { [row.key]: null } }, reach(row.key));
										}}
									>
										{t("editor.remove", { tag: row.key })}
									</button>
								)}
							</div>
						)}
					</fieldset>
				);
			})}

			{!readOnly && (
				<div className={styles.add}>
					<input
						className={styles.input}
						aria-label={t("editor.tagKey")}
						placeholder={t("editor.tagKey")}
						value={key}
						disabled={chosen.length === 0}
						onChange={(event) => setKey(event.target.value)}
					/>
					<input
						className={styles.input}
						aria-label={t("editor.tagValue")}
						placeholder={t("editor.tagValue")}
						value={value}
						disabled={chosen.length === 0}
						onChange={(event) => setValue(event.target.value)}
						onKeyDown={(event) => {
							if (event.key !== "Enter") return;
							event.preventDefault();
							addByKey();
						}}
					/>
					<button
						type="button"
						className={styles.button}
						disabled={chosen.length === 0}
						onClick={addByKey}
					>
						<Plus size={14} aria-hidden="true" />
						{t("editor.addTag")}
					</button>
				</div>
			)}
			{refusal && (
				<p role="alert" className={styles.error}>
					{refusal}
				</p>
			)}
		</div>
	);
}
