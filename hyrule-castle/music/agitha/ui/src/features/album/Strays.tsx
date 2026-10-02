import { File as FileIcon } from "lucide-react";
import { useId, useState } from "react";

import { isRunning } from "@/domain/album/albumQuery";
import { albumUrl } from "@/shared/api/album";
import type { AlbumView, Stray, StrayAnswer } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import pageStyles from "@/shared/styles/albumPage.module.css";
import type { Pending } from "./pending";
import styles from "./Strays.module.css";

// The names a kept image may take in the library; none is `cover`, which stays the album's own.
const LIBRARY_NAMES = [
	"front",
	"back",
	"medium",
	"booklet",
	"tray",
	"obi",
	"spine",
	"sticker",
	"poster",
	"liner",
	"track",
	"matrix-runout",
	"top",
	"bottom",
	"other",
];

function outcomeOf(
	stray: Stray,
	owned: Record<string, string | null>,
): StrayAnswer {
	if (Object.hasOwn(owned, stray.path)) {
		const name = owned[stray.path];
		return name === null || name === undefined
			? { delete: true }
			: { keep: name };
	}
	return stray.answer;
}

const extensionOf = (path: string) => {
	const name = path.split("/").pop() ?? path;
	const dot = name.lastIndexOf(".");
	const ext = dot > 0 ? name.slice(dot).toLowerCase() : "";
	return ext === ".jpeg" ? ".jpg" : ext;
};

// Names the engine accepts (`_LIBRARY_NAME` in musiclib/strays.py): booklet only numbered from 01, the
// others plain or numbered from 2. `reach(type)` is the highest number to offer for a type.
function suggestionsFor(path: string, reach: (type: string) => number) {
	const ext = extensionOf(path);
	return LIBRARY_NAMES.flatMap((type) => {
		const numbers = Array.from({ length: reach(type) }, (_, i) => i + 1);
		return type === "booklet"
			? numbers.map((n) => `booklet-${String(n).padStart(2, "0")}${ext}`)
			: [`${type}${ext}`, ...numbers.slice(1).map((n) => `${type}-${n}${ext}`)];
	});
}

const typeOfName = (name: string) => name.replace(/(?:-\d+)?\.[^.]*$/, "");

// Each type may be numbered past the images already kept under it, plus one for the next; an image
// still without a name could be of any type, so each counts toward every type.
function reachOf(outcomes: StrayAnswer[], undecided: number) {
	const kept = new Map<string, number>();
	for (const outcome of outcomes) {
		if (outcome && "keep" in outcome) {
			const type = typeOfName(outcome.keep);
			kept.set(type, (kept.get(type) ?? 0) + 1);
		}
	}
	return (type: string) => Math.max(3, (kept.get(type) ?? 0) + undecided + 1);
}

