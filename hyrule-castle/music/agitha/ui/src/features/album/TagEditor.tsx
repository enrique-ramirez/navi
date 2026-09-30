import { useForm } from "@tanstack/react-form";
import { Plus, X } from "lucide-react";
import { useId, useState } from "react";

import { genreKeyOf } from "@/domain/album/albumTags";
import {
	bytesOf,
	type Locked,
	lockedKind,
	type Model,
	modelOf,
} from "@/domain/album/tagModel";
import type { AlbumView, PlanFile } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import type { Pending } from "./pending";
import styles from "./TagEditor.module.css";

export function TagEditor({
	view,
	position,
	pending,
}: {
	view: AlbumView;
	position: string | "all";
	pending: Pending;
}) {
	const first = view.preview?.files.find(
		(file) => position === "all" || file.position === position,
	);
	const edits =
		pending.draft.action === "accept" && first
			? (pending.draft.edits[first.position] ?? {})
			: {};
	// One form per track and per preview: a new preview brings new written values.
	return (
		<EditorForm
			key={`${position}:${view.preview?.plan_digest ?? ""}`}
			view={view}
			position={position}
			pending={pending}
			model={modelOf(view, position, edits)}
			first={first}
		/>
	);
}

function EditorForm({
	view,
	position,
	pending,
	model,
	first,
}: {
	view: AlbumView;
	position: string | "all";
	pending: Pending;
	model: Model;
	first: PlanFile | undefined;
}) {
	const { t } = useTranslate();
	const uid = useId();
	const [keyError, setKeyError] = useState<string | null>(null);
	const names = view.names[model.family];
	const nameOf = (key: string) => names[key] ?? key;
	const genreKey = genreKeyOf(model.family);
	const written = (key: string) => Boolean(first && key in first.after);

	const form = useForm({
		defaultValues: {
			rows: model.rows,
			genres: model.genres ?? [],
			addKey: "",
			addGenre: "",
		},
	});

	function commit(key: string, values: string[]) {
		const kept = values.filter((value) => value !== "");
		if (kept.length > 0) pending.setEdit(position, key, kept);
		else if (written(key)) pending.setEdit(position, key, null);
		else pending.removeEdit(position, key);
	}

	function setGenres(next: string[]) {
		pending.setEdit(position, "genre", next.length > 0 ? next : null);
	}

	function addKey() {
		const key = form.getFieldValue("addKey").trim();
		if (!key) return;
		const present =
			key === genreKey ||
			form.getFieldValue("rows").some((row) => row.key === key) ||
			model.locked.some((each) => each.key === key);
		if (lockedKind(key, [])) {
			setKeyError(t("editor.lockedKey", { key }));
			return;
		}
		setKeyError(null);
		if (!present) form.pushFieldValue("rows", { key, values: [""] });
		form.setFieldValue("addKey", "");
	}

	const reasons: Record<Locked, string> = {
		id: t("editor.fromRelease"),
		rating: t("editor.rating"),
		binary: t("editor.binary"),
	};

	if (model.mixed) return <p>{t("editor.mixed")}</p>;

	return (
		<form
			className={styles.form}
			aria-label={t("editor.title")}
			onSubmit={(event) => event.preventDefault()}
		>
			<form.Subscribe selector={(state) => state.values.rows}>
				{(rows) =>
					rows.map((row, i) => {
						const id = `${uid}-${i}`;
						const name = nameOf(row.key);
						return (
							<div key={row.key} className={styles.row}>
								<label htmlFor={id} title={row.key} className={styles.name}>
									{name}
								</label>
								<div className={styles.values}>
									{row.values.map((_, j) => (
										// biome-ignore lint/suspicious/noArrayIndexKey: the values are an unkeyed list of strings
										<div key={j} className={styles.value}>
											<form.Field name={`rows[${i}].values[${j}]` as const}>
												{(field) => (
													<input
														id={j === 0 ? id : undefined}
														aria-label={
															j === 0
																? undefined
																: t("editor.valueN", { name, n: j + 1 })
														}
														value={field.state.value}
														onChange={(event) => {
															const next = form
																.getFieldValue(`rows[${i}].values` as const)
																.map((value, k) =>
																	k === j ? event.target.value : value,
																);
															field.handleChange(event.target.value);
															commit(row.key, next);
														}}
													/>
												)}
											</form.Field>
											{row.values.length > 1 && (
												<button
													type="button"
													className={styles.icon}
													aria-label={t("editor.removeValue", { tag: name })}
													onClick={() => {
														const next = row.values.filter((_v, k) => k !== j);
														form.removeFieldValue(
															`rows[${i}].values` as const,
															j,
														);
														commit(row.key, next);
													}}
												>
													<X size={14} aria-hidden="true" />
												</button>
											)}
										</div>
									))}
									<button
										type="button"
										className={styles.icon}
										aria-label={t("editor.addValue", { tag: name })}
										onClick={() =>
											form.pushFieldValue(`rows[${i}].values` as const, "")
										}
									>
										<Plus size={14} aria-hidden="true" />
									</button>
								</div>
								<button
									type="button"
									className={styles.icon}
									aria-label={t("editor.remove", { tag: name })}
									onClick={() => {
										form.removeFieldValue("rows", i);
										if (written(row.key))
											pending.setEdit(position, row.key, null);
										else pending.removeEdit(position, row.key);
									}}
								>
									<X size={14} aria-hidden="true" />
								</button>
							</div>
						);
					})
				}
			</form.Subscribe>

			<div className={styles.row}>
				<span className={styles.name}>{t("editor.genres")}</span>
				{model.genres === null ? (
					<span className={styles.reason}>{t("editor.differs")}</span>
				) : (
					<form.Field name="genres" mode="array">
						{(field) => (
							<div className={styles.values}>
								<ul className={styles.chips} aria-label={t("editor.genres")}>
									{field.state.value.map((genre, i) => (
										<li key={genre} className={styles.chip}>
											{genre}
											<button
												type="button"
												className={styles.icon}
												aria-label={t("editor.removeGenre", { genre })}
												onClick={() => {
													const next = field.state.value.filter(
														(_g, k) => k !== i,
													);
													field.removeValue(i);
													setGenres(next);
												}}
											>
												<X size={12} aria-hidden="true" />
											</button>
										</li>
									))}
								</ul>
								<form.Field name="addGenre">
									{(add) => (
										<input
											aria-label={t("editor.addGenre")}
											value={add.state.value}
											onChange={(event) => add.handleChange(event.target.value)}
											onKeyDown={(event) => {
												if (event.key !== "Enter") return;
												event.preventDefault();
												const genre = add.state.value.trim();
												if (!genre) return;
												add.handleChange("");
												if (field.state.value.includes(genre)) return;
												const next = [...field.state.value, genre];
												field.pushValue(genre);
												setGenres(next);
											}}
										/>
									)}
								</form.Field>
							</div>
						)}
					</form.Field>
				)}
			</div>

			{model.differing.map((key) => (
				<div key={key} className={styles.row}>
					<span className={styles.name} title={key}>
						{nameOf(key)}
					</span>
					<span className={styles.reason}>{t("editor.differs")}</span>
				</div>
			))}

			{model.locked.map(({ key, kind, value }) => (
				<div key={key} className={styles.row}>
					<span className={styles.name} title={key}>
						{nameOf(key)}
					</span>
					<span className={styles.locked}>
						{kind === "binary" ? binaryText(key, value, t) : value}
					</span>
					<span className={styles.reason}>{reasons[kind]}</span>
				</div>
			))}

			<div className={styles.add}>
				<form.Field name="addKey">
					{(field) => (
						<input
							aria-label={t("editor.tagKey")}
							value={field.state.value}
							onChange={(event) => field.handleChange(event.target.value)}
							onKeyDown={(event) => {
								if (event.key !== "Enter") return;
								event.preventDefault();
								addKey();
							}}
						/>
					)}
				</form.Field>
				<button type="button" className={styles.button} onClick={addKey}>
					{t("editor.addTag")}
				</button>
			</div>
			{keyError && <p role="alert">{keyError}</p>}
		</form>
	);
}

function binaryText(
	key: string,
	value: string,
	t: ReturnType<typeof useTranslate>["t"],
) {
	const size = bytesOf(value);
	return size
		? t("tags.binary", { kind: key.split(":")[0] ?? key, size })
		: value;
}
