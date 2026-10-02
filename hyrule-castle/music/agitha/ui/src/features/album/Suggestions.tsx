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
		suggestion: GenreSuggestion | SoundtrackSuggestion,
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

	return (
		<ul className={styles.suggestions} aria-label={t("suggest.title")}>
			{shown.map((suggestion) => (
				<li key={suggestionKey(suggestion)}>
					{suggestion.kind === "genre"
						? chooseRow(
								suggestion,
								t("suggest.add", { genre: suggestion.genre }),
								() => addGenre(suggestion.genre),
							)
						: suggestion.kind === "soundtrack"
							? chooseRow(
									suggestion,
									t("suggest.choose", { genre: suggestion.genre }),
									() => pending.setGame(suggestion.genre),
								)
							: spellingRow(suggestion)}
				</li>
			))}
		</ul>
	);
}
