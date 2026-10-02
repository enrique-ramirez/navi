import { albumTags } from "@/domain/album/albumTags";
import { summaryOf } from "@/domain/album/summary";
import { summaryFacts } from "@/domain/album/summaryFacts";
import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { SideSummary } from "@/shared/ui/SideSummary";
import { CoverCard } from "./CoverCard";
import { Landing } from "./Landing";
import type { Pending } from "./pending";

export function AlbumSide({
	view,
	pending,
}: {
	view: AlbumView;
	pending: Pending;
}) {
	const { t } = useTranslate();
	const tags = albumTags(view);
	const title = tags.title || view.name;
	const summary = summaryOf(view);

	return (
		<SideSummary
			cover={<CoverCard view={view} pending={pending} title={title} />}
			title={title}
			artist={tags.artist}
			year={tags.year}
			genres={tags.genres}
			facts={summary ? summaryFacts(summary, t) : []}
		>
			<Landing view={view} />
		</SideSummary>
	);
}
