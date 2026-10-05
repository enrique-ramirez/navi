import { factsOf, trackTitle } from "@/domain/album/albumTags";
import { formatLength } from "@/domain/album/format";
import { mimeOf, usePlayer } from "@/domain/player/usePlayer";
import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { TrackRows } from "@/shared/ui/TrackRows";
import { failingOf, failingWords } from "./failingWords";
import styles from "./TrackList.module.css";

interface Props {
	view: AlbumView;
	selected: string | null;
	onSelect: (position: string) => void;
	changes: Record<string, number>;
}

function numberOf(position: string, multiDisc: boolean) {
	const [disc = "", track = ""] = position.split("-");
	const padded = track.padStart(2, "0");
	return multiDisc ? `${disc}-${padded}` : padded;
}

export function TrackList({ view, selected, onSelect, changes }: Props) {
	const { t } = useTranslate();
	const player = usePlayer();
	const files = view.preview?.files ?? [];
	const failing = failingOf(view);
	const discs = new Set(files.map((file) => file.position.split("-")[0]));

	return (
		<TrackRows
			player={player}
			selected={selected}
			onSelect={onSelect}
			rows={files.map((file) => {
				const facts = factsOf(view, file.position);
				const unfit = failing.get(file.position);
				return {
					id: file.position,
					number: numberOf(file.position, discs.size > 1),
					title: trackTitle(view, file),
					file: facts?.path_now ?? null,
					length: facts ? formatLength(facts.length) : "",
					audio: facts
						? {
								format: facts.format,
								url: facts.audio_url,
								mime: mimeOf(facts.format),
							}
						: null,
					changes: changes[file.position] ?? 0,
					note: unfit && (
						<span className={styles.unfit}>{failingWords(unfit, t)}</span>
					),
				};
			})}
		/>
	);
}
