import { X } from "lucide-react";
import {
	genreIsEverywhere,
	genresOnTrack,
	suggestionKey,
	suggestionName,
	withGenre,
} from "@/domain/album/suggestions";
import type {
	AlbumView,
	GenreSuggestion,
	SoundtrackSuggestion,
	SpellingSuggestion,
	Suggestion,
} from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import type { Pending } from "./pending";
import styles from "./Suggestions.module.css";
import { useDismissed } from "./useDismissed";

export function Suggestions({
	view,
	pending,
}: {
	view: AlbumView;
	pending: Pending;
}) {
	const { t } = useTranslate();
	const dismissed = useDismissed(view);

	const files = view.preview?.files ?? [];
	const edits = pending.draft.action === "accept" ? pending.draft.edits : {};

	const shown = view.suggestions.filter(
		(suggestion) =>
			!dismissed.has(suggestionKey(suggestion)) &&
			!(
				suggestion.kind === "genre" &&
				genreIsEverywhere(view, edits, suggestion.genre)
			),
	);
	if (!view.preview || shown.length === 0) return null;

	function addGenre(genre: string) {
		for (const file of files)
			pending.setEdit(
				file.position,
				"genre",
				withGenre(genresOnTrack(view, edits, file.position), genre),
			);
	}

	// The neutral name, whatever the files are: the engine moves the folder for it alone.
	const putSpelling = (name: string) =>
		pending.setEdit("all", "albumartist", [name]);

	const dismiss = (suggestion: Suggestion) => (
		<button
			type="button"
			className={styles.button}
			aria-label={`${t("suggest.dismiss")} ${suggestionName(suggestion)}`}
			onClick={() => dismissed.dismiss(suggestionKey(suggestion))}
		>
			{t("suggest.dismiss")}
		</button>
	);

	const says = (suggestion: GenreSuggestion | SoundtrackSuggestion) =>
		t("suggest.genre", {
			genre: suggestion.genre,
			albums: suggestion.albums,
			of: suggestion.of,
			artist: suggestion.artist,
		});

	const chooseRow = (
		suggestion: SoundtrackSuggestion,
		label: string,
		onChoose: () => void,
	) => (
		<>
			<span className={styles.says}>{says(suggestion)}</span>
			<div className={styles.buttons}>
				<button type="button" className={styles.button} onClick={onChoose}>
					{label}
				</button>
				{dismiss(suggestion)}
			</div>
		</>
	);

	const spellingRow = (suggestion: SpellingSuggestion) => (
		<>
			<span className={styles.says}>
				{t("suggest.spelling", {
					artist: suggestion.artist,
					folders: suggestion.folders.map((folder) => folder.path).join(", "),
					landsIn: suggestion.lands_in,
				})}
			</span>
			<div className={styles.buttons}>
				{suggestion.folders.map((folder) => (
					<button
						key={folder.path}
						type="button"
						className={styles.button}
						onClick={() => putSpelling(folder.name)}
					>
						{t("suggest.useSpelling", { name: folder.name })}
					</button>
				))}
				{dismiss(suggestion)}
			</div>
		</>
	);

	// A genre is a pill: an artist with many albums brings many, and a row each buries the page.
	const genrePill = (suggestion: GenreSuggestion) => (
		<li key={suggestionKey(suggestion)} className={styles.pill}>
			<button
				type="button"
				className={styles.pillAdd}
				aria-label={t("suggest.add", { genre: suggestion.genre })}
				title={says(suggestion)}
				onClick={() => addGenre(suggestion.genre)}
			>
				<span aria-hidden="true">{suggestion.genre}</span>
				<span className={styles.count} aria-hidden="true">
					{suggestion.albums}/{suggestion.of}
				</span>
				<span className="visually-hidden">{says(suggestion)}</span>
			</button>
			<button
				type="button"
				className={styles.pillDismiss}
				aria-label={`${t("suggest.dismiss")} ${suggestion.genre}`}
				title={t("suggest.dismiss")}
				onClick={() => dismissed.dismiss(suggestionKey(suggestion))}
			>
				<X size={12} aria-hidden="true" />
			</button>
		</li>
	);

	const genres = shown.filter((suggestion) => suggestion.kind === "genre");
	const rows = shown.filter((suggestion) => suggestion.kind !== "genre");

	return (
		<ul className={styles.suggestions} aria-label={t("suggest.title")}>
			{rows.map((suggestion) => (
				<li key={suggestionKey(suggestion)} className={styles.row}>
					{suggestion.kind === "soundtrack"
						? chooseRow(
								suggestion,
								t("suggest.choose", { genre: suggestion.genre }),
								() => pending.setGame(suggestion.genre),
							)
						: spellingRow(suggestion)}
				</li>
			))}
			{genres[0] && (
				<li role="presentation" className={styles.lead}>
					{t("suggest.genres", { artist: genres[0].artist })}
				</li>
			)}
			{genres.map(genrePill)}
		</ul>
	);
}