function Row({
	view,
	pending,
	stray,
	outcome,
	owned,
	disabled,
	reach,
}: {
	view: AlbumView;
	pending: Pending;
	stray: Stray;
	outcome: StrayAnswer;
	owned: boolean;
	disabled: boolean;
	reach: (type: string) => number;
}) {
	const { t } = useTranslate();
	const listId = useId();
	const [name, setName] = useState(
		outcome && "keep" in outcome ? outcome.keep : "",
	);
	const [broken, setBroken] = useState(false);
	const { path } = stray;
	const isImage = stray.kind === "image";
	const url = `${albumUrl(view)}/strays/${path.split("/").map(encodeURIComponent).join("/")}`;

	const what = outcome
		? "keep" in outcome
			? t("strays.kept", { name: outcome.keep })
			: t("strays.deleted")
		: t("strays.needsName");
	const against = stray.against ?? "";
	const why = owned
		? t("strays.why.owner")
		: {
				guessed: t("strays.why.guessed"),
				copy: t("strays.why.copy", { file: against }),
				lost: t("strays.why.lost", { file: against }),
				won: t("strays.why.won", { file: against }),
				owner: t("strays.why.owner"),
				"no guess": t("strays.why.noGuess"),
			}[stray.why];

	return (
		<tr className={styles.row} data-undecided={outcome === null || undefined}>
			<td className={styles.thumb}>
				{isImage && !broken ? (
					<a
						href={`${url}?full`}
						target="_blank"
						rel="noreferrer"
						className={styles.frame}
					>
						<img
							src={url}
							alt={path}
							className={styles.image}
							onError={() => setBroken(true)}
						/>
					</a>
				) : (
					<span className={styles.frame} data-icon>
						<FileIcon size={32} aria-hidden="true" />
					</span>
				)}
			</td>
			<td className={styles.what}>
				<span className={styles.path}>{path}</span>
				<strong className={styles.outcome}>{what}</strong>
				<span className={styles.why}>{why}</span>
			</td>
			<td>
				<fieldset className={styles.controls}>
					<legend className="visually-hidden">{path}</legend>
					<input
						type="text"
						value={name}
						list={isImage ? listId : undefined}
						aria-label={t("strays.nameFor", { path })}
						disabled={disabled}
						onChange={(event) => setName(event.target.value)}
					/>
					{isImage && (
						<datalist id={listId}>
							{suggestionsFor(path, reach).map((each) => (
								<option key={each} value={each} />
							))}
						</datalist>
					)}
					<button
						type="button"
						disabled={disabled || name.trim() === ""}
						onClick={() => pending.setStray(path, name.trim())}
					>
						{t("strays.keep")}
					</button>
					<button
						type="button"
						disabled={disabled}
						onClick={() => pending.setStray(path, null)}
					>
						{t("strays.delete")}
					</button>
				</fieldset>
			</td>
		</tr>
	);
}

export function Strays({
	view,
	pending,
}: {
	view: AlbumView;
	pending: Pending;
}) {
	const { t } = useTranslate();
	const strays = view.preview?.strays ?? [];
	if (strays.length === 0) return null;

	const owned = pending.draft.strays ?? {};
	const disabled = isRunning(view.state) || view.busy;
	const outcomes = strays.map((stray) => outcomeOf(stray, owned));
	const undecided = outcomes.filter((outcome) => outcome === null).length;
	const reach = reachOf(outcomes, undecided);
	// The plan's order decides, so a row stays put once the owner answers it.
	const rows = strays
		.map((stray, index) => ({ stray, outcome: outcomes[index] ?? null }))
		.sort(
			(a, b) =>
				Number(b.stray.answer === null) - Number(a.stray.answer === null),
		);

	return (
		<section className={styles.section} aria-labelledby="strays-title">
			<h2 id="strays-title" className={pageStyles.label}>
				{t("strays.title")}
				{" · "}
				<span className={styles.count}>
					{undecided === 0
						? t("strays.needNone")
						: t(undecided === 1 ? "strays.needOne" : "strays.needMany", {
								n: undecided,
							})}
				</span>
			</h2>
			<div className={styles.bulk}>
				<button
					type="button"
					disabled={disabled}
					onClick={() =>
						pending.deleteAllStrays(strays.map((stray) => stray.path))
					}
				>
					{t("strays.deleteAll")}
				</button>
				<button
					type="button"
					disabled={disabled}
					onClick={() => pending.clearStrays()}
				>
					{t("strays.useAgitha")}
				</button>
			</div>
			<table className={styles.table}>
				<thead>
					<tr>
						<th scope="col">
							<span className="visually-hidden">{t("strays.preview")}</span>
						</th>
						<th scope="col">{t("strays.file")}</th>
						<th scope="col">{t("strays.choice")}</th>
					</tr>
				</thead>
				<tbody>
					{rows.map(({ stray, outcome }) => (
						<Row
							key={`${stray.path}|${JSON.stringify(outcome)}`}
							view={view}
							pending={pending}
							stray={stray}
							outcome={outcome}
							owned={Object.hasOwn(owned, stray.path)}
							disabled={disabled}
							reach={reach}
						/>
					))}
				</tbody>
			</table>
		</section>
	);
}
